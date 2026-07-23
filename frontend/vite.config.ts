import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api and /health are proxied to the FastAPI backend so the app needs no
// CORS setup or hardcoded API host during development.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
