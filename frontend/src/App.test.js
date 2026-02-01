import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import App from './App';

// Mock axios
jest.mock('axios', () => ({
  get: jest.fn(() => Promise.resolve({ data: [] })),
  post: jest.fn(() => Promise.resolve({ data: { id: 'test-job-id', status: 'pending', filename: 'test.mp3' } })),
  delete: jest.fn(() => Promise.resolve({ data: { status: 'deleted' } })),
}));

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

describe('App', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.getItem.mockReturnValue(null);
  });

  test('renders Track2stem header', () => {
    render(<App />);
    expect(screen.getByText(/Track2stem/i)).toBeInTheDocument();
  });

  test('renders upload section', () => {
    render(<App />);
    expect(screen.getByText(/Upload Audio File/i)).toBeInTheDocument();
  });

  test('renders upload button', () => {
    render(<App />);
    expect(screen.getByRole('button', { name: /Upload & Process/i })).toBeInTheDocument();
  });

  test('upload button is disabled when no file is selected', () => {
    render(<App />);
    const uploadButton = screen.getByRole('button', { name: /Upload & Process/i });
    expect(uploadButton).toBeDisabled();
  });

  test('renders stem mode options', () => {
    render(<App />);
    expect(screen.getByText(/Output Mode/i)).toBeInTheDocument();
    expect(screen.getByText(/All 6 Stems/i)).toBeInTheDocument();
    expect(screen.getByText(/Isolate One/i)).toBeInTheDocument();
  });

  test('renders file input for audio files', () => {
    render(<App />);
    const fileInput = document.getElementById('file-input');
    expect(fileInput).toBeInTheDocument();
    expect(fileInput).toHaveAttribute('type', 'file');
    expect(fileInput).toHaveAttribute('accept', '.mp3,.wav,.flac,.ogg,.m4a,.aac,audio/*');
  });

  test('renders footer with technology info', () => {
    render(<App />);
    expect(screen.getByText(/Powered by Demucs/i)).toBeInTheDocument();
  });

  test('stem mode radio buttons are functional', () => {
    render(<App />);
    const allStemsRadio = screen.getByRole('radio', { name: /All 6 Stems/i });
    const isolateRadio = screen.getByRole('radio', { name: /Isolate One/i });
    
    // Default is 'all'
    expect(allStemsRadio).toBeChecked();
    expect(isolateRadio).not.toBeChecked();
    
    // Click isolate
    fireEvent.click(isolateRadio);
    expect(isolateRadio).toBeChecked();
    expect(allStemsRadio).not.toBeChecked();
  });

  test('isolate stem selector appears when isolate mode is selected', () => {
    render(<App />);
    const isolateRadio = screen.getByRole('radio', { name: /Isolate One/i });
    
    // Selector should not be visible initially
    expect(screen.queryByText(/Choose stem to isolate/i)).not.toBeInTheDocument();
    
    // Click isolate mode
    fireEvent.click(isolateRadio);
    
    // Selector should now be visible
    expect(screen.getByText(/Choose stem to isolate/i)).toBeInTheDocument();
  });
});
