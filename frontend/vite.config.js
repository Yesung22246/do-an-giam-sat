import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    // recharts tự nó đã ~530 kB (≈150 kB gzip) — tách riêng rồi nên chấp nhận.
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        // Tách thư viện ra file riêng: trình duyệt cache lâu dài, code app đổi
        // thì người dùng chỉ phải tải lại phần app nhỏ.
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (/[\\/](recharts|d3-[^\\/]+|victory-vendor)[\\/]/.test(id))
            return "charts";
          if (id.includes("lucide-react")) return "icons";
          return "vendor";
        },
      },
    },
  },
});
