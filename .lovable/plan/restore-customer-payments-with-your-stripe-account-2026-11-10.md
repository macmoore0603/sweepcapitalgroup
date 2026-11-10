# Restore customer payments with your Stripe account

## Current status
- Your own Stripe account is connected using a live restricted key.
- The account already contains The Edge at $1,000 and Managed Trading at $1,000.
- The existing Full Send price is $3,000, not the website’s $2,000; Apprenticeship is missing.
- Website checkout still points at the disconnected built-in integration, so connecting the account alone has not restored payments.

## What to deliver
1. Keep the four website tiers and one-time USD prices: The Edge $1,000; Apprenticeship $1,500; Managed Trading $1,000; Full Send $2,000.
2. Reuse matching products and prices. Add the missing Apprenticeship and a new $2,000 Full Send price without deleting the old price or unrelated products.
3. Connect the website’s existing checkout and order-status page directly to your Stripe account, preserving guest checkout.
4. Restore verified payment notifications so purchase-confirmation emails and existing recovery automations work with the new account.
5. Verify each tier opens checkout at the correct amount and test payment confirmation without making a real charge.

## Tax and eligibility
- Managed trading requires Stripe approval; the provider recommendation does not establish Stripe eligibility. Confirm approval before collecting payments for that service or its bundle.
- Full compliance handling is not a suitable default for this human-involved financial-services catalog. Use Stripe tax calculation and collection (+0.5%); the business remains responsible for registration, filing, and remittance. Verify product tax codes and Stripe Tax configuration before enabling it.

## What you may need to provide
- A matching Stripe publishable key, entered securely, for the embedded checkout.
- Adequate restricted-key permissions for products, prices, Checkout Sessions, payment-status reads, and webhook configuration. The current key cannot read account details; this alone does not prove checkout permissions are missing.
- A test key and matching test publishable key for a no-real-money payment test.
- The new webhook signing secret, entered securely after the callback is configured.

## Technical details
- Replace the disconnected gateway client with the existing Stripe SDK’s fetch-based direct client using the securely stored account key.
- Preserve the existing server functions, embedded checkout interface, return route, and signed public webhook; do not introduce a second payment flow.
- Keep test/live account keys and webhook secrets isolated, and map only the four allowed tier identifiers to account prices.
- Add focused tests for the four price amounts and tier mapping; verify the customer checkout flow and signed notification handling.

## Completion criteria
All four correct prices are reachable through the website, order status reads back correctly, and a verified test payment produces its confirmation email. Any account approval, key permissions, or paused Cloud services that prevent verification will be reported explicitly. Publishing follows verification.