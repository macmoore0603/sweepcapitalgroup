---
name: social-growth-agent
description: Use when building or extending the Lexus Nexus Capital social growth AI agent — drafting and auto-posting organic content to Instagram, X, LinkedIn, and TikTok/YouTube Shorts. Triggers on "social media agent", "post to Instagram/X/LinkedIn/TikTok", "content calendar", "auto-post", "grow followers", "social ads" (organic-only here — redirect paid asks).
---

# Social Growth Agent

Builds and iterates on an in-app AI agent that drafts, schedules, and auto-publishes organic social content for Lexus Nexus Capital Group across Instagram, X, LinkedIn, and TikTok/YouTube Shorts.

## When to use
- User asks to add, change, or debug the social agent UI, drafting logic, scheduler, or any platform publisher
- User asks for a content calendar, weekly plan, hashtag set, or caption rewrite
- User mentions connecting a new social account or rotating tokens

## Architecture

```
src/routes/api/social/
  draft.ts            POST → AI SDK streamText, returns platform-tuned drafts
  schedule.ts         POST/GET → CRUD on scheduled_posts table
  publish/$id.ts      POST → publishes a single scheduled_post (called by pg_cron)
  oauth/$platform.ts  GET → start/complete OAuth for IG/X/LinkedIn/TikTok
src/routes/agent/     in-app dashboard: accounts, queue, calendar, draft chat
src/lib/social/
  prompts.ts          brand voice + per-platform system prompts
  publishers/         one file per platform; each exports `publish(post, token)`
  guardrails.ts       compliance checks (see Guardrails)
```

DB tables (Lovable Cloud): `social_accounts` (platform, handle, encrypted access_token, refresh_token, expires_at, owner user_id), `scheduled_posts` (account_id, status, scheduled_for, body, media_urls, platform_post_id, error), `post_metrics` (post_id, impressions, likes, comments, fetched_at). RLS scopes everything to the authenticated owner.

## Workflow

1. **Draft endpoint** uses `streamText` from the AI SDK with the Lovable AI Gateway provider (`google/gemini-3-flash-preview` by default). System prompt comes from `prompts.ts` and is composed of:
   - Brand voice block (institutional, restrained, no hype, no return promises — the site copy in `src/routes/index.tsx` is the source of truth).
   - Platform block (length limits, hashtag rules, CTA shape — see Platform conventions).
   - Goal block from the user (announcement, lesson, market commentary, mentorship CTA).
2. **Guardrails** run on every generated draft *and* every manual edit before it leaves draft state. See Guardrails — these are non-negotiable for a regulated finance brand.
3. **Scheduling** writes to `scheduled_posts` with `status='scheduled'`. A `pg_cron` job every minute calls `/api/public/social/tick` which selects due posts and POSTs each to `/api/social/publish/$id` with the anon key in the `apikey` header (see schedule-jobs-options knowledge — do not invent a custom shared secret).
4. **Publishers** each: refresh the OAuth token if `expires_at < now() + 5m`, upload media if needed, post, store `platform_post_id`, set `status='published'` or `status='failed'` with the API error message. Never throw past the route handler — always update the row.
5. **Metrics** pull runs daily via the same pg_cron pattern, hitting each platform's insights/analytics endpoint per published post younger than 30 days.

## Platform conventions

| Platform | API | Auth | Key rules |
| --- | --- | --- | --- |
| Instagram | Graph API (IG Business account via linked Facebook Page) | Meta OAuth, `instagram_content_publish`, `pages_show_list` | Two-step: create media container → publish. Square/4:5 images perform best. 30 hashtag max; use 8–15. |
| X / Twitter | API v2 `/2/tweets` | OAuth 2.0 PKCE, `tweet.write`, `users.read`, `offline.access` | 280 chars. Threads = multiple POSTs with `reply.in_reply_to_tweet_id`. No more than 2 hashtags. |
| LinkedIn | `/rest/posts` (Versioned API, header `LinkedIn-Version: 202404` or newer) | OAuth 2.0, `w_member_social` for personal, `w_organization_social` for company page | 3000 char limit but keep <1300. First 210 chars show before "see more". |
| TikTok / YT Shorts | TikTok Content Posting API / YouTube Data API v3 `videos.insert` | TikTok: `video.publish`; YouTube: `youtube.upload` | Video only. Generate captions + hook (first 3s) + on-screen text suggestions; actual video file is uploaded by the user, agent does not synthesize video. |

Each platform requires the user to register a developer app and provide client ID/secret. Use `secrets--add_secret` for `META_APP_ID`/`META_APP_SECRET`, `X_CLIENT_ID`/`X_CLIENT_SECRET`, `LINKEDIN_CLIENT_ID`/`LINKEDIN_CLIENT_SECRET`, `TIKTOK_CLIENT_KEY`/`TIKTOK_CLIENT_SECRET`, `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`. Per-user OAuth tokens live in `social_accounts`, not in secrets — the connector pattern does not fit here because each end-user authorizes their own account.

## Guardrails (run on every draft)

Reject or strip before publish — fail loud in the UI:

- **No return/performance promises.** Block "guaranteed", "risk-free", "X% returns", "double your money", specific future price targets. Past audited stats from the site (68.4% win rate, etc.) are allowed only with the qualifier "audited, past performance is not indicative of future results".
- **No solicitation of unregistered securities.** Reject anything that reads as an investment offering. Mentorship and education framing only.
- **No client testimonials with dollar figures** unless flagged `compliance_reviewed=true` on the source record.
- **Disclaimer suffix** required on any post that discusses trading methodology, results, or capital: append "Educational content. Not financial advice." (X: shorten to "Not financial advice.")
- **Brand voice check**: reject emoji-heavy drafts (>2 emoji), all-caps lines other than the existing brand wordmark, and exclamation marks (>1). The brand is restrained.

Run guardrails as a pure function returning `{ ok: boolean; violations: string[]; sanitized?: string }`. The drafting endpoint streams to the UI, then the guardrails result is appended as a structured part the UI renders below the draft.

## Scheduler

- `pg_cron` every minute → `net.http_post` to `/api/public/social/tick` with `apikey` header set to the Supabase anon key. No custom `CRON_SECRET`.
- `tick` claims due rows with `UPDATE scheduled_posts SET status='publishing' WHERE id IN (SELECT id FROM scheduled_posts WHERE status='scheduled' AND scheduled_for <= now() FOR UPDATE SKIP LOCKED LIMIT 20) RETURNING id` to avoid double-publish.
- For each claimed id, fire-and-forget POST to `/api/social/publish/$id`. That route owns the publish + status update.

## UI

In-app dashboard at `/agent`:
- **Accounts**: list connected social accounts with connect/disconnect buttons per platform.
- **Composer**: chat-style draft surface using AI Elements (`PromptInput`, `Conversation`, `Message`, `MessageResponse`) — follow the `chat-agent-ui-contract`. Multi-platform target selector; one stream produces N platform-tuned variants in parallel via `Output.array`.
- **Calendar**: week view of `scheduled_posts`, drag to reschedule.
- **Performance**: per-account stats from `post_metrics`.

Brand-match the dashboard to the existing site (black background, mono labels, accent color, no Sparkles icon — use the existing `lnc-logo.png`).

## Conventions

- Server functions only for AI calls and platform API calls — never call platform APIs from the browser.
- Use `attachSupabaseAuth` (already wired in `src/start.ts`) so server fns see the authed user.
- Encrypt OAuth tokens at rest. Use `pgcrypto` `pgp_sym_encrypt(token, current_setting('app.token_key'))` and store the key as the `SOCIAL_TOKEN_KEY` secret.
- Add new platforms by dropping a file into `src/lib/social/publishers/` exporting `{ publish, refreshToken, fetchMetrics, oauthStart, oauthCallback }`. The route layer is generic.

## Validation

Before claiming a change works:
1. Draft endpoint streams a sample post and the guardrails block visibly rejects a planted phrase ("guaranteed returns").
2. Connect at least one real account end-to-end (OAuth round trip lands back at `/agent` with the new account row).
3. Schedule a post 2 minutes out and confirm `pg_cron` fires it and the `platform_post_id` is populated.
4. Disconnecting an account leaves no orphan `scheduled_posts` in `status='scheduled'` (cancel them in the same transaction).

## Out of scope (push back if asked)

- Paid ads (Meta Ads Manager, Google Ads). The user chose organic-only — confirm before adding paid flows.
- Generating video files. Agent produces scripts, hooks, and captions; the user uploads the actual video.
- DM auto-reply / inbox management — separate skill if requested later.
