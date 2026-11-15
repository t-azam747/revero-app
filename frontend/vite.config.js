import { defineConfig } from 'vite';
export default defineConfig({ server: { host: '127.0.0.1', port: Number(process.env.REVERO_WEB_PORT || 5173), strictPort: true, proxy: { '/api': process.env.REVERO_API_TARGET || 'http://127.0.0.1:8000' } } });
