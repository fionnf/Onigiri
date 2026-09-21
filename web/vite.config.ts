import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectManifest: { globPatterns: ["**/*.{js,css,html,svg,png,woff2}"] },
      devOptions: { enabled: false, type: "module" },
      manifest: {
        name: "Onigiri",
        short_name: "Onigiri",
        description: "Your recipe bank: capture from Instagram, the web and photos.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#0b0b0c",
        theme_color: "#0b0b0c",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "/icon-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
        // The service worker intercepts this POST, so no cookie crosses a site boundary.
        share_target: {
          action: "/share-target",
          method: "POST",
          enctype: "multipart/form-data",
          params: {
            title: "title",
            text: "text",
            url: "url",
            files: [
              { name: "files", accept: ["image/*", "video/*"] },
            ],
          },
        },
        shortcuts: [
          { name: "Add a recipe", url: "/add" },
          { name: "Needs review", url: "/?status=needs_review" },
        ],
      },
    }),
  ],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: { outDir: "dist", sourcemap: false, target: "es2022" },
});
