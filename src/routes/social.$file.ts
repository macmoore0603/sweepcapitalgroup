import { createFileRoute } from "@tanstack/react-router";
import type {} from "@tanstack/react-start";

// Serves the branded social images used for scheduled Instagram/Facebook posts.
export const Route = createFileRoute("/social/$file")({
  server: {
    handlers: {
      GET: async ({ params }) => {
        const { SOCIAL_IMAGES } = await import("@/lib/social-images");
        const data = SOCIAL_IMAGES[params.file];
        if (!data) return new Response("Not found", { status: 404 });
        const bin = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
        return new Response(bin, {
          headers: {
            "Content-Type": "image/png",
            "Cache-Control": "public, max-age=86400",
          },
        });
      },
    },
  },
});
