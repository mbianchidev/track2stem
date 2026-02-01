import React from 'react';
import { render, screen } from '@testing-library/react';
import Spectrogram from './Spectrogram';

describe('Spectrogram', () => {
  test('renders with title', () => {
    render(<Spectrogram title="Test Waveform" />);
    expect(screen.getByText('Test Waveform')).toBeInTheDocument();
  });

  test('renders canvas element', () => {
    const { container } = render(<Spectrogram title="Test" />);
    const canvas = container.querySelector('canvas');
    expect(canvas).toBeInTheDocument();
  });

  test('canvas has correct dimensions', () => {
    const { container } = render(<Spectrogram height={80} />);
    const canvas = container.querySelector('canvas');
    expect(canvas).toHaveAttribute('width', '600');
    expect(canvas).toHaveAttribute('height', '80');
  });

  test('renders spectrogram container', () => {
    const { container } = render(<Spectrogram title="Input Audio" />);
    const spectrogramContainer = container.querySelector('.spectrogram-container');
    expect(spectrogramContainer).toBeInTheDocument();
  });

  test('renders without crashing when no audio source provided', () => {
    render(<Spectrogram title="Empty Spectrogram" />);
    expect(screen.getByText('Empty Spectrogram')).toBeInTheDocument();
  });

  test('canvas is visible when no audio source provided', () => {
    const { container } = render(<Spectrogram title="Test" />);
    const canvas = container.querySelector('canvas');
    expect(canvas).toHaveStyle('display: block');
  });
});
