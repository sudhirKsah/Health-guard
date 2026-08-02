import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Health Guard",
    short_name: "Health Guard",
    description: "Autonomous, bounded replenishment for recurring OTC care supplies.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#f6f9f4",
    theme_color: "#195337",
    orientation: "portrait-primary",
    categories: ["health", "lifestyle", "productivity"],
    icons: [
      {
        src: "/icons/icon-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/icons/icon-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
