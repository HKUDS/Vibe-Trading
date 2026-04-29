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
      "/run": { target: "http://localhost:8899", changeOrigin: true },
      "/runs": { target: "http://localhost:8899", changeOrigin: true },
      "/health": { target: "http://localhost:8899", changeOrigin: true },
      "/sessions": { target: "http://localhost:8899", changeOrigin: true },
      "/skills": { target: "http://localhost:8899", changeOrigin: true },
      "/swarm/presets": { target: "http://localhost:8899", changeOrigin: true },
      "/swarm/runs": { target: "http://localhost:8899", changeOrigin: true },
      "/settings/llm": { target: "http://localhost:8899", changeOrigin: true },
      "/settings/data-sources": { target: "http://localhost:8899", changeOrigin: true },
      "/upload": { target: "http://localhost:8899", changeOrigin: true },
      "/api": { target: "http://localhost:8899", changeOrigin: true },
      "/system": { target: "http://localhost:8899", changeOrigin: true },
      "/shadow-reports": { target: "http://localhost:8899", changeOrigin: true },
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
