import { createFileRoute } from "@tanstack/react-router";
import { getHealthStatus } from "@/lib/health";

export const Route = createFileRoute("/api/health")({
  server: {
    handlers: {
      GET: async () => Response.json(getHealthStatus()),
    },
  },
});
