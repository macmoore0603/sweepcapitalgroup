# Payments restoration
- [x] Connect own Stripe account and reconcile four one-time prices.
- [x] Restore direct checkout and return-status connection with safe unavailable messaging.
- [ ] Configure the signed Stripe webhook (endpoint created per owner; owner will add STRIPE_WEBHOOK_SECRET securely).
- [x] Stripe Tax active per owner; set STRIPE_TAX_READY=true without changing Stripe products or prices.
- [x] Point purchase confirmations and their shared email helper at the existing active built-in sender domain; no DNS changes.
- [ ] Enable managed-trading purchases (needs Stripe approval).
- [x] Use Stripe receipt emails for purchase confirmations without Pro or invoice creation; keep optional webhook email failures non-blocking.
- [ ] Verify a completed checkout and confirmation email (blocked by missing webhook secret and owner prohibition on charges/publishing).