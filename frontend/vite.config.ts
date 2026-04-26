import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    host: "::",
    port: 8080,
    hmr: {
      overlay: false,
    },
    // Dev-only proxy so the SPA can call /lit-review, /protocol, /materials
    // as if they were same-origin. In production these are expected to live
    // behind a reverse proxy or under the same origin as the Flask app.
    proxy: {
      "/lit-review":   "http://localhost:5000",
      "/protocol":     "http://localhost:5000",
      "/protocol/pdf": "http://localhost:5000",
      "/materials":    "http://localhost:5000",
      "/timeline":     "http://localhost:5000",
      "/validation":   "http://localhost:5000",
      "/critique":     "http://localhost:5000",
      "/health":       "http://localhost:5000",
    },
  },
  plugins: [react(), mode === "development" && componentTagger()].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime", "@tanstack/react-query", "@tanstack/query-core"],
  },
}));
