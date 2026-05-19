# Social agent — phase 1 (cadence-enforced foundation)

Goal: ship the agent end-to-end with the ≥3 posts/day rule wired into the scheduler, planner, and UI. Real platform publishing turns on per-platform as you provide OAuth app credentials.

## What gets built now

**Database (Lovable Cloud migration)**
- `social_accounts` — platform, handle, encrypted oauth tokens, owner `user_id`, `min_posts_per_day` (default 3), `posting_windows` (jsonb: e.g. `[{"hour":9},{"hour":13},{"hour":18}]`), RLS scoped to owner.
- `scheduled_posts` — account_id, status (`draft|scheduled|publishing|published|failed|cancelled`), scheduled_for, body, media_urls, platform_post_id, error, RLS scoped to owner via account.
- `post_metrics` — post_id, impressions, likes, comments, fetched_at.
- `agent_settings` — per-user defaults: global `min_posts_per_day=3`, brand voice overrides.
- pgcrypto-encrypted token columns (`SOCIAL_TOKEN_KEY` secret).

**Server functions / routes** (`src/lib/social/*.functions.ts`, `src/routes/api/social/*`, `src/routes/api/public/social/tick.ts`)
- `draft` — streams platform-tuned drafts via Lovable AI Gateway (`google/gemini-3-flash-preview`), runs guardrails from the skill.
- `schedule` — CRUD on `scheduled_posts`, **rejects any day that would leave an account under its `min_posts_per_day`**.
- `autofill-day` — given an account + date, generates and schedules enough drafts to hit the ≥3/day minimum using the account's `posting_windows`.
- `publish/$id` — generic dispatcher, calls per-platform publisher.
- `oauth/$platform` start/callback stubs (return "credentials not configured" until secrets exist).
- `/api/public/social/tick` — pg_cron hits every minute, claims due posts with `FOR UPDATE SKIP LOCKED`, fires publishers, **and tops up the day if any account is below quota** (creates new drafts in remaining windows).

**Cadence enforcement (the core of this request)**
- Daily pg_cron at 00:05 user-local-ish (UTC for now): for every active `social_account`, ensure ≥3 scheduled or published posts exist for "today" in its `posting_windows`. Missing slots get auto-drafted (status `draft` → user can edit, otherwise auto-promotes to `scheduled` after a configurable grace window).
- Hourly safety net: if a slot's time has passed and the post is still `draft`, auto-promote to `scheduled` for the next free window so we never silently miss the quota.
- UI surfaces a daily quota meter per account (e.g. "2/3 scheduled today — autofill").

**UI (`/agent`)**
- Accounts page with connect buttons per platform + per-account `min_posts_per_day` (defaults to 3, can be raised, never set below 3) and posting-window editor.
- Composer (AI Elements chat) with platform multi-select.
- Calendar with the 3 daily slots highlighted; under-quota days flagged red.
- "Autofill week" button → fills every account to ≥3/day for the next 7 days.

**Publishers** — files in `src/lib/social/publishers/` for `instagram.ts`, `x.ts`, `linkedin.ts`, `tiktok.ts`, `youtube.ts`. Each exports `{ publish, refreshToken, fetchMetrics, oauthStart, oauthCallback }`. Until credentials exist, `publish` writes status `failed` with error `"<platform> credentials not configured"` so the queue stays honest.

## What needs you (deferred — add per platform when you're ready)

OAuth client IDs/secrets — I'll request via `add_secret` only when you say "enable Instagram" etc.:
- `META_APP_ID`, `META_APP_SECRET` (Instagram + Facebook)
- `X_CLIENT_ID`, `X_CLIENT_SECRET`
- `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`
- `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` (YouTube Shorts)
- `SOCIAL_TOKEN_KEY` (random 32-byte string for token encryption)

`LOVABLE_API_KEY` is already set, so drafting works on day one.

## Out of scope for phase 1

- Actual video file synthesis (TikTok/YT publishers will accept uploaded MP4s in phase 2).
- Paid ads (you confirmed organic-only).
- DM/inbox auto-reply.

## After you approve

I'll run the migration first (you confirm), then write the server functions, scheduler, publishers, and `/agent` UI. Then we wire up platforms one at a time as you drop in credentials.
