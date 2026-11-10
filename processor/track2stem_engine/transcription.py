import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import librosa
import mido
import numpy as np
from scipy.signal import find_peaks

from .audio import check_cancelled
from .models import get_session
from .tuning import infer_tuning

DRUM_NAMES = {
    35: "Acoustic kick", 36: "Kick", 37: "Side stick", 38: "Snare", 39: "Hand clap", 40: "Electric snare",
    41: "Low tom", 42: "Closed hi-hat", 44: "Pedal hi-hat", 46: "Open hi-hat", 47: "Mid tom",
    49: "Crash", 50: "High tom", 51: "Ride", 52: "China cymbal", 54: "Tambourine", 55: "Splash",
    56: "Cowbell", 58: "Vibraslap", 64: "Congas/timbales", 70: "Shaker", 71: "Whistle", 73: "Guiro",
    75: "Claves/wood block", 78: "Cuica", 81: "Triangle",
}
DIVISIONS = 480
DRUM_POSITIONS = {
    35: ("F", 4), 36: ("F", 4), 37: ("C", 5), 38: ("C", 5), 39: ("C", 5), 40: ("C", 5),
    41: ("A", 4), 42: ("G", 5), 44: ("D", 4), 46: ("G", 5), 47: ("D", 5),
    49: ("A", 5), 50: ("E", 5), 51: ("F", 5), 52: ("A", 5), 54: ("F", 5),
    55: ("A", 5), 56: ("G", 5), 58: ("B", 4), 64: ("E", 5), 70: ("G", 5),
    71: ("B", 5), 73: ("B", 5), 75: ("C", 5), 78: ("D", 5), 81: ("F", 5),
}
CYMBALS = {42, 44, 46, 49, 51, 52, 54, 55, 70}


def pitched_notes(audio, sample_rate, instrument, model_dir, report, cancelled):
    session = get_session("basic-pitch", model_dir, report, cancelled)
    mono = librosa.resample(audio.mean(axis=1), orig_sr=sample_rate, target_sr=22050)
    window, border, step = 43844, 15, 142
    prefix = border * 256
    padded = np.pad(mono, (prefix, window))
    frames, onsets = [], []
    count = math.ceil(len(mono) / (step * 256))
    for index in range(count):
        check_cancelled(cancelled)
        start = index * step * 256
        data = padded[start:start + window].astype(np.float32)[None, :, None]
        prediction, attack = session.run(
            ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
            {"serving_default_input_2:0": data},
        )
        frames.append(prediction[0, border:-border])
        onsets.append(attack[0, border:-border])
        report(82 + int(4 * (index + 1) / count), f"Transcribing {instrument} {index + 1}/{count}")
    probabilities = np.concatenate(frames)[:math.ceil(len(mono) / 256)]
    attacks = np.concatenate(onsets)[:len(probabilities)]
    low, high = (24, 67) if instrument == "bass" else (28, 88)
    notes = []
    for midi in range(low, high + 1):
        column = midi - 21
        active = probabilities[:, column] >= .3
        edges = np.flatnonzero(active & ~np.r_[False, active[:-1]])
        peaks, _ = find_peaks(attacks[:, column], height=.6, distance=5)
        starts = sorted({*edges, *[peak for peak in peaks if active[peak] and
                                  all(abs(peak - edge) > 3 for edge in edges)]})
        for index, first in enumerate(starts):
            last = first + 1
            limit = starts[index + 1] if index + 1 < len(starts) else len(active)
            while last < limit and active[last]:
                last += 1
            if (last - first) * 256 / 22050 < .07:
                continue
            start = max(0, first * 256 / 22050)
            end = min(len(audio) / sample_rate, last * 256 / 22050)
            notes.append({"start": round(float(start), 5), "end": round(float(end), 5), "pitch": midi,
                          "velocity": max(1, min(127, round(float(probabilities[first:last, column].mean()) * 127)))})
    return sorted(notes, key=lambda note: (note["start"], note["pitch"]))


def tempo_map(values):
    points = []
    for value in sorted(values or [{"time": 0, "bpm": 120}], key=lambda entry: entry["time"]):
        time, bpm = float(value["time"]), float(value["bpm"])
        if not math.isfinite(time) or not math.isfinite(bpm) or time < 0 or not 20 <= bpm <= 400:
            raise ValueError("Invalid tempo map")
        if not points or bpm != points[-1]["bpm"]:
            points.append({"time": time, "bpm": bpm})
    if not points or points[0]["time"] != 0:
        raise ValueError("Tempo map must start at zero")
    return points


def ticks_at(seconds, points):
    ticks = 0.
    for index, point in enumerate(points):
        end = points[index + 1]["time"] if index + 1 < len(points) else seconds
        ticks += max(0, min(seconds, end) - point["time"]) * point["bpm"] / 60 * DIVISIONS
        if end >= seconds:
            break
    return round(ticks)


def meter_map(values):
    if values is None:
        return [{"time": 0, "numerator": 4, "denominator": 4, "pulse_quarters": 1, "assumed": True}]
    points = []
    for value in sorted(values, key=lambda entry: entry["time"]):
        time = float(value["time"])
        numerator, denominator = value["numerator"], value["denominator"]
        pulse = float(value.get("pulse_quarters", 1))
        if (not math.isfinite(time) or time < 0 or not isinstance(numerator, int) or isinstance(numerator, bool)
                or not 1 <= numerator <= 32 or not isinstance(denominator, int) or isinstance(denominator, bool)
                or denominator not in (1, 2, 4, 8, 16, 32)
                or not math.isfinite(pulse) or not 0 < pulse <= 8):
            raise ValueError("Invalid meter map")
        if points and time == points[-1]["time"]:
            raise ValueError("Meter changes must have distinct times")
        point = {"time": time, "numerator": numerator, "denominator": denominator, "pulse_quarters": pulse}
        if not points or any(point[key] != points[-1][key] for key in ("numerator", "denominator", "pulse_quarters")):
            points.append(point)
    return points


def write_midi(notes, instrument, path, points, meters=None):
    midi = mido.MidiFile(ticks_per_beat=DIVISIONS)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    channel = 9 if instrument == "drums" else 0
    events = [(ticks_at(point["time"], points), 0,
               mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(point["bpm"]))) for point in points]
    signatures = meter_map(meters)
    events.extend((ticks_at(point["time"], points), 0,
                   mido.MetaMessage("time_signature", numerator=point["numerator"], denominator=point["denominator"],
                                    clocks_per_click=round(24 * point["pulse_quarters"]))) for point in signatures)
    track.append(mido.MetaMessage("track_name", name=f"Track2stem {instrument} estimate"))
    if not signatures:
        track.append(mido.MetaMessage("text", text="Meter undetermined; notes use an unmetered quarter-note clock"))
    if instrument != "drums":
        track.append(mido.Message("program_change", program=33 if instrument == "bass" else 24, channel=channel))
    for note in notes:
        start = ticks_at(note["start"], points)
        end = max(start + 1, ticks_at(note["end"], points))
        events.extend(((start, 2, mido.Message("note_on", note=note["pitch"], velocity=note["velocity"], channel=channel)),
                       (end, 1, mido.Message("note_off", note=note["pitch"], velocity=0, channel=channel))))
    previous = 0
    for tick, _, message in sorted(events, key=lambda event: (event[0], event[1])):
        message.time = tick - previous
        track.append(message)
        previous = tick
    midi.save(path)


def assign_frets(notes, instrument, tuning=None):
    tuning = list(tuning or infer_tuning(notes, instrument)["strings"])
    assigned = []
    active = []
    position = 0
    for note in notes:
        active = [(end, string) for end, string in active if end > note["start"] + .025]
        occupied = {string for _, string in active}
        candidates = [(abs(note["pitch"] - pitch - position) + (note["pitch"] - pitch) * .1,
                       len(tuning) - index, note["pitch"] - pitch)
                      for index, pitch in enumerate(tuning)
                      if 0 <= note["pitch"] - pitch <= 24 and len(tuning) - index not in occupied]
        entry = dict(note)
        if candidates:
            _, string, fret = min(candidates)
            entry.update(string=string, fret=fret)
            active.append((note["end"], string))
            position = fret
        assigned.append(entry)
    return assigned, tuning


def add_pitch(parent, midi):
    pitch = ET.SubElement(parent, "pitch")
    names = (("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
             ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0))
    step, alter = names[midi % 12]
    ET.SubElement(pitch, "step").text = step
    if alter:
        ET.SubElement(pitch, "alter").text = str(alter)
    ET.SubElement(pitch, "octave").text = str(midi // 12 - 1)


def write_musicxml(notes, instrument, path, points, tuning, meters=None):
    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = f"Track2stem {instrument} transcription (estimate)"
    parts = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(parts, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = instrument.title()
    if instrument == "drums":
        pitches = sorted({note["pitch"] for note in notes})
        for pitch in pitches:
            declaration = ET.SubElement(score_part, "score-instrument", id=f"D{pitch}")
            ET.SubElement(declaration, "instrument-name").text = DRUM_NAMES.get(pitch, f"GM percussion {pitch}")
        for pitch in pitches:
            declaration = ET.SubElement(score_part, "midi-instrument", id=f"D{pitch}")
            ET.SubElement(declaration, "midi-channel").text = "10"
            ET.SubElement(declaration, "midi-unpitched").text = str(pitch + 1)
    part = ET.SubElement(root, "part", id="P1")
    quantized = [{**note, "first": round(ticks_at(note["start"], points) / 30) * 30,
                  "last": max(round(ticks_at(note["start"], points) / 30) * 30 + 30,
                              round(ticks_at(note["end"], points) / 30) * 30)} for note in notes]
    end = max((note["last"] for note in quantized), default=DIVISIONS * 4)
    signatures = [{**point, "tick": ticks_at(point["time"], points)} for point in meter_map(meters)]
    offset, measure_number, previous_signature = 0, 0, None
    while offset < end:
        signature = next((point for point in reversed(signatures) if point["tick"] <= offset), None)
        next_change = next((point["tick"] for point in signatures if point["tick"] > offset), end)
        bar = round(DIVISIONS * signature["numerator"] * 4 / signature["denominator"]) if signature else end - offset
        measure_end = min(offset + bar, end, next_change)
        measure_number += 1
        measure = ET.SubElement(part, "measure", number=str(measure_number))
        if measure_end - offset < bar:
            measure.set("implicit", "yes")
        if offset == 0 or signature != previous_signature:
            attributes = ET.SubElement(measure, "attributes")
            if offset == 0:
                ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
            time = ET.SubElement(attributes, "time")
            if signature:
                ET.SubElement(time, "beats").text = str(signature["numerator"])
                ET.SubElement(time, "beat-type").text = str(signature["denominator"])
            else:
                ET.SubElement(time, "senza-misura")
        if offset == 0:
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = "percussion" if instrument == "drums" else "TAB"
            if tuning:
                details = ET.SubElement(attributes, "staff-details")
                ET.SubElement(details, "staff-lines").text = str(len(tuning))
                for index, pitch in enumerate(tuning):
                    staff_tuning = ET.SubElement(details, "staff-tuning", line=str(index + 1))
                    element = ET.Element("note")
                    add_pitch(element, pitch)
                    for child in element.find("pitch"):
                        ET.SubElement(staff_tuning, f"tuning-{child.tag}").text = child.text
        for point in points:
            tick = ticks_at(point["time"], points)
            if offset <= tick < measure_end:
                direction = ET.SubElement(measure, "direction")
                kind = ET.SubElement(direction, "direction-type")
                ET.SubElement(kind, "words").text = f"{point['bpm']:g} BPM"
                ET.SubElement(direction, "offset").text = str(tick - offset)
                ET.SubElement(direction, "sound", tempo=str(point["bpm"]))
        boundaries = sorted({offset, measure_end,
                             *[note[key] for note in quantized for key in ("first", "last")
                               if offset < note[key] < measure_end]})
        for first, last in zip(boundaries, boundaries[1:]):
            active = [note for note in quantized if note["first"] <= first < note["last"]]
            for index, item in enumerate(active or [None]):
                element = ET.SubElement(measure, "note")
                if index:
                    ET.SubElement(element, "chord")
                if item is None:
                    ET.SubElement(element, "rest")
                elif instrument == "drums":
                    unpitched = ET.SubElement(element, "unpitched")
                    step, octave = DRUM_POSITIONS.get(item["pitch"], ("C", 5))
                    ET.SubElement(unpitched, "display-step").text = step
                    ET.SubElement(unpitched, "display-octave").text = str(octave)
                else:
                    add_pitch(element, item["pitch"])
                ET.SubElement(element, "duration").text = str(last - first)
                if item:
                    ties = [kind for kind, condition in (("stop", item["first"] < first), ("start", item["last"] > last)) if condition]
                    for kind in ties:
                        ET.SubElement(element, "tie", type=kind)
                    if instrument == "drums":
                        ET.SubElement(element, "instrument", id=f"D{item['pitch']}")
                        if item["pitch"] in CYMBALS:
                            ET.SubElement(element, "notehead").text = "circle-x" if item["pitch"] == 46 else "x"
                    notation = ET.SubElement(element, "notations")
                    for kind in ties:
                        ET.SubElement(notation, "tied", type=kind)
                    if "string" in item:
                        technical = ET.SubElement(notation, "technical")
                        ET.SubElement(technical, "string").text = str(item["string"])
                        ET.SubElement(technical, "fret").text = str(item["fret"])
        offset, previous_signature = measure_end, signature
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def write_transcription(notes, instrument, directory, tempos=None, meters=None, tuning_estimate=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    points = tempo_map(tempos)
    tuning_estimate = None if instrument == "drums" else tuning_estimate or infer_tuning(notes, instrument)
    assigned, tuning = (notes, None) if instrument == "drums" else assign_frets(notes, instrument, tuning_estimate["strings"])
    paths = {f"{instrument}_{kind}": str(directory / f"{instrument}.{extension}")
             for kind, extension in (("tabs", "txt"), ("score", "musicxml"), ("midi", "mid"), ("notes", "json"))}
    write_midi(notes, instrument, paths[f"{instrument}_midi"], points, meters)
    write_musicxml(assigned, instrument, paths[f"{instrument}_score"], points, tuning, meters)
    signatures = meter_map(meters)
    description = ", ".join(f"{point['numerator']}/{point['denominator']} at {point['time']:g}s" for point in signatures)
    lines = [f"Track2stem {instrument} tablature", "Automatic estimate. Review notes, rhythm and tuning before use.",
             "MIDI and MusicXML preserve timing; text rows use seconds.",
             "Meter: " + (description if signatures else "undetermined; unmetered notation."),
             "Without timing analysis, MIDI uses a 120 BPM reference clock."]
    if meters is None:
        lines.append("Meter: assumed 4/4 because no meter analysis was supplied.")
    if tuning:
        lines.append("Proposed open strings, low to high: " + ", ".join(librosa.midi_to_note(tuning, unicode=False)))
        lines.append("Tuning and fingerings are proposals, not a unique solution.")
        if tuning_estimate["ambiguous"]:
            lines.append("Tuning is ambiguous; candidate: " + tuning_estimate["candidates"][0]["name"]
                         if tuning_estimate["candidates"] else "Tuning could not be inferred; standard strings used for notation.")
    if not notes:
        lines.append("No notes were detected. Try a cleaner isolated stem.")
    for item in assigned:
        name = DRUM_NAMES.get(item["pitch"], str(item["pitch"])) if instrument == "drums" else (
            f"string {item['string']} fret {item['fret']}" if "string" in item else f"unassigned MIDI pitch {item['pitch']}")
        lines.append(f"{item['start']:8.3f}-{item['end']:8.3f}s  {name}")
    Path(paths[f"{instrument}_tabs"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
    Path(paths[f"{instrument}_notes"]).write_text(json.dumps({
        "instrument": instrument, "notes": notes, "fingerings": assigned, "tuning": tuning,
        "tuning_estimate": tuning_estimate,
        "method": "ADT_STR setting-tau-0.8; 26 drum classes; CC-BY-SA-4.0 component"
                  if instrument == "drums" else "Basic Pitch note estimates with proposed string/fret assignments",
        "tempo_changes": points, "meter_changes": signatures, "estimated": True,
        "warnings": ["Unassigned pitches remain in MIDI; their string/fret could not be resolved."]
                    if any("string" not in note for note in assigned) and tuning else [],
    }, allow_nan=False), encoding="utf-8")
    return paths
