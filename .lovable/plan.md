# Sierra — your personal AI assistant

A phone number you can text and call. Sierra is locked to your verified number, runs on Lovable AI (Gemini 3 Flash + GPT-5 for hard reasoning), and can actually *do things* on your behalf by reusing this project's existing tools.

## What you get

- **Text Sierra** at a Twilio number → conversational replies in seconds, with full memory.
- **Call Sierra** → she answers, listens (Twilio speech recognition), replies with natural TTS (Twilio Polly Neural / ElevenLabs if a key is set). Each turn streams through the same tool-using agent.
- **Locked to your phone number** — any other caller hears a polite "this line is private" and gets dropped. Allowlist editable in `/sierra`.
- **Tools she can use mid-conversation**:
  1. `schedule_social_post` — drafts & schedules to Instagram (and future X/LinkedIn) via the existing `scheduled_posts` pipeline. Runs the same guardrails.
  2. `create_reminder` — "remind me to call Marcus at 4pm" → row in `sierra_reminders`, cron texts you at the time.
  3. `web_search` — live lookup via Lovable AI grounding for prices, news, facts.
  4. `send_email` — drafts and sends via your existing email infra (Resend) to any address.
  5. `get_calendar_today` — reads `sierra_reminders` for the next 24h so she can answer "what's on today?".

## Dashboard at `/sierra`

- Header: connection status (Twilio number, allowed callers, last message).
- Live conversation feed (SMS + transcribed calls in one timeline).
- Allowlist editor — add/remove phone numbers.
- Reminder list with cancel.
- System-prompt editor (default: institutional concierge voice matching LNC brand).

## Technical layout

```text
src/routes/
  sierra.tsx                              ← in-app dashboard
  api/public/sierra/
    sms.ts                                ← Twilio inbound SMS webhook
    voice.ts                              ← Twilio inbound voice (returns TwiML)
    voice/gather.ts                       ← per-turn speech result → TTS reply
    voice/status.ts                       ← call lifecycle logging
    reminders/tick.ts                     ← pg_cron every minute → send due reminders
src/lib/sierra/
  agent.ts                                ← streamText + tools, brand system prompt
  tools.ts                                ← all 5 tools (Zod schemas, executors)
  twilio.ts                               ← signed REST calls via Twilio connector gateway
  twiml.ts                                ← TwiML builders (<Say>, <Gather>, <Hangup>)
  auth.ts                                 ← verify X-Twilio-Signature + allowlist check
```

### Database (one migration)

- `sierra_owners (user_id, phone_e164, label, is_admin)` — allowlist; RLS to owner.
- `sierra_conversations (id, phone_e164, channel sms|voice, created_at)` — one per phone.
- `sierra_messages (id, conversation_id, role user|assistant|tool, parts jsonb, twilio_sid, created_at)` — full UIMessage log for memory across SMS + voice in one thread per number.
- `sierra_reminders (id, owner_user_id, phone_e164, body, due_at, status pending|sent|cancelled)`.
- Realtime enabled on `sierra_messages` so `/sierra` updates live.

### Security

- Every Twilio webhook verifies `X-Twilio-Signature` with `TWILIO_AUTH_TOKEN` before touching anything.
- `From` number must exist in `sierra_owners` or the call/text is rejected (voice: "this line is private"; SMS: silent drop).
- Twilio creds come from the Twilio standard connector (already supported). No raw secrets in code.
- `LOVABLE_API_KEY` already provisioned.

### Voice loop

1. Twilio dials in → `POST /api/public/sierra/voice` → TwiML: `<Say>Hi, it's Sierra.</Say><Gather input="speech" action="/api/public/sierra/voice/gather" speechTimeout="auto"/>`
2. Caller speaks → Twilio transcribes → POSTs `SpeechResult` to `/gather` → we append to the conversation, call `streamText` with full history + tools, take the assistant text, return TwiML: `<Say voice="Polly.Joanna-Neural">{reply}</Say><Gather .../>`
3. Repeats until silence or hangup. Status webhook logs duration.

This is **not** OpenAI Realtime (which needs raw WebSocket bridging Twilio Media Streams ↔ OpenAI — workable on Cloudflare Workers but adds a week of work). The Gather-loop is ~600ms turn latency, sounds natural with Neural voices, and reuses the exact same tool agent as SMS. We can upgrade to Realtime later as a drop-in replacement.

### SMS loop

`POST /api/public/sierra/sms` → verify → append user message → `streamText` with tools → reply via Twilio Messages API → log assistant message. Multi-step tool calls (`stepCountIs(50)`) so she can chain: search → draft → schedule in one turn.

### Reminders cron

`pg_cron` every minute → `POST /api/public/sierra/reminders/tick` → claim due rows, send SMS via Twilio, mark `sent`.

## What you'll need to provide

1. **Connect the Twilio connector** (one-click) — gives Sierra Account SID + an API key.
2. **A Twilio phone number** with SMS + Voice capability. Tell me the E.164 number and I'll wire the webhooks.
3. **Your iPhone's E.164 number** (e.g. +13105551234) — gets inserted as the first allowed owner.
4. Confirm `TWILIO_AUTH_TOKEN` so we can validate webhook signatures (separate from the API key — used only for HMAC verification).

## Out of scope for v1 (say the word and I'll add)

- OpenAI Realtime / ElevenLabs Conversational AI for sub-200ms voice.
- WhatsApp channel.
- Outbound calls (Sierra calling *you*).
- Calendar sync to Google/Apple (we use a local reminder table instead).
- Paid social posting — only organic, per existing brand guardrails.

Approve and I'll start with the migration + Twilio connector, then build the SMS path end-to-end before voice.