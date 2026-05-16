import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect } from "react";

import appCss from "../styles.css?url";
import { Toaster } from "@/components/ui/sonner";

const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"] as const;

function captureFirstTouchAttribution() {
  if (typeof window === "undefined") return;
  try {
    const STORAGE_KEY = "lnc_attribution";
    if (window.sessionStorage.getItem(STORAGE_KEY)) return;
    const url = new URL(window.location.href);
    const data: Record<string, string> = {
      landing_page: window.location.href,
    };
    if (document.referrer) data.referrer = document.referrer;
    for (const k of UTM_KEYS) {
      const v = url.searchParams.get(k);
      if (v) data[k] = v;
    }
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // ignore
  }
}

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "Lexus Nexus Capital Group — Institutional Trading" },
      { name: "description", content: "Private, institutional-grade day trading mentorship and capital allocation for serious investors. Discipline is the only edge." },
      { name: "author", content: "Lexus Nexus Capital Group" },
      { property: "og:title", content: "Lexus Nexus Capital Group — Institutional Trading" },
      { property: "og:description", content: "Private, institutional-grade day trading mentorship and capital allocation for serious investors. Discipline is the only edge." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:site", content: "@LexusNexusCap" },
      { name: "twitter:title", content: "Lexus Nexus Capital Group — Institutional Trading" },
      { name: "twitter:description", content: "Private, institutional-grade day trading mentorship and capital allocation for serious investors. Discipline is the only edge." },
      { property: "og:image", content: "https://lexusnexuscapital.com/og-card.jpg" },
      { property: "og:image:width", content: "1200" },
      { property: "og:image:height", content: "630" },
      { property: "og:image:alt", content: "Lexus Nexus Capital Group — Success is the only edge." },
      { name: "twitter:image", content: "https://lexusnexuscapital.com/og-card.jpg" },
      { name: "twitter:image:alt", content: "Lexus Nexus Capital Group — Success is the only edge." },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  useEffect(() => {
    captureFirstTouchAttribution();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <Outlet />
      <Toaster richColors theme="dark" position="top-right" />
    </QueryClientProvider>
  );
}
