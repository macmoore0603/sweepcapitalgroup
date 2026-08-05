import { createFileRoute } from "@tanstack/react-router";
import { createClient } from "@supabase/supabase-js";

/**
 * Referral link redirect. Logs the click and sends the visitor to the homepage
 * with the referrer's code attached so a later purchase can be attributed.
 */
export const Route = createFileRoute("/ref/$code")({
  server: {
    handlers: {
      GET: async ({ request, params }) => {
        const code = params.code;
        const url = new URL(request.url);
        const origin = `${url.protocol}//${url.host}`;

        const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
        const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

        if (supabaseUrl && supabaseServiceKey) {
          const supabase = createClient(supabaseUrl, supabaseServiceKey);
          await supabase.from("referral_clicks").insert({
            code,
            ip: request.headers.get("cf-connecting-ip") ?? request.headers.get("x-forwarded-for") ?? null,
            user_agent: request.headers.get("user-agent") ?? null,
            utm_source: url.searchParams.get("utm_source") ?? null,
          });
        }

        const redirect = new URL("/", origin);
        redirect.searchParams.set("ref", code);
        if (url.searchParams.get("utm_source")) {
          redirect.searchParams.set("utm_source", url.searchParams.get("utm_source")!);
        }

        return new Response(null, {
          status: 302,
          headers: { Location: redirect.toString() },
        });
      },
    },
  },
});
