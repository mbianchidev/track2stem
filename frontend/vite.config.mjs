import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const fontLicenses = {
  name: 'local-font-licenses',
  generateBundle() {
    for (const font of ['barlow-condensed', 'ibm-plex-sans', 'ibm-plex-mono']) {
      const directory = path.dirname(require.resolve(`@fontsource/${font}/400.css`));
      this.emitFile({ type: 'asset', fileName: `font-licenses/${font}.txt`,
        source: readFileSync(path.join(directory, 'LICENSE'), 'utf8') });
    }
  },
};

export default defineConfig({
  plugins: [react(), fontLicenses],
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.js'],
  },
});
