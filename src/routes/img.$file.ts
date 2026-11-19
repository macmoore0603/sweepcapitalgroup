import { createFileRoute } from "@tanstack/react-router";
import type {} from "@tanstack/react-start";

const TYPES: Record<string, string> = { webp: "image/webp", jpg: "image/jpeg", png: "image/png" };

// Serves optimized images (OG cards, founder photo) from a base64 module.
export const Route = createFileRoute("/img/$file")({
  server: {
    handlers: {
      GET: async ({ params }) => {
        const { SITE_IMAGES } = await import("@/lib/site-images");
        const data = SITE_IMAGES[params.file];
        if (!data) return new Response("Not found", { status: 404 });
        const bin = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
        const ext = params.file.split(".").pop() ?? "";
        return new Response(bin, {
          headers: {
            "Content-Type": TYPES[ext] ?? "application/octet-stream",
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
          },
        });
      },
    },
  },
});
