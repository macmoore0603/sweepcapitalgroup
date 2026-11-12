# Payments restoration
- [x] Connect own Stripe account and reconcile four one-time prices.
- [x] Restore direct checkout and return-status connection with safe unavailable messaging.
- [ ] Configure the signed Stripe webhook (needs published callback and account signing secret).
- [x] Stripe Tax active per owner; set STRIPE_TAX_READY=true without changing Stripe products or prices.
- [x] Point purchase confirmations and their shared email helper at the existing active built-in sender domain; no DNS changes.
- [ ] Enable managed-trading purchases (needs Stripe approval).
- [ ] Enable purchase-confirmation sending (built-in custom app emails require Pro, listed at $25 USD/month; existing active domain does not bypass Free-plan restriction). No upgrade authorized; stopped.
- [ ] Verify a completed checkout and confirmation email (blocked by missing webhook secret and owner prohibition on charges/publishing).