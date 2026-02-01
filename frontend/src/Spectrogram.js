import React, { useRef, useEffect, useState, useCallback } from 'react';

const Spectrogram = ({ audioUrl, audioFile, title, height = 100 }) => {
  const canvasRef = useRef(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const hasDrawnRef = useRef(false);

  const drawWaveform = useCallback(async () => {
    if (!audioUrl && !audioFile) return;
    if (hasDrawnRef.current && !audioFile) return; // Don't redraw for URLs once drawn
    
    setIsLoading(true);
    setError(null);
    
    try {
      const audioContext = new (window.AudioContext || window.webkitAudioContext)();
      let arrayBuffer;
      
      if (audioFile) {
        // Read from File object
        arrayBuffer = await audioFile.arrayBuffer();
      } else {
        // Fetch from URL
        const response = await fetch(audioUrl);
        if (!response.ok) throw new Error('Failed to fetch audio');
        arrayBuffer = await response.arrayBuffer();
      }
      
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      const channelData = audioBuffer.getChannelData(0);
      
      const canvas = canvasRef.current;
      if (!canvas) return;
      
      const ctx = canvas.getContext('2d');
      const width = canvas.width;
      const canvasHeight = canvas.height;
      const centerY = canvasHeight / 2;
      
      // Clear canvas with dark background
      ctx.fillStyle = '#0a0a1a';
      ctx.fillRect(0, 0, width, canvasHeight);
      
      // Draw center line
      ctx.strokeStyle = 'rgba(100, 100, 120, 0.3)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, centerY);
      ctx.lineTo(width, centerY);
      ctx.stroke();
      
      // Calculate samples per pixel
      const samplesPerPixel = Math.floor(channelData.length / width);
      
      // Create gradient for waveform
      const gradient = ctx.createLinearGradient(0, 0, 0, canvasHeight);
      gradient.addColorStop(0, '#4da6ff');
      gradient.addColorStop(0.3, '#66b3ff');
      gradient.addColorStop(0.5, '#80bfff');
      gradient.addColorStop(0.7, '#66b3ff');
      gradient.addColorStop(1, '#4da6ff');
      
      ctx.fillStyle = gradient;
      
      // Draw waveform bars (like the screenshot)
      for (let x = 0; x < width; x++) {
        const startSample = x * samplesPerPixel;
        const endSample = Math.min(startSample + samplesPerPixel, channelData.length);
        
        // Find min and max in this segment
        let min = 0;
        let max = 0;
        for (let i = startSample; i < endSample; i++) {
          const sample = channelData[i];
          if (sample < min) min = sample;
          if (sample > max) max = sample;
        }
        
        // Scale to canvas height with some padding
        const amplitude = Math.max(Math.abs(min), Math.abs(max));
        const barHeight = amplitude * (canvasHeight - 10);
        
        // Draw symmetric bar from center
        const topY = centerY - barHeight;
        const bottomY = centerY + barHeight;
        
        ctx.fillRect(x, topY, 1, bottomY - topY);
      }
      
      audioContext.close();
      hasDrawnRef.current = true;
      
    } catch (err) {
      console.error('Waveform error:', err);
      setError('Could not generate waveform');
    } finally {
      setIsLoading(false);
    }
  }, [audioUrl, audioFile]);

  useEffect(() => {
    drawWaveform();
  }, [drawWaveform]);

  return (
    <div className="spectrogram-container">
      {title && <p className="spectrogram-title">{title}</p>}
      {isLoading && <div className="spectrogram-loading">Generating waveform...</div>}
      {error && <div className="spectrogram-error">{error}</div>}
      <canvas 
        ref={canvasRef} 
        width={600} 
        height={height}
        className="spectrogram-canvas"
        style={{ display: isLoading || error ? 'none' : 'block' }}
      />
    </div>
  );
};

export default Spectrogram;
