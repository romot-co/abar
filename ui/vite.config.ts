import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` は起動中の `abar ui` バックエンドへ /api を中継する。
// バックエンドはHost/Originを検証するため、両方をターゲット側へ書き換える。
const backend = process.env.ABAR_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("origin", backend);
          });
        },
      },
    },
  },
  build: {
    outDir: "../src/abar/server/static",
    emptyOutDir: true,
    sourcemap: false,
  },
});
