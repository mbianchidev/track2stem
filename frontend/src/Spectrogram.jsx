import { useRef, useEffect, useState } from 'react';

const WAVEFORM_ERROR = 'Waveform unavailable. You can still process or download the audio.';

const Spectrogram = ({ audioUrl, audioFile, title, label, height = 100 }) => {
  const canvasRef = useRef(null);
  const [channelData, setChannelData] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    let audioContext;
    let closing = false;
    const controller = new AbortController();

    const closeContext = () => {
      if (!audioContext || closing) return;
      closing = true;
      audioContext.close().catch((err) => console.warn('Could not close waveform audio context:', err));
    };

    setChannelData(null);
    setError(null);
    if (!audioUrl && !audioFile) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    const loadAudio = async () => {
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) throw new Error('This browser does not support Web Audio');
        audioContext = new AudioContext();

        let arrayBuffer;
        if (audioFile) {
          arrayBuffer = await audioFile.arrayBuffer();
        } else {
          const response = await fetch(audioUrl, { signal: controller.signal });
          if (!response.ok) throw new Error(`Could not fetch waveform audio (HTTP ${response.status})`);
          arrayBuffer = await response.arrayBuffer();
        }

        if (!active) return;
        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
        const samples = audioBuffer.getChannelData(0);
        if (samples.length === 0) throw new Error('Decoded audio contains no samples');
        if (active) setChannelData(samples);
      } catch (err) {
        if (active) {
          console.error('Waveform error:', err);
          setError(WAVEFORM_ERROR);
        }
      } finally {
        closeContext();
        if (active) setIsLoading(false);
      }
    };

    loadAudio();
    return () => {
      active = false;
      controller.abort();
      closeContext();
    };
  }, [audioUrl, audioFile]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !channelData) return;

    const drawWaveform = () => {
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        console.error('Waveform error: the browser could not create a 2D canvas context');
        setError(WAVEFORM_ERROR);
        return;
      }

      const pixelRatio = window.devicePixelRatio || 1;
      const width = Math.max(1, Math.round((canvas.getBoundingClientRect().width || 600) * pixelRatio));
      const canvasHeight = Math.round(height * pixelRatio);
      canvas.width = width;
      canvas.height = canvasHeight;
      const centerY = canvasHeight / 2;
      const halfHeight = Math.max(0, centerY - 4 * pixelRatio);
      const theme = getComputedStyle(document.documentElement);
      ctx.fillStyle = theme.getPropertyValue('--color-bg-primary').trim() || '#15171a';
      ctx.fillRect(0, 0, width, canvasHeight);
      ctx.strokeStyle = theme.getPropertyValue('--color-border').trim() || '#343a43';
      ctx.lineWidth = pixelRatio;
      ctx.beginPath();
      ctx.moveTo(0, centerY);
      ctx.lineTo(width, centerY);
      ctx.stroke();
      ctx.fillStyle = theme.getPropertyValue('--color-accent-primary').trim() || '#e9ad45';

      for (let x = 0; x < width; x++) {
        const start = Math.floor(x * channelData.length / width);
        const end = Math.min(channelData.length, Math.max(start + 1, Math.floor((x + 1) * channelData.length / width)));
        let amplitude = 0;
        for (let sample = start; sample < end; sample++) {
          amplitude = Math.max(amplitude, Math.abs(channelData[sample]));
        }
        const barHeight = Math.min(1, amplitude) * halfHeight;
        ctx.fillRect(x, centerY - barHeight, 1, barHeight * 2);
      }
    };

    drawWaveform();
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(drawWaveform);
      observer.observe(canvas);
      return () => observer.disconnect();
    }
    window.addEventListener('resize', drawWaveform);
    return () => window.removeEventListener('resize', drawWaveform);
  }, [channelData, height]);

  return (
    <div className="spectrogram-container">
      {title && <p className="spectrogram-title">{title}</p>}
      {isLoading && <div className="spectrogram-loading" role="status">Generating waveform...</div>}
      {error && <div className="spectrogram-error" role="status">{error}</div>}
      <canvas
        ref={canvasRef}
        width={600}
        height={height}
        role="img"
        aria-label={label || title || 'Audio waveform'}
        className="spectrogram-canvas"
        style={{ height: `${height}px`, display: isLoading || error ? 'none' : 'block' }}
      />
    </div>
  );
};

export default Spectrogram;
