# Architecture
- Keep direct Stripe access in server-only helpers using the fetch HTTP client; account credentials must never enter browser bundles.
- Validate checkout tiers and amounts against the shared payment catalog; block live managed-service purchases until explicit provider approval is configured.
- Return only the configured publishable key through a public server function, and isolate test/live keys and signed webhook secrets.