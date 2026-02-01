import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentJob, setCurrentJob] = useState(null);
  const [processingProgress, setProcessingProgress] = useState({ progress: 0, stage: '' });
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState('');

  const API_BASE = process.env.REACT_APP_API_URL || '/api';

  useEffect(() => {
    fetchJobs();
  }, []);

  useEffect(() => {
    if (currentJob && (currentJob.status === 'pending' || currentJob.status === 'processing')) {
      const interval = setInterval(() => {
        fetchJobStatus(currentJob.id);
        fetchProcessingProgress(currentJob.id);
      }, 2000);
      return () => clearInterval(interval);
    } else {
      setProcessingProgress({ progress: 0, stage: '' });
    }
  }, [currentJob]);

  const fetchJobs = async () => {
    try {
      const response = await axios.get(`${API_BASE}/jobs`);
      setJobs(response.data || []);
    } catch (err) {
      console.error('Failed to fetch jobs:', err);
    }
  };

  const fetchJobStatus = async (jobId) => {
    try {
      const response = await axios.get(`${API_BASE}/jobs/${jobId}`);
      setCurrentJob(response.data);
      if (response.data.status === 'completed' || response.data.status === 'failed') {
        fetchJobs();
        setProcessingProgress({ progress: 100, stage: 'Done!' });
      }
    } catch (err) {
      console.error('Failed to fetch job status:', err);
    }
  };

  const fetchProcessingProgress = async (jobId) => {
    try {
      const response = await axios.get(`${API_BASE}/processing-status/${jobId}`);
      if (response.data) {
        setProcessingProgress(response.data);
      }
    } catch (err) {
      // Silently ignore - progress endpoint may not be available
    }
  };

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      const validTypes = ['audio/mpeg', 'audio/wav', 'audio/flac', 'audio/ogg', 'audio/m4a', 'audio/aac'];
      const validExtensions = ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'];
      const extension = selectedFile.name.split('.').pop().toLowerCase();
      
      if (validTypes.includes(selectedFile.type) || validExtensions.includes(extension)) {
        setFile(selectedFile);
        setError('');
      } else {
        setError('Please select a valid audio file (mp3, wav, flac, ogg, m4a, aac)');
        setFile(null);
      }
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    setUploading(true);
    setUploadProgress(0);
    setError('');

    try {
      const response = await axios.post(`${API_BASE}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          setUploadProgress(percentCompleted);
        },
      });
      
      setCurrentJob(response.data);
      setFile(null);
      // Reset file input
      const fileInput = document.getElementById('file-input');
      if (fileInput) fileInput.value = '';
    } catch (err) {
      setError('Upload failed: ' + (err.response?.data || err.message));
    } finally {
      setUploading(false);
    }
  };

  const handleDownload = (jobId, stem) => {
    window.open(`${API_BASE}/download/${jobId}/${stem}`, '_blank');
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  return (
    <div className="App">
      <header className="App-header">
        <h1>🎵 Track2stem</h1>
        <p>Turn any track into multi-stem</p>
      </header>

      <main className="App-main">
        <div className="upload-section">
          <h2>Upload Audio File</h2>
          <div className="upload-box">
            <input
              id="file-input"
              type="file"
              accept=".mp3,.wav,.flac,.ogg,.m4a,.aac,audio/*"
              onChange={handleFileChange}
              disabled={uploading}
            />
            {file && <p className="file-name">Selected: {file.name}</p>}
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="upload-button"
            >
              {uploading ? `Uploading... ${uploadProgress}%` : 'Upload & Process'}
            </button>
            {uploading && (
              <div className="progress-container">
                <div className="progress-bar" style={{ width: `${uploadProgress}%` }}></div>
              </div>
            )}
          </div>
          {error && <p className="error">{error}</p>}
        </div>

        {currentJob && (
          <div className="current-job">
            <h2>Current Job</h2>
            <div className="job-card">
              <div className="job-header">
                <span className="job-filename">{currentJob.filename}</span>
                <span className={`job-status status-${currentJob.status}`}>
                  {currentJob.status}
                </span>
              </div>
              <p className="job-id">Job ID: {currentJob.id}</p>
              <p className="job-date">Created: {formatDate(currentJob.created_at)}</p>
              
              {(currentJob.status === 'processing' || currentJob.status === 'pending') && (
                <div className="processing-indicator">
                  <div className="progress-container large">
                    <div 
                      className="progress-bar processing" 
                      style={{ width: `${processingProgress.progress || 10}%` }}
                    ></div>
                  </div>
                  <p className="progress-text">
                    {processingProgress.stage || 'Starting processing...'} ({processingProgress.progress || 0}%)
                  </p>
                  <p className="processing-note">🎧 AI is separating your audio stems. This may take 5-15 minutes depending on file size.</p>
                </div>
              )}

              {currentJob.status === 'completed' && currentJob.output_files && (
                <div className="stems">
                  <h3>Download Stems:</h3>
                  <div className="stem-buttons">
                    {Object.keys(currentJob.output_files).map((stem) => (
                      <button
                        key={stem}
                        onClick={() => handleDownload(currentJob.id, stem)}
                        className="stem-button"
                      >
                        <span className="stem-icon">🎼</span>
                        {stem.charAt(0).toUpperCase() + stem.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {currentJob.status === 'failed' && (
                <p className="error">Error: {currentJob.error}</p>
              )}
            </div>
          </div>
        )}

        {jobs.length > 0 && (
          <div className="jobs-section">
            <h2>Recent Jobs</h2>
            <div className="jobs-list">
              {jobs.slice().reverse().slice(0, 10).map((job) => (
                <div key={job.id} className="job-card-small">
                  <div className="job-header">
                    <span className="job-filename">{job.filename}</span>
                    <span className={`job-status status-${job.status}`}>
                      {job.status}
                    </span>
                  </div>
                  {job.status === 'completed' && job.output_files && (
                    <div className="stem-buttons-small">
                      {Object.keys(job.output_files).map((stem) => (
                        <button
                          key={stem}
                          onClick={() => handleDownload(job.id, stem)}
                          className="stem-button-small"
                        >
                          {stem}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>

      <footer className="App-footer">
        <p>Powered by Demucs | Backend: Go | Frontend: React</p>
      </footer>
    </div>
  );
}

export default App;
