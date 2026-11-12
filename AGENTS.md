# Architecture
- Keep direct Stripe access in server-only helpers using the fetch HTTP client; account credentials must never enter browser bundles.
- Validate checkout tiers and amounts against the shared payment catalog; block live managed-service purchases until explicit provider approval is configured.
- Return only the configured publishable key through a public server function, and isolate test/live keys and signed webhook secrets.
- Build Stripe session options in a pure typed helper and finish paid-order recording before best-effort app email; receipt configuration can be tested without charges and email failures cannot gate fulfillment.