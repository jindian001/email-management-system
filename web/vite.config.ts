import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
// https://vitejs.dev/config/
// 产物直接输出到后端静态目录，FastAPI 挂在 /ui/ 下提供服务
export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  build: {
    outDir: "../src/mailmind/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8080",
    },
  },
});
