import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5899,
    proxy: {
      "/run": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/runs": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/health": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/sessions": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/skills": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/swarm/presets": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/swarm/runs": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/settings/llm": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/settings/data-sources": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/correlation": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/upload": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/api": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/system": { target: "http://101.32.115.139:8888", changeOrigin: true },
      "/shadow-reports": { target: "http://101.32.115.139:8888", changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-charts": ["echarts"],
        },
      },
    },
  },
});
