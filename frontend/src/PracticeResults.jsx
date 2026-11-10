import React from 'react';

const ARTIFACT_NAMES = {
  analysis: 'Full analysis (JSON)', tempo: 'Tempo map (CSV)', meter: 'Meter map (CSV)', sections: 'Song sections (CSV)',
  click: 'Click track (WAV)', lyrics: 'Lyrics (text)', lyrics_srt: 'Lyrics (SRT)', lyrics_words: 'Word timings (JSON)',
  vocal_split: 'Vocal separation details (JSON)',
  guitar_tabs: 'Guitar tabs', guitar_score: 'Guitar score (MusicXML)', guitar_midi: 'Guitar MIDI', guitar_notes: 'Guitar notes (JSON)',
  bass_tabs: 'Bass tabs', bass_score: 'Bass score (MusicXML)', bass_midi: 'Bass MIDI', bass_notes: 'Bass notes (JSON)',
  drums_tabs: 'Drum tabs', drums_score: 'Drum score (MusicXML)', drums_midi: 'Drum MIDI', drums_notes: 'Drum hits (JSON)',
};
const timecode = (seconds) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

export default function PracticeResults({ job, apiBase }) {
  const analysis = job.analysis;
  const meters = [...new Set((analysis?.meter_changes || []).map((entry) => `${entry.numerator}/${entry.denominator}`))];
  const artifacts = Object.keys(job.artifacts || {});
  if (!analysis && !artifacts.length) return null;
  return (
    <section className="practice-results" aria-labelledby={`practice-${job.id}`}>
      <h3 id={`practice-${job.id}`}>Practice tools</h3>
      {analysis && (
        <>
          <dl className="musical-summary">
            <div><dt>Tempo</dt><dd>{analysis.bpm} <span>Quarter-note BPM, variable grid</span></dd></div>
            <div><dt>Estimated meter</dt><dd>{meters.join(' to ') || 'Undetermined'}
              {!meters.length && <span>Unmetered notation; clicks are not forced to 4/4.</span>}</dd></div>
            <div><dt>Estimated key</dt><dd>{analysis.key?.name || 'Uncertain'}</dd></div>
            {Object.entries(analysis.tuning || {}).map(([instrument, value]) => (
              <div key={instrument}><dt>{instrument} tuning</dt><dd>{value.candidate || 'Not determined'}
                {value.lowest_note && <span>Lowest detected note: {value.lowest_note}</span>}
                {Number.isFinite(value.analyzed_seconds) && <span>Analyzed {timecode(value.analyzed_seconds)} of audio</span>}
                {value.ambiguous && <span>Ambiguous; review the ranked alternatives in the full analysis.</span>}</dd></div>
            ))}
          </dl>
          {analysis.sections?.length > 0 && (
            <div className="song-sections">
              <h4>Section estimates</h4>
              <ol>
                {analysis.sections.map((section, index) => (
                  <li key={`${section.start}-${index}`}>
                    <span className="section-time">{timecode(section.start)} - {timecode(section.end)}</span>
                    <span>{section.label}</span>
                    <span className="section-confidence">{Math.round(section.confidence * 100)}% estimation score</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          <p className="setting-help">Tempo, key, tuning and section names are estimates. Review the grid and labels before using them in a DAW.</p>
        </>
      )}
      {job.lyrics && (
        <details className="lyrics-preview">
          <summary>Lyrics</summary>
          {job.lyrics.model && <p className="setting-help">Local model: {job.lyrics.model}, CPU inference.</p>}
          <p className="setting-help">{job.lyrics.warning}</p>
          <pre>{job.lyrics.text || 'No words detected.'}</pre>
        </details>
      )}
      {job.vocal_split && <p className="setting-help">{job.vocal_split.warning} Weight license: {job.vocal_split.weight_license}.</p>}
      <div className="artifact-downloads">
        {artifacts.map((name) => (
          <a key={name} href={`${apiBase}/artifacts/${encodeURIComponent(job.id)}/${encodeURIComponent(name)}`} download>
            {ARTIFACT_NAMES[name] || name.replaceAll('_', ' ')}
          </a>
        ))}
      </div>
    </section>
  );
}
