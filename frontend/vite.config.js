import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies /api to the FastAPI server, so the phone only needs this one origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
