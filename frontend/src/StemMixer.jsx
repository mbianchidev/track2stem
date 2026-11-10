import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';

const label = (stem) => (stem[0].toUpperCase() + stem.slice(1)).replaceAll('_', ' ');
const defaults = (job) => Object.fromEntries(job.mix_stems.map((stem) => [stem, job.gains?.[stem] ?? 1]));

export default function StemMixer({ job, apiBase, onJobChange }) {
  const [gains, setGains] = useState(() => defaults(job));
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const context = useRef(null);
  const buffers = useRef(new Map());
  const nodes = useRef(new Map());
  const playback = useRef(null);
  const request = useRef(null);
  const latestGains = useRef(gains);

  const stop = () => {
    request.current?.abort();
    const active = playback.current;
    playback.current = null;
    for (const source of active?.sources || []) source.stop();
    nodes.current.clear();
    setPlaying(false);
  };

  useEffect(() => {
    latestGains.current = gains;
    if (context.current) {
      for (const [stem, node] of nodes.current) {
        node.gain.setTargetAtTime(gains[stem], context.current.currentTime, .015);
      }
    }
  }, [gains]);

  useEffect(() => () => {
    request.current?.abort();
    const active = playback.current;
    playback.current = null;
    for (const source of active?.sources || []) source.stop();
    if (context.current && context.current.state !== 'closed') {
      context.current.close().catch((failure) => console.error('Could not close the stem preview:', failure));
    }
  }, []);

  const play = async () => {
    setLoading(true);
    setError('');
    const controller = new AbortController();
    request.current = controller;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('This browser does not support audio mixing. Export the mix to listen instead.');
      context.current ||= new AudioContext();
      const audioContext = context.current;
      await audioContext.resume();
      await Promise.all(job.mix_stems.map(async (stem) => {
        if (buffers.current.has(stem)) return;
        const response = await fetch(`${apiBase}/stems/${encodeURIComponent(job.id)}/${encodeURIComponent(stem)}`, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Could not load ${stem} (${response.status}). Separate the source again if stored audio is missing.`);
        const decoded = await audioContext.decodeAudioData(await response.arrayBuffer());
        if (!controller.signal.aborted) buffers.current.set(stem, decoded);
      }));
      if (controller.signal.aborted) return;
      const durations = job.mix_stems.map((stem) => buffers.current.get(stem).duration);
      if (Math.max(...durations) - Math.min(...durations) > .01) throw new Error('Stored instruments have different lengths and cannot be synchronized.');
      const group = { sources: [], remaining: job.mix_stems.length };
      playback.current = group;
      const when = audioContext.currentTime + .05;
      for (const stem of job.mix_stems) {
        const source = audioContext.createBufferSource();
        const gain = audioContext.createGain();
        source.buffer = buffers.current.get(stem);
        gain.gain.value = latestGains.current[stem];
        source.connect(gain);
        gain.connect(audioContext.destination);
        nodes.current.set(stem, gain);
        source.onended = () => {
          source.disconnect();
          gain.disconnect();
          if (playback.current === group && --group.remaining === 0) {
            playback.current = null;
            nodes.current.clear();
            setPlaying(false);
          }
        };
        source.start(when);
        group.sources.push(source);
      }
      setPlaying(true);
    } catch (failure) {
      if (!controller.signal.aborted) {
        console.error('Stem preview failed:', failure);
        setError(failure.message);
        stop();
      }
    } finally {
      setLoading(false);
    }
  };

  const exportMix = async () => {
    setExporting(true);
    setError('');
    setNotice('');
    try {
      const response = await axios.post(`${apiBase}/jobs/${job.id}/mix`, { gains });
      onJobChange(response.data);
      setNotice('Mix exported. The stem downloads below now use these levels.');
    } catch (failure) {
      console.error('Mix export failed:', failure);
      const detail = failure.response?.data;
      setError(`Mix export failed: ${typeof detail === 'string' ? detail : detail?.error || failure.message}. Previous downloads are unchanged.`);
    } finally {
      setExporting(false);
    }
  };

  return (
    <section className="stem-mixer" aria-labelledby={`mixer-${job.id}`}>
      <div className="mixer-heading">
        <h3 id={`mixer-${job.id}`}>Instrument levels</h3>
        <button type="button" className="quiet-button" onClick={() => setGains(Object.fromEntries(job.mix_stems.map((stem) => [stem, 1])))}
          disabled={exporting}>Reset levels</button>
      </div>
      <p className="setting-help">100% is the original level. Backing tracks keep a separate control for every instrument.</p>
      <div className="mixer-channels">
        {job.mix_stems.map((stem) => {
          const percentage = Math.round(gains[stem] * 100);
          const decibels = percentage === 0 ? 'Muted' : `${(20 * Math.log10(gains[stem])).toFixed(1)} dB`;
          const id = `gain-${job.id}-${stem}`;
          return (
            <div className="mixer-channel" key={stem}>
              <label htmlFor={id}>{label(stem)}<span className="sr-only"> volume</span></label>
              <output htmlFor={id}>{percentage}% <span>{decibels}</span></output>
              <input id={id} type="range" min="0" max="400" step="1" value={percentage} disabled={exporting}
                aria-valuetext={`${percentage} percent, ${decibels}`}
                onChange={(event) => {
                  setGains((previous) => ({ ...previous, [stem]: Number(event.target.value) / 100 }));
                  setNotice('');
                }} />
            </div>
          );
        })}
      </div>
      <div className="mixer-actions">
        <button type="button" className="download-button" onClick={play} disabled={playing || loading}>
          {loading ? 'Loading audio...' : 'Play mix'}
        </button>
        <button type="button" className="quiet-button" onClick={stop} disabled={!playing && !loading}>Stop</button>
        <button type="button" className="download-button" onClick={exportMix} disabled={exporting}>
          {exporting ? 'Exporting mix...' : 'Export mix'}
        </button>
      </div>
      <p className="setting-help">Boosts can clip during preview. Exports follow the selected rescale or clamp setting.</p>
      {error && <p role="alert" className="error">{error}</p>}
      <p role="status" className="setting-help">{notice}</p>
    </section>
  );
}
