import { jobMetadata } from './job-metadata.js';

const MAX_STATE_BYTES = 8 * 1024 * 1024;

export function createNativeStorage(state, persist) {
  if (state?.version !== 1 || !state.storage || typeof state.storage !== 'object' || Array.isArray(state.storage)) {
    throw new Error('Unsupported or invalid DAW project state version');
  }
  const entries = Object.entries(state.storage);
  if (entries.some(([key, value]) => !key.startsWith('track2stem_') || typeof value !== 'string')) {
    throw new Error('Invalid DAW project storage');
  }
  let values = new Map(entries);
  const update = (next) => {
    const snapshot = { version: 1, storage: Object.fromEntries(next) };
    if (new TextEncoder().encode(JSON.stringify(snapshot)).length > MAX_STATE_BYTES) {
      throw new Error('DAW project metadata exceeds 8 MiB. Remove older job history before saving more jobs.');
    }
    persist(snapshot);
    values = next;
  };
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem(key, value) {
      if (!key.startsWith('track2stem_')) throw new Error('Unexpected DAW storage key');
      update(new Map(values).set(key, String(value)));
    },
    removeItem(key) {
      const next = new Map(values);
      next.delete(key);
      update(next);
    },
    clear: () => update(new Map()),
  };
}

function encode(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  const chunks = [];
  for (let index = 0; index < bytes.length; index += 32768) {
    chunks.push(String.fromCharCode(...bytes.subarray(index, index + 32768)));
  }
  return btoa(chunks.join(''));
}

function send(tag, value) {
  window.IPlugSendMsg({ msg: 'SAMFUI', msgTag: tag, ctrlTag: -1, data: value ? encode(value) : 0 });
}

async function restoreCurrentJob(storage, apiBase) {
  const saved = storage.getItem('track2stem_current_job');
  if (!saved) return;
  const job = JSON.parse(saved);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9-]{0,254}$/.test(job.id)) throw new Error('Saved DAW job reference is invalid');
  const response = await fetch(`${apiBase}/jobs/${job.id}`, { signal: AbortSignal.timeout(5000) });
  if (response.ok) {
    storage.setItem('track2stem_current_job', JSON.stringify(jobMetadata(await response.json())));
  } else if (response.status === 404) {
    storage.setItem('track2stem_current_job', JSON.stringify({
      ...job, status: 'failed',
      error: 'Processed audio is missing or this job was interrupted. Import the source again. DAW projects store references, not audio.',
    }));
  } else {
    throw new Error(`Could not restore the saved job (${response.status}). Check the local worker and retry.`);
  }
}

export function initializeNativeHost(onReady, onError) {
  let generation = 0;
  let ready = false;
  const timeout = setTimeout(() => onError(new Error('The local worker did not connect. Restart it from the plugin.')), 25000);
  window.SPVFD = () => {};
  window.SCVFD = () => {};
  window.SCMFD = () => {};
  const receive = async (_tag, _size, encoded) => {
    try {
      const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
      const message = JSON.parse(new TextDecoder().decode(bytes));
      if (message.type === 'host_ready') {
        const current = ++generation;
        if (message.version !== 1) throw new Error('Unsupported native host contract version');
        if (!Number.isSafeInteger(message.generation) || message.generation < 0) throw new Error('Invalid DAW restore generation');
        const url = new URL(message.api_base);
        if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port
          || url.username || url.password || !/^\/[a-zA-Z0-9_-]{20,}\/api$/.test(url.pathname)) {
          throw new Error('The native worker supplied an invalid local address');
        }
        const storage = createNativeStorage(message.state, (state) => {
          if (current === generation) send(101, { ...state, generation: message.generation });
        });
        await restoreCurrentJob(storage, message.api_base);
        if (current !== generation) return;
        clearTimeout(timeout);
        ready = true;
        window.track2stemHost = {
          apiBase: message.api_base,
          storage,
          async download(url) {
            try {
              if (!url.startsWith(`${message.api_base}/`)) throw new Error('Refusing a non-local export');
              const response = await fetch(url, { method: 'HEAD', signal: AbortSignal.timeout(5000) });
              if (!response.ok) throw new Error(`Stored audio is unavailable (${response.status}). Import the source again if files were removed.`);
              window.location.assign(url);
            } catch (failure) {
              console.error('Native export could not start:', failure);
              window.dispatchEvent(new CustomEvent('track2stem-native-message', {
                detail: { type: 'native_error', message: `Export failed. ${failure.message}` },
              }));
            }
          },
        };
        onReady(current);
      } else if (message.type === 'native_error' || message.type === 'native_notice') {
        if (!ready && message.type === 'native_error') onError(new Error(message.message));
        else window.dispatchEvent(new CustomEvent('track2stem-native-message', { detail: message }));
      }
    } catch (error) {
      console.error('Native bridge failed:', error);
      clearTimeout(timeout);
      onError(error);
    }
  };
  window.SAMFD = (...args) => {
    void receive(...args);
    return null;
  };
  send(100);
}

export function restartNativeWorker() {
  send(102);
}
