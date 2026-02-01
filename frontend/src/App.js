import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';
import Spectrogram from './Spectrogram';

// LocalStorage keys
const STORAGE_KEYS = {
  JOBS: 'track2stem_jobs',
  CURRENT_JOB: 'track2stem_current_job',
  START_TIME: 'track2stem_start_time',
  PROCESSING_PROGRESS: 'track2stem_progress',
  INPUT_FILE_NAME: 'track2stem_input_filename',
};

function App() {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentJob, setCurrentJob] = useState(null);
  const [processingProgress, setProcessingProgress] = useState({ progress: 0, stage: '' });
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState('');
  const [stemMode, setStemMode] = useState('all'); // 'all' or 'isolate'
  const [isolateStem, setIsolateStem] = useState('vocals'); // which stem to isolate
  const [elapsedTime, setElapsedTime] = useState(0); // elapsed seconds
  const [inputFileName, setInputFileName] = useState(''); // Keep track of input file name for display
  const [isInitialized, setIsInitialized] = useState(false); // Track if localStorage has been loaded
  const startTimeRef = useRef(null);
  const timerRef = useRef(null);

  const API_BASE = process.env.REACT_APP_API_URL || '/api';

  // Format elapsed time as Xm Ys
  const formatElapsedTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  };

  // Load persisted state from localStorage
  useEffect(() => {
    // Load jobs from localStorage
    const savedJobs = localStorage.getItem(STORAGE_KEYS.JOBS);
    if (savedJobs) {
      try {
        setJobs(JSON.parse(savedJobs));
      } catch (e) {
        console.error('Failed to parse saved jobs:', e);
      }
    }
    
    // Load current job from localStorage
    const savedCurrentJob = localStorage.getItem(STORAGE_KEYS.CURRENT_JOB);
    if (savedCurrentJob) {
      try {
        const parsedJob = JSON.parse(savedCurrentJob);
        setCurrentJob(parsedJob);
      } catch (e) {
        console.error('Failed to parse saved current job:', e);
      }
    }
    
    // Load start time for timer recovery
    const savedStartTime = localStorage.getItem(STORAGE_KEYS.START_TIME);
    if (savedStartTime) {
      startTimeRef.current = parseInt(savedStartTime, 10);
    }
    
    // Load processing progress
    const savedProgress = localStorage.getItem(STORAGE_KEYS.PROCESSING_PROGRESS);
    if (savedProgress) {
      try {
        setProcessingProgress(JSON.parse(savedProgress));
      } catch (e) {
        console.error('Failed to parse saved progress:', e);
      }
    }
    
    // Load input file name
    const savedInputFileName = localStorage.getItem(STORAGE_KEYS.INPUT_FILE_NAME);
    if (savedInputFileName) {
      setInputFileName(savedInputFileName);
    }
    
    // Mark as initialized after loading
    setIsInitialized(true);
  }, []);

  // Save jobs to localStorage whenever they change
  useEffect(() => {
    if (jobs.length > 0) {
      localStorage.setItem(STORAGE_KEYS.JOBS, JSON.stringify(jobs));
    }
  }, [jobs]);

  // Save current job to localStorage whenever it changes
  useEffect(() => {
    if (currentJob) {
      localStorage.setItem(STORAGE_KEYS.CURRENT_JOB, JSON.stringify(currentJob));
    }
  }, [currentJob]);

  // Fetch jobs on mount and merge with localStorage
  useEffect(() => {
    fetchJobs();
  }, []);

  // Stopwatch effect - runs every second when processing
  useEffect(() => {
    if (currentJob && (currentJob.status === 'pending' || currentJob.status === 'processing')) {
      // Start the timer if not already started
      if (!startTimeRef.current) {
        startTimeRef.current = Date.now();
        localStorage.setItem(STORAGE_KEYS.START_TIME, startTimeRef.current.toString());
      }
      
      // Calculate initial elapsed time (for page refresh recovery)
      const initialElapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
      setElapsedTime(initialElapsed);
      
      // Update elapsed time every second
      timerRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
        setElapsedTime(elapsed);
      }, 1000);
      
      return () => {
        if (timerRef.current) {
          clearInterval(timerRef.current);
        }
      };
    } else {
      // Job finished or no job - reset timer refs but keep last elapsed time
      if (currentJob?.status === 'completed' || currentJob?.status === 'failed') {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
        localStorage.removeItem(STORAGE_KEYS.START_TIME);
      }
      // Only reset if initialized and explicitly no job (user cleared it)
      // Don't reset on initial load before localStorage is read
    }
  }, [currentJob]);

  useEffect(() => {
    if (currentJob && (currentJob.status === 'pending' || currentJob.status === 'processing')) {
      const interval = setInterval(() => {
        fetchJobStatus(currentJob.id);
        fetchProcessingProgress(currentJob.id);
      }, 2000);
      return () => clearInterval(interval);
    }
    // Don't reset progress here - it causes the 90% issue
  }, [currentJob]);

  const fetchJobs = async () => {
    try {
      const response = await axios.get(`${API_BASE}/jobs`);
      const serverJobs = response.data || [];
      
      // Merge server jobs with localStorage jobs (localStorage takes precedence for completed jobs)
      const savedJobsStr = localStorage.getItem(STORAGE_KEYS.JOBS);
      const savedJobs = savedJobsStr ? JSON.parse(savedJobsStr) : [];
      
      // Create a map of all jobs
      const jobsMap = new Map();
      
      // Add saved jobs first
      savedJobs.forEach(job => {
        jobsMap.set(job.id, job);
      });
      
      // Update with server jobs (server has latest status)
      serverJobs.forEach(job => {
        const existing = jobsMap.get(job.id);
        if (!existing || job.status === 'completed' || job.status === 'failed') {
          jobsMap.set(job.id, job);
        }
      });
      
      const mergedJobs = Array.from(jobsMap.values());
      setJobs(mergedJobs);
      
    } catch (err) {
      console.error('Failed to fetch jobs:', err);
    }
  };

  const fetchJobStatus = async (jobId) => {
    try {
      const response = await axios.get(`${API_BASE}/jobs/${jobId}`);
      const updatedJob = response.data;
      setCurrentJob(updatedJob);
      
      if (updatedJob.status === 'completed' || updatedJob.status === 'failed') {
        // Update the job in our jobs list with processing time
        setJobs(prevJobs => {
          const updatedJobs = prevJobs.filter(j => j.id !== updatedJob.id);
          updatedJobs.push(updatedJob);
          return updatedJobs;
        });
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
        // Persist progress to localStorage
        localStorage.setItem(STORAGE_KEYS.PROCESSING_PROGRESS, JSON.stringify(response.data));
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
    formData.append('stem_mode', stemMode);
    formData.append('isolate_stem', isolateStem);

    setUploading(true);
    setUploadProgress(0);
    setError('');
    
    // Save input file name for display during processing
    setInputFileName(file.name);
    localStorage.setItem(STORAGE_KEYS.INPUT_FILE_NAME, file.name);
    
    // Reset timer for new job
    startTimeRef.current = Date.now();
    localStorage.setItem(STORAGE_KEYS.START_TIME, startTimeRef.current.toString());
    setElapsedTime(0);
    
    // Reset progress for new job
    setProcessingProgress({ progress: 0, stage: 'Starting...' });
    localStorage.setItem(STORAGE_KEYS.PROCESSING_PROGRESS, JSON.stringify({ progress: 0, stage: 'Starting...' }));

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

  const handleDeleteJob = async (jobId) => {
    // Find the job to check if it's in progress
    const jobToDelete = jobs.find(j => j.id === jobId) || (currentJob?.id === jobId ? currentJob : null);
    
    // If job is in progress, try to cancel it on the server
    if (jobToDelete && (jobToDelete.status === 'pending' || jobToDelete.status === 'processing')) {
      try {
        await axios.delete(`${API_BASE}/jobs/${jobId}`);
      } catch (err) {
        console.warn('Could not cancel job on server:', err);
      }
    }
    
    // Remove from state
    setJobs(prevJobs => prevJobs.filter(j => j.id !== jobId));
    
    // Update localStorage
    const savedJobs = localStorage.getItem(STORAGE_KEYS.JOBS);
    if (savedJobs) {
      const parsed = JSON.parse(savedJobs);
      const filtered = parsed.filter(j => j.id !== jobId);
      localStorage.setItem(STORAGE_KEYS.JOBS, JSON.stringify(filtered));
    }
    
    // If it's the current job, clear it and all related state
    if (currentJob && currentJob.id === jobId) {
      setCurrentJob(null);
      setProcessingProgress({ progress: 0, stage: '' });
      setInputFileName('');
      localStorage.removeItem(STORAGE_KEYS.CURRENT_JOB);
      localStorage.removeItem(STORAGE_KEYS.PROCESSING_PROGRESS);
      localStorage.removeItem(STORAGE_KEYS.INPUT_FILE_NAME);
      localStorage.removeItem(STORAGE_KEYS.START_TIME);
      startTimeRef.current = null;
      setElapsedTime(0);
    }
  };

  const handleClearCurrentJob = () => {
    setCurrentJob(null);
    setProcessingProgress({ progress: 0, stage: '' });
    setInputFileName('');
    localStorage.removeItem(STORAGE_KEYS.CURRENT_JOB);
    localStorage.removeItem(STORAGE_KEYS.START_TIME);
    localStorage.removeItem(STORAGE_KEYS.PROCESSING_PROGRESS);
    localStorage.removeItem(STORAGE_KEYS.INPUT_FILE_NAME);
    startTimeRef.current = null;
    setElapsedTime(0);
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  const getDownloadUrl = (jobId, stem) => {
    return `${API_BASE}/download/${jobId}/${stem}`;
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
            
            {/* Waveform for input file - show when file is selected */}
            {file && (
              <div className="input-spectrogram">
                <Spectrogram audioFile={file} title="📊 Input Audio Waveform" height={80} />
              </div>
            )}
            
            {/* Stem Mode Options */}
            <div className="stem-options">
              <h3>Output Mode</h3>
              <div className="stem-mode-selector">
                <label className={`mode-option ${stemMode === 'all' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="stemMode"
                    value="all"
                    checked={stemMode === 'all'}
                    onChange={(e) => setStemMode(e.target.value)}
                    disabled={uploading}
                  />
                  <span className="mode-label">🎼 All 6 Stems</span>
                  <span className="mode-desc">Vocals, Drums, Bass, Guitar, Piano, Other</span>
                </label>
                <label className={`mode-option ${stemMode === 'isolate' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="stemMode"
                    value="isolate"
                    checked={stemMode === 'isolate'}
                    onChange={(e) => setStemMode(e.target.value)}
                    disabled={uploading}
                  />
                  <span className="mode-label">🎤 Isolate One</span>
                  <span className="mode-desc">Get one stem + everything else (great for covers)</span>
                </label>
              </div>
              
              {stemMode === 'isolate' && (
                <div className="isolate-selector">
                  <label>Choose stem to isolate:</label>
                  <select 
                    value={isolateStem} 
                    onChange={(e) => setIsolateStem(e.target.value)}
                    disabled={uploading}
                  >
                    <option value="vocals">🎤 Vocals</option>
                    <option value="drums">🥁 Drums</option>
                    <option value="bass">🎸 Bass</option>
                    <option value="guitar">🎸 Guitar</option>
                    <option value="piano">🎹 Piano</option>
                  </select>
                </div>
              )}
            </div>
            
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
            <div className="section-header">
              <h2>Current Job</h2>
              {(currentJob.status === 'completed' || currentJob.status === 'failed') && (
                <button className="clear-button" onClick={handleClearCurrentJob}>
                  ✕ Clear
                </button>
              )}
            </div>
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
                  <p className="elapsed-time">⏱️ Elapsed: {formatElapsedTime(elapsedTime)}</p>
                  <p className="processing-note">🎧 AI is separating your audio stems. This may take 5-15 minutes depending on file size.</p>
                </div>
              )}

              {currentJob.status === 'completed' && currentJob.output_files && (
                <div className="stems">
                  <p className="total-time">✅ Processed in {currentJob.processing_time || formatElapsedTime(elapsedTime)}</p>
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
                  
                  {/* Spectrograms for output stems */}
                  <div className="output-spectrograms">
                    <h3>📊 Output Spectrograms:</h3>
                    <div className="spectrograms-grid">
                      {Object.keys(currentJob.output_files).map((stem) => (
                        <Spectrogram 
                          key={stem}
                          audioUrl={getDownloadUrl(currentJob.id, stem)}
                          title={stem.charAt(0).toUpperCase() + stem.slice(1)}
                          height={60}
                        />
                      ))}
                    </div>
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
                    <div className="job-header-right">
                      {job.processing_time && (
                        <span className="job-time">⏱️ {job.processing_time}</span>
                      )}
                      <span className={`job-status status-${job.status}`}>
                        {job.status}
                      </span>
                      <button 
                        className="delete-job-button" 
                        onClick={() => handleDeleteJob(job.id)}
                        title="Delete job"
                      >
                        🗑️
                      </button>
                    </div>
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
