import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
  plugins: [react(), tailwindcss()],
  base: process.env.VITE_BASE_PATH || "/",
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8793",
        changeOrigin: true,
        ws: true,
      },
    },
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
}));
