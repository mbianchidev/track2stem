// jest-dom adds custom Vitest matchers for asserting on DOM nodes.
// Learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Mock Web Audio API for tests
window.AudioContext = vi.fn().mockImplementation(() => ({
  decodeAudioData: vi.fn().mockResolvedValue({
    getChannelData: vi.fn().mockReturnValue(new Float32Array(1000)),
  }),
  close: vi.fn(),
}));

window.webkitAudioContext = window.AudioContext;
