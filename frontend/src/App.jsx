import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import './App.css';
import Spectrogram from './Spectrogram.jsx';
import StemMixer from './StemMixer.jsx';
import PracticeResults from './PracticeResults.jsx';

const STORAGE_KEYS = {
  JOBS: 'track2stem_jobs',
  CURRENT_JOB: 'track2stem_current_job',
  START_TIME: 'track2stem_start_time',
  PROCESSING_PROGRESS: 'track2stem_progress',
  INPUT_FILE_NAME: 'track2stem_input_filename',
};

const SIX_STEM_MODELS = ['htdemucs_6s'];
const SIX_STEMS = ['vocals', 'drums', 'bass', 'guitar', 'piano', 'other'];
const FOUR_STEMS = ['vocals', 'drums', 'bass', 'other'];
const ICON_PATHS = {
  upload: 'M12 16V4m-5 5 5-5 5 5M4 16v4h16v-4',
  file: 'M14 3H5v18h14V8l-5-5Zm0 0v5h5M8 13h8m-8 4h5',
  settings: 'M4 7h7m4 0h5M4 17h3m4 0h9M11 4v6M7 14v6',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  download: 'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',
  chevron: 'm6 9 6 6 6-6',
  close: 'm6 6 12 12M6 18 18 6',
  trash: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  clock: 'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
  check: 'm5 12 4 4L19 6',
  split: 'M4 12h6m0 0 5-6h5m-10 6 5 6h5M17 3l3 3-3 3m0 6 3 3-3 3',
};

function Icon({ name, className = '' }) {
  return (
    <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true" focusable="false">
      <path d="M7 13v6m6-12v18m6-15v12m6-8v4" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
}

const stemLabel = (stem) => (stem.charAt(0).toUpperCase() + stem.slice(1)).replaceAll('_', ' ');
const PRACTICE_TOOLS = [
  ['analysis', 'Tempo, key & song sections'], ['click_track', 'Click track'], ['lyrics', 'Lyrics'],
  ['guitar_tabs', 'Guitar tabs'], ['bass_tabs', 'Bass tabs'], ['drum_tabs', 'Drum tabs & MIDI'],
  ['split_vocals', 'Lead / backing vocals'],
];

function App() {
  const localStorage = window.track2stemHost?.storage || window.localStorage;
  const nativeHost = Boolean(window.track2stemHost);
  const [file, setFile] = useState(null);
  const [sourceType, setSourceType] = useState('file');
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentJob, setCurrentJob] = useState(null);
  const [processingProgress, setProcessingProgress] = useState({ progress: 0, stage: '' });
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState('');
  const [stemMode, setStemMode] = useState('all'); // 'all' or 'isolate'
  const [isolateStem, setIsolateStem] = useState('vocals'); // which stem to isolate
  const [elapsedTime, setElapsedTime] = useState(0); // elapsed seconds
  const [isInitialized, setIsInitialized] = useState(false); // Track if localStorage has been loaded
  const [showAdvanced, setShowAdvanced] = useState(false); // Toggle advanced options
  const [jobsLoading, setJobsLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const [statusWarning, setStatusWarning] = useState('');
  const [progressWarning, setProgressWarning] = useState('');
  const [modelNotice, setModelNotice] = useState('');

  // Advanced options
  const [outputFormat, setOutputFormat] = useState('mp3');
  const [model, setModel] = useState('htdemucs_6s');
  const [segment, setSegment] = useState('');
  const [overlap, setOverlap] = useState('0.25');
  const [shifts, setShifts] = useState('0');
  const [clipMode, setClipMode] = useState('rescale');
  const [workers, setWorkers] = useState('1');
  const [tools, setTools] = useState(Object.fromEntries(PRACTICE_TOOLS.map(([name]) => [name, false])));

  const startTimeRef = useRef(null);
  const timerRef = useRef(null);
  const fileInputRef = useRef(null);
  const historyHeadingRef = useRef(null);

  const API_BASE = window.track2stemHost?.apiBase || import.meta.env.VITE_API_URL || '/api';

  const isSixStemModel = SIX_STEM_MODELS.includes(model);
  const availableStems = isSixStemModel ? SIX_STEMS : FOUR_STEMS;
  const expectedStems = stemMode === 'all'
    ? (tools.split_vocals ? ['lead_vocals', 'backing_vocals', ...availableStems.slice(1)] : availableStems)
    : [...(tools.split_vocals && isolateStem === 'vocals' ? ['lead_vocals', 'backing_vocals'] : [isolateStem]),
      isolateStem === 'vocals' ? 'instrumental' : 'backing'];
  const currentProgress = Number.isFinite(processingProgress.progress)
    ? Math.max(0, Math.min(100, processingProgress.progress))
    : null;

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

  // Fetch jobs on mount and merge with localStorage (only after localStorage is loaded)
  useEffect(() => {
    const doFetchJobs = async () => {
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
        setHistoryError('Could not refresh recent jobs. Saved history is still shown; check the server connection and refresh.');
      } finally {
        setJobsLoading(false);
      }
    };

    if (isInitialized) {
      doFetchJobs();
    }
  }, [isInitialized, API_BASE]);

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

  // Fetch job status and progress polling
  const fetchJobStatus = useCallback(async (jobId) => {
    try {
      const response = await axios.get(`${API_BASE}/jobs/${jobId}`);
      const updatedJob = response.data;
      setCurrentJob(updatedJob);
      setStatusWarning('');
      
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
      if (err.response?.status === 404) {
        setCurrentJob((previous) => previous?.id === jobId ? {
          ...previous, status: 'failed',
          error: 'This job is no longer available. The server or local worker may have restarted. Import the source again.',
        } : previous);
      } else {
        setStatusWarning('Could not refresh this job. Retrying automatically; check the server connection.');
      }
    }
  }, [API_BASE]);

  const fetchProcessingProgress = useCallback(async (jobId) => {
    try {
      const response = await axios.get(`${API_BASE}/processing-status/${jobId}`);
      if (response.data) {
        setProcessingProgress(response.data);
        setProgressWarning('');
        // Persist progress to localStorage
        localStorage.setItem(STORAGE_KEYS.PROCESSING_PROGRESS, JSON.stringify(response.data));
      }
    } catch (err) {
      console.warn('Failed to fetch processing progress:', err);
      setProgressWarning('Live progress is unavailable. Job status will continue to update.');
    }
  }, [API_BASE]);

  useEffect(() => {
    if (currentJob && (currentJob.status === 'pending' || currentJob.status === 'processing')) {
      const interval = setInterval(() => {
        fetchJobStatus(currentJob.id);
        fetchProcessingProgress(currentJob.id);
      }, 2000);
      return () => clearInterval(interval);
    }
    // Don't reset progress here - it causes the 90% issue
  }, [currentJob, fetchJobStatus, fetchProcessingProgress]);

  const handleFileChange = (e) => {
    const selectedFile = e.target.files[0];
    if (selectedFile) {
      const validTypes = ['audio/mpeg', 'audio/wav', 'audio/flac', 'audio/ogg', 'audio/m4a', 'audio/aac'];
      const validExtensions = ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'];
      const extension = selectedFile.name.split('.').pop().toLowerCase();
      
      if (!validTypes.includes(selectedFile.type) && !validExtensions.includes(extension)) {
        setError('Please select a valid audio file (mp3, wav, flac, ogg, m4a, aac)');
        setFile(null);
        return;
      }

      const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB
      if (selectedFile.size > MAX_FILE_SIZE) {
        const sizeMB = (selectedFile.size / (1024 * 1024)).toFixed(1);
        setError(`File is too large (${sizeMB} MB). Maximum allowed size is 100 MB.`);
        setFile(null);
        return;
      }

      setFile(selectedFile);
      setError('');
    }
  };

  const handleModelChange = (event) => {
    const nextModel = event.target.value;
    setModel(nextModel);
    setModelNotice('');
    if (!SIX_STEM_MODELS.includes(nextModel) && ['guitar', 'piano'].includes(isolateStem)) {
      setIsolateStem('vocals');
      setModelNotice('Isolation changed to vocals. Guitar and piano require the six-stem model.');
    }
    if (!SIX_STEM_MODELS.includes(nextModel) && tools.guitar_tabs) {
      setTools((previous) => ({ ...previous, guitar_tabs: false }));
      setModelNotice('Guitar tabs disabled. Guitar transcription requires the six-stem model.');
    }
  };

  const handleUpload = async (event) => {
    event.preventDefault();
    if (sourceType === 'file' ? !file : !youtubeUrl.trim()) {
      setError(sourceType === 'file' ? 'Please select a file' : 'Please enter a YouTube video URL');
      return;
    }

    const formData = new FormData();
    if (sourceType === 'file') formData.append('file', file);
    formData.append('stem_mode', stemMode);
    formData.append('isolate_stem', isolateStem);
    formData.append('output_format', outputFormat);
    formData.append('model', model);
    formData.append('shifts', shifts);
    formData.append('clip_mode', clipMode);
    if (segment) {
      formData.append('segment', segment);
    }
    if (overlap) {
      formData.append('overlap', overlap);
    }
    formData.append('workers', workers);
    for (const [name, enabled] of Object.entries(tools)) {
      if (enabled) formData.append(name, 'true');
    }

    setUploading(true);
    setUploadProgress(0);
    setError('');
    setStatusWarning('');
    setProgressWarning('');
    
    // Save input file name to localStorage
    localStorage.setItem(STORAGE_KEYS.INPUT_FILE_NAME, sourceType === 'file' ? file.name : 'YouTube audio');
    
    // Reset timer for new job
    startTimeRef.current = Date.now();
    localStorage.setItem(STORAGE_KEYS.START_TIME, startTimeRef.current.toString());
    setElapsedTime(0);
    
    // Reset progress for new job
    setProcessingProgress({ progress: 0, stage: 'Starting...' });
    localStorage.setItem(STORAGE_KEYS.PROCESSING_PROGRESS, JSON.stringify({ progress: 0, stage: 'Starting...' }));

    try {
      const response = sourceType === 'youtube'
        ? await axios.post(`${API_BASE}/import`, {
          url: youtubeUrl.trim(),
          settings: Object.fromEntries([...formData.entries()].filter(([name]) => name !== 'file')),
        })
        : await axios.post(`${API_BASE}/upload`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = progressEvent.total
            ? Math.round((progressEvent.loaded * 100) / progressEvent.total)
            : null;
          setUploadProgress(percentCompleted);
        },
        });
      
      setCurrentJob(response.data);
      setFile(null);
      // Reset file input
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err) {
      const status = err.response?.status;
      const data = err.response?.data;
      let message;

      if (status === 413) {
        message = 'File is too large. Maximum allowed size is 100 MB.';
      } else if (typeof data === 'string' && data.includes('<html')) {
        message = 'The server rejected the request. The file may be too large (max 100 MB).';
      } else {
        message = typeof data === 'string' ? data : data?.error || err.message || 'The request could not be completed.';
      }

      setError((sourceType === 'youtube' ? 'Import failed: ' : 'Upload failed: ') + message);
    } finally {
      setUploading(false);
    }
  };

  const handleDownload = (jobId, stem) => {
    window.open(getDownloadUrl(jobId, stem), '_blank');
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
      localStorage.removeItem(STORAGE_KEYS.CURRENT_JOB);
      localStorage.removeItem(STORAGE_KEYS.PROCESSING_PROGRESS);
      localStorage.removeItem(STORAGE_KEYS.INPUT_FILE_NAME);
      localStorage.removeItem(STORAGE_KEYS.START_TIME);
      startTimeRef.current = null;
      setElapsedTime(0);
    }
    historyHeadingRef.current?.focus();
  };

  const handleClearCurrentJob = () => {
    setCurrentJob(null);
    setProcessingProgress({ progress: 0, stage: '' });
    localStorage.removeItem(STORAGE_KEYS.CURRENT_JOB);
    localStorage.removeItem(STORAGE_KEYS.START_TIME);
    localStorage.removeItem(STORAGE_KEYS.PROCESSING_PROGRESS);
    localStorage.removeItem(STORAGE_KEYS.INPUT_FILE_NAME);
    startTimeRef.current = null;
    setElapsedTime(0);
    setStatusWarning('');
    setProgressWarning('');
    fileInputRef.current?.focus();
  };

  const formatDate = (dateString) => {
    return new Date(dateString).toLocaleString();
  };

  const getDownloadUrl = (jobId, stem) => {
    return `${API_BASE}/download/${jobId}/${stem}`;
  };

  const updateMixedJob = (job) => {
    setCurrentJob(job);
    setJobs((previous) => [...previous.filter((entry) => entry.id !== job.id), job]);
  };

  return (
    <div className="App">
      <a className="skip-link" href="#main-content">Skip to workspace</a>
      <header className="App-header">
        <div className="header-inner">
          <a className="brand" href="#main-content" aria-label="Track2stem workspace">
            <BrandMark />
            <span>Track2stem</span>
          </a>
          <div className="header-links">
            <span className="host-label">{nativeHost ? 'Local DAW workspace' : 'Self-hosted audio separation'}</span>
            <a href="https://github.com/mbianchidev/track2stem/blob/main/docs/usage.md" target="_blank" rel="noreferrer">
              Usage guide <Icon name="arrow" />
            </a>
          </div>
        </div>
      </header>

      <main className="App-main" id="main-content" tabIndex={-1}>
        <div className="workspace-heading">
          <div>
            <h1>Separate audio <span>into stems</span></h1>
            <p className="workspace-description">Extract vocals, drums, bass, and other instruments.</p>
          </div>
          <a className="history-link" href="#recent-jobs">Recent jobs <Icon name="arrow" /></a>
        </div>

        <div className="workspace-grid">
          <section className="panel source-panel" aria-labelledby="source-heading">
            <div className="panel-header">
              <h2 id="source-heading"><Icon name="file" /> Source audio</h2>
              <span className="panel-label">Input</span>
            </div>
            <fieldset className="source-type" disabled={uploading}>
              <legend className="sr-only">Source type</legend>
              <label><input type="radio" name="sourceType" checked={sourceType === 'file'} onChange={() => { setSourceType('file'); setError(''); }} /> Audio file</label>
              <label><input type="radio" name="sourceType" checked={sourceType === 'youtube'} onChange={() => { setSourceType('youtube'); setError(''); }} /> YouTube link</label>
            </fieldset>
            {sourceType === 'youtube' ? (
              <div className="youtube-source">
                <label className="setting-label" htmlFor="youtube-url">YouTube video URL</label>
                <input id="youtube-url" form="separation-form" type="url" required value={youtubeUrl}
                  placeholder="https://www.youtube.com/watch?v=..."
                  onChange={(event) => setYoutubeUrl(event.target.value)} disabled={uploading} />
                <p className="setting-help">Single videos up to 60 minutes and 100 MiB. Import only audio you have permission to use. Restricted videos may require a local file instead.</p>
              </div>
            ) : <><div className={`source-picker ${file ? 'has-file' : ''}`}>
              <input
                ref={fileInputRef}
                id="file-input"
                className="file-input"
                type="file"
                aria-label="Choose audio file"
                aria-describedby={`source-help${error ? ' source-error' : ''}`}
                aria-invalid={Boolean(error) && !file}
                accept=".mp3,.wav,.flac,.ogg,.m4a,.aac,audio/*"
                onChange={handleFileChange}
                disabled={uploading}
              />
              <div className="source-symbol" aria-hidden="true">
                <Icon name={file ? 'file' : 'upload'} />
              </div>
              <div className="source-picker-copy">
                <h3 title={file?.name}>{file ? file.name : 'No audio selected'}</h3>
                {file && <p>{(file.size / (1024 * 1024)).toFixed(2)} MB</p>}
              </div>
              <span className="choose-file-button" aria-hidden="true">
                Choose audio file <Icon name="arrow" />
              </span>
            </div>
            <p className="file-help" id="source-help">
              <span>MP3, WAV, FLAC, OGG, M4A, AAC</span>
              <span>Up to 100 MB</span>
            </p>
            {file && (
              <div className="source-waveform">
                <Spectrogram audioFile={file} title="Source waveform" height={88} />
              </div>
            )}</>}
            {uploading && (
              <div className="upload-progress">
                <div className="progress-caption">
                  <span>Uploading audio</span>
                  <span>{uploadProgress === null ? 'Sending...' : `${uploadProgress}%`}</span>
                </div>
                <progress aria-label="Upload progress" max="100" value={uploadProgress ?? undefined} />
              </div>
            )}
            {error && <p className="error source-error" role="alert" id="source-error">{error}</p>}
          </section>

          <form id="separation-form" className="panel settings-panel" aria-labelledby="settings-heading" onSubmit={handleUpload} aria-busy={uploading}>
            <div className="panel-header">
              <h2 id="settings-heading"><Icon name="settings" /> Separation settings</h2>
            </div>
            <div className="settings-body">
              <fieldset className="settings-fieldset" disabled={uploading}>
                <legend className="setting-label">Output mode</legend>
                <label className={`mode-option ${stemMode === 'all' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="stemMode"
                    value="all"
                    checked={stemMode === 'all'}
                    onChange={(e) => setStemMode(e.target.value)}
                  />
                  <span className="mode-copy">
                    <span className="mode-label">All {availableStems.length} stems</span>
                    <span className="mode-desc">{availableStems.map(stemLabel).join(', ')}</span>
                  </span>
                </label>
                <label className={`mode-option ${stemMode === 'isolate' ? 'selected' : ''}`}>
                  <input
                    type="radio"
                    name="stemMode"
                    value="isolate"
                    checked={stemMode === 'isolate'}
                    onChange={(e) => setStemMode(e.target.value)}
                  />
                  <span className="mode-copy">
                    <span className="mode-label">Isolate one</span>
                    <span className="mode-desc">One stem plus a backing track</span>
                  </span>
                </label>
                {stemMode === 'isolate' && (
                  <div className="isolate-selector setting-group">
                    <label className="setting-label" htmlFor="isolate-select">Choose stem to isolate</label>
                    <select id="isolate-select" value={isolateStem} onChange={(e) => {
                      setIsolateStem(e.target.value);
                      setModelNotice('');
                    }}>
                      {availableStems.filter((stem) => stem !== 'other').map((stem) => (
                        <option key={stem} value={stem}>{stemLabel(stem)}</option>
                      ))}
                    </select>
                  </div>
                )}
              </fieldset>

              <div className="setting-group">
                <label className="setting-label" htmlFor="model-select">AI model</label>
                <select id="model-select" value={model} onChange={handleModelChange} disabled={uploading}>
                  <option value="htdemucs_6s">htdemucs_6s / 6 stems</option>
                  <option value="htdemucs">htdemucs / Hybrid Transformer</option>
                  <option value="htdemucs_ft">htdemucs_ft / Fine-tuned, slower</option>
                  <option value="hdemucs_mmi">hdemucs_mmi / Hybrid v3</option>
                  <option value="mdx">mdx</option>
                  <option value="mdx_extra">mdx_extra / Extra training data</option>
                  <option value="mdx_q">mdx_q / Quantized, smaller</option>
                  <option value="mdx_extra_q">mdx_extra_q / Extra, quantized</option>
                </select>
                {modelNotice
                  ? <p className="setting-help model-notice" role="status">{modelNotice}</p>
                  : <p className="setting-help">{isSixStemModel ? 'Includes separate guitar and piano tracks.' : 'Vocals, drums, bass, and other instruments.'}</p>}
              </div>
              <div className="setting-group">
                <label className="setting-label" htmlFor="profile-select">CPU profile</label>
                <select id="profile-select" defaultValue="custom" disabled={uploading} onChange={(event) => {
                  if (event.target.value === 'fast') {
                    handleModelChange({ target: { value: 'htdemucs' } });
                    setOverlap('0.1');
                    setShifts('0');
                    setSegment('');
                    setModelNotice('Fast profile: four instruments, no shift passes, and less overlap. Use six-stem defaults for separate guitar and piano.');
                  } else if (event.target.value === 'six') {
                    setModel('htdemucs_6s');
                    setOverlap('0.25');
                    setShifts('0');
                    setSegment('');
                    setModelNotice('');
                  }
                }}>
                  <option value="custom">Custom settings</option>
                  <option value="six">Six-stem defaults</option>
                  <option value="fast">Fast / four stems</option>
                </select>
              </div>

              <fieldset className="settings-fieldset" disabled={uploading}>
                <legend className="setting-label">Output format</legend>
                <div className="format-radio-group">
                  {['mp3', 'wav', 'flac'].map((fmt) => (
                    <label key={fmt} className={`format-choice ${outputFormat === fmt ? 'active' : ''}`}>
                      <input type="radio" name="outputFormat" value={fmt} checked={outputFormat === fmt}
                        onChange={(e) => setOutputFormat(e.target.value)} />
                      {fmt.toUpperCase()}
                    </label>
                  ))}
                </div>
                <p className="setting-help">
                  {outputFormat === 'mp3' ? '320 kbps' : outputFormat === 'wav' ? 'Uncompressed audio' : 'Lossless compression'}
                </p>
              </fieldset>
              <fieldset className="settings-fieldset practice-options" disabled={uploading}>
                <legend className="setting-label">Practice tools</legend>
                {PRACTICE_TOOLS.map(([name, text]) => (
                  <label key={name}>
                    <input type="checkbox" checked={tools[name]} disabled={uploading || (name === 'guitar_tabs' && !isSixStemModel)}
                      onChange={(event) => setTools((previous) => ({ ...previous, [name]: event.target.checked }))} />
                    {text}
                  </label>
                ))}
                <p className="setting-help">Optional local processing. Lyrics, tabs and vocal splitting download extra models on first use. Automatic transcriptions need review.</p>
              </fieldset>

              <div className="advanced-section">
                <button type="button" className="advanced-toggle" aria-expanded={showAdvanced}
                  aria-controls="advanced-options" onClick={() => setShowAdvanced((value) => !value)}>
                  {showAdvanced ? 'Hide advanced' : 'Advanced tuning'}
                  <Icon name="chevron" className={showAdvanced ? 'is-expanded' : ''} />
                </button>
                <div id="advanced-options" hidden={!showAdvanced}>
                  {showAdvanced && (
                    <div className="advanced-options-panel">
                      <div className="setting-group">
                        <label className="setting-label" htmlFor="workers-select">Parallel CPU workers</label>
                        <select id="workers-select" value={workers} onChange={(event) => setWorkers(event.target.value)} disabled={uploading}>
                          {[1, 2, 3, 4].map((count) => <option key={count} value={count}>{count}{count === 1 ? ' / low memory' : ' / more memory'}</option>)}
                        </select>
                        <p className="setting-help">Workers share one model and crossfade overlapping segments. Start with one on memory-limited hosts.</p>
                      </div>
                      <div className="setting-group">
                        <label className="setting-label" htmlFor="segment-select">Segment size</label>
                        <select id="segment-select" value={segment} onChange={(e) => setSegment(e.target.value)} disabled={uploading}>
                          <option value="">Default</option>
                          <option value="5">5 s (low memory)</option>
                          <option value="7">7 s</option>
                          {!model.startsWith('htdemucs') && <option value="8">8 s</option>}
                          {!model.startsWith('htdemucs') && <>
                          <option value="10">10 s</option>
                          <option value="15">15 s</option>
                          <option value="20">20 s</option>
                          <option value="25">25 s</option>
                          <option value="30">30 s</option>
                          <option value="40">40 s</option>
                          <option value="60">60 s (high memory)</option>
                          </>}
                        </select>
                      </div>

                      <div className="setting-group">
                        <label className="setting-label" htmlFor="overlap-select">Overlap</label>
                        <select id="overlap-select" value={overlap} onChange={(e) => setOverlap(e.target.value)} disabled={uploading}>
                          <option value="">Default</option>
                          <option value="0.1">0.10 (fastest)</option>
                          <option value="0.15">0.15</option>
                          <option value="0.2">0.20</option>
                          <option value="0.25">0.25 (recommended)</option>
                          <option value="0.3">0.30</option>
                          <option value="0.35">0.35</option>
                          <option value="0.4">0.40</option>
                          <option value="0.5">0.50 (best quality)</option>
                        </select>
                      </div>

                      <div className="setting-group">
                        <label className="setting-label" htmlFor="shifts-select">Shifts (quality)</label>
                        <select id="shifts-select" value={shifts} onChange={(e) => setShifts(e.target.value)} disabled={uploading}>
                          <option value="0">0 / Default</option>
                          <option value="1">1</option>
                          <option value="2">2</option>
                          <option value="5">5</option>
                          <option value="10">10</option>
                        </select>
                      </div>

                      <div className="setting-group">
                        <label className="setting-label" htmlFor="clip-mode-select">Clip mode</label>
                        <select id="clip-mode-select" value={clipMode} onChange={(e) => setClipMode(e.target.value)} disabled={uploading}>
                          <option value="rescale">Rescale</option>
                          <option value="clamp">Clamp (hard clip)</option>
                        </select>
                      </div>
                      <p className="setting-help advanced-help">More overlap and shifts can improve quality but take longer. Rescale preserves relative volume.</p>
                    </div>
                  )}
                </div>
              </div>

              <div className="settings-action">
                <button type="submit" disabled={(sourceType === 'file' ? !file : !youtubeUrl.trim()) || uploading} className="upload-button">
                  {uploading ? `Uploading...${uploadProgress === null ? '' : ` ${uploadProgress}%`}` : sourceType === 'youtube' ? 'Import & Process' : 'Upload & Process'}
                  <Icon name="arrow" />
                </button>
                <p className="setting-footnote">{nativeHost ? 'Processing stays on this Mac.' : "Processing runs on your server's CPU."}</p>
              </div>
            </div>
          </form>

          <section className="panel results-panel" aria-labelledby="results-heading">
            <div className="panel-header">
              <h2 id="results-heading"><Icon name="split" /> Separated stems</h2>
              {currentJob && ['completed', 'failed'].includes(currentJob.status)
                ? <button type="button" className="quiet-button" onClick={handleClearCurrentJob} aria-label="Clear current job">
                  <Icon name="close" /> Clear
                </button>
                : <span className="panel-label">{currentJob ? 'Current job' : 'Output'}</span>}
            </div>
            <p className="sr-only" role="status" aria-atomic="true">
              {currentJob?.status === 'completed' ? 'Separation completed. Stems are ready to download.'
                : currentJob?.status === 'failed' ? 'Separation failed.'
                  : currentJob ? processingProgress.stage || 'Waiting for separation.' : ''}
            </p>
            {!currentJob ? (
              <div className="results-empty">
                <svg className="routing-diagram" viewBox="0 0 180 72" fill="none" aria-hidden="true">
                  <path d="M8 36h48m0 0c22 0 22-24 44-24h52M56 36h96M56 36c22 0 22 24 44 24h52" />
                  <rect x="4" y="28" width="8" height="16" rx="2" />
                  <rect x="152" y="6" width="20" height="12" rx="2" />
                  <rect x="152" y="30" width="20" height="12" rx="2" />
                  <rect x="152" y="54" width="20" height="12" rx="2" />
                </svg>
                <h3>No stems yet</h3>
                <p>Choose a file, then click Upload &amp; Process.</p>
                <div className="expected-stems" aria-label="Expected outputs">
                  {expectedStems.map((stem) => <span key={stem}>{stemLabel(stem)}</span>)}
                </div>
              </div>
            ) : (
              <div className="current-job">
                <div className="job-summary">
                  <h3 className="job-filename">{currentJob.filename}</h3>
                  <span className={`job-status status-${currentJob.status}`}>{currentJob.status}</span>
                </div>
                {['processing', 'pending'].includes(currentJob.status) && (
                  <div className="processing-panel">
                    <div className="progress-caption">
                      <span>{processingProgress.stage || 'Waiting for the processor...'}</span>
                      <span>{currentProgress === null ? 'Waiting...' : `${Math.round(currentProgress)}%`}</span>
                    </div>
                    <progress aria-label="Separation progress" max="100" value={currentProgress ?? undefined} />
                    <div className="processing-meta">
                      <span><Icon name="clock" /> Elapsed <span role="timer" aria-label="Elapsed processing time" aria-live="off">{formatElapsedTime(elapsedTime)}</span></span>
                      <span>CPU separation</span>
                    </div>
                    <p className="processing-note">Processing time depends on track length, model, and quality settings.</p>
                    {statusWarning && <p className="inline-notice" role="status">{statusWarning}</p>}
                    {progressWarning && <p className="inline-notice" role="status">{progressWarning}</p>}
                  </div>
                )}
                {currentJob.status === 'completed' && currentJob.output_files && (
                  <>
                    <p className="completed-summary">
                      <Icon name="check" /> Separation complete
                      {(currentJob.processing_time || elapsedTime > 0) && (
                        <span>Processed in {currentJob.processing_time || formatElapsedTime(elapsedTime)}</span>
                      )}
                    </p>
                    {currentJob.mix_stems?.length > 0 && <StemMixer key={currentJob.id} job={currentJob} apiBase={API_BASE} onJobChange={updateMixedJob} />}
                    <div className="stem-lanes">
                      {Object.keys(currentJob.output_files).map((stem) => (
                        <div className="stem-lane" key={stem}>
                          <h3 className="stem-name">{stemLabel(stem)}</h3>
                          <div className="stem-waveform">
                            <Spectrogram audioUrl={`${getDownloadUrl(currentJob.id, stem)}?v=${encodeURIComponent(currentJob.output_files[stem])}`} label={`${stemLabel(stem)} waveform`} height={52} />
                          </div>
                          <button type="button" className="download-button" aria-label={`Download ${stem}`} onClick={() => handleDownload(currentJob.id, stem)}>
                            <Icon name="download" /> Download
                          </button>
                        </div>
                      ))}
                    </div>
                    <PracticeResults job={currentJob} apiBase={API_BASE} />
                  </>
                )}
                {currentJob.status === 'failed' && <p className="error" role="alert">Separation failed: {currentJob.error}</p>}
                <details className="job-details">
                  <summary>Job details</summary>
                  <dl>
                    <div><dt>Job ID</dt><dd>{currentJob.id}</dd></div>
                    <div><dt>Created</dt><dd>{formatDate(currentJob.created_at)}</dd></div>
                  </dl>
                </details>
              </div>
            )}
          </section>

          <section className="panel history-panel" id="recent-jobs" aria-labelledby="history-heading">
            <div className="panel-header">
              <h2 id="history-heading" ref={historyHeadingRef} tabIndex={-1}><Icon name="clock" /> Recent jobs</h2>
              <span className="panel-label">Local history</span>
            </div>
            <p className="history-note">This browser stores job history. Your server stores the audio.</p>
            {historyError && <p className="error history-error" role="alert">{historyError}</p>}
            {jobsLoading && <p className="history-empty" role="status">Loading recent jobs...</p>}
            {!jobsLoading && !historyError && jobs.length === 0 && (
              <div className="history-empty"><p>No recent jobs</p></div>
            )}
            <div className="history-list">
              {jobs.slice().reverse().slice(0, 10).map((job) => (
                <article key={job.id} className="history-job">
                  <div className="history-job-header">
                    <Icon name="file" />
                    <h3 className="job-filename">{job.filename}</h3>
                    <div className="history-job-actions">
                      {job.processing_time && (
                        <span className="job-time">{job.processing_time}</span>
                      )}
                      <span className={`job-status status-${job.status}`}>{job.status}</span>
                      <button type="button" className="remove-job-button" onClick={() => handleDeleteJob(job.id)}
                        aria-label={`Remove ${job.filename} from history`} title="Remove from history">
                        <Icon name="trash" />
                      </button>
                    </div>
                  </div>
                  {job.status === 'completed' && job.output_files && (
                    <div className="history-downloads">
                      {Object.keys(job.output_files).map((stem) => (
                        <button type="button" key={stem} onClick={() => handleDownload(job.id, stem)}
                          aria-label={`Download ${stem} from ${job.filename}`}>
                          <Icon name="download" /> {stemLabel(stem)}
                        </button>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          </section>
        </div>
      </main>

      <footer className="App-footer">
        <p>Powered by Demucs</p>
        <a href="https://github.com/mbianchidev/track2stem" target="_blank" rel="noreferrer">View on GitHub <Icon name="arrow" /></a>
      </footer>
    </div>
  );
}

export default App;
