// Jest-DOM adds custom jest matchers for asserting on DOM nodes.
// Learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';

// Mock Web Audio API for tests
window.AudioContext = jest.fn().mockImplementation(() => ({
  decodeAudioData: jest.fn().mockResolvedValue({
    getChannelData: jest.fn().mockReturnValue(new Float32Array(1000)),
  }),
  close: jest.fn(),
}));

window.webkitAudioContext = window.AudioContext;
