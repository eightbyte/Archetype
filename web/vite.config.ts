import react from '@vitejs/plugin-react';
// vitest/config re-exports Vite's defineConfig widened with the `test` block below.
import { defineConfig } from 'vitest/config';

// Dev is two processes (P1-14): uvicorn on 8787, Vite on 5173 with /api proxied to it.
// The single-process mode - FastAPI serving a built web/dist - is the real target shape and
// arrives in P1-14; it needs no config here because the built assets are served by the server.
const API_TARGET = 'http://127.0.0.1:8787';

export default defineConfig({
  plugins: [react()],
  server: {
    // Bound by address, not by name. Vite's default is the name `localhost`, which on Windows
    // resolves to ::1 first — so the dev server listened on IPv6 only and the documented
    // http://127.0.0.1:5173 refused the connection. Naming the address also states the D7
    // loopback posture outright rather than leaving it to name resolution.
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    restoreMocks: true,
  },
});
