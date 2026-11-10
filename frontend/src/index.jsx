import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import '@fontsource/barlow-condensed/500.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import App from './App.jsx';
import { initializeNativeHost, restartNativeWorker } from './native-host.js';

const root = ReactDOM.createRoot(document.getElementById('root'));
const renderApp = (revision = 'browser') => root.render(
  <React.StrictMode><App key={revision} /></React.StrictMode>,
);
if (typeof window.IPlugSendMsg === 'function') {
  root.render(<p role="status" className="native-startup">Connecting to the local CPU worker...</p>);
  initializeNativeHost(renderApp, (error) => root.render(
    <div className="native-startup">
      <p role="alert">{error.message}</p>
      <button type="button" onClick={restartNativeWorker}>Restart local worker</button>
    </div>,
  ));
} else {
  renderApp();
}
