import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// K-RE MAP — Vite 설정 (map.enxight.com 루트 서빙 전제)
export default defineConfig({
  plugins: [react()],
});
