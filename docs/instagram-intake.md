# Instagram DM intake pilot

Local implementation: webhook-only FastAPI, signature checks, atomic SQLite intake, replay deduplication, and a durable Saved outbox. Live intake and Saved replies have been accepted on 13 real shares; link-only media access measured 0/13, so full video needs an upload. No Gemini, Telegram, automatic downloads, or model calls run in the Instagram worker.

## Local startup

From the repository root, use the existing dependencies or install them:

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm ci --prefix frontend
```

Edit the existing ignored `.env` locally. If absent, copy `.env.example` to `.env` first; do not overwrite existing configuration. Generate a verify token with `openssl rand -hex 32` and put it directly into `.env`. Run `chmod 600 .env`. Values are read from root `.env`, with shell environment taking precedence. API/webhook startup captures configuration; restart the webhook after changes. The reply worker reloads configuration on each iteration.

Run each command in its own terminal from the root:

```sh
# Private workspace API
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log
```

```sh
# Private browser workspace: http://127.0.0.1:5173
npm run dev --prefix frontend -- --host 127.0.0.1
```

```sh
# Only this service is exposed to Meta; no docs, workspace API, or UI routes.
backend/.venv/bin/python -m uvicorn app.instagram_webhook:app --app-dir backend --host 127.0.0.1 --port 8001 --no-access-log
```

```sh
# Instagram Saved replies only; default disabled until explicitly configured.
PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_worker
```

All services default to `backend/data/revero.sqlite3`. To use another database, export the same absolute `REVERO_DB_PATH` in every terminal before starting. Browser tests use API port 8002 (override with REVERO_TEST_API_PORT) so the webhook on 8001 can keep running.

Do not start the existing general extraction/digest worker for this pilot. The private browser app retains those existing features, but they are outside this intake gate. Refresh the inbox to see new DM saves. Reference-only saves show an internal inbox identity and a caption/upload option, without turning an attachment reference into an Instagram permalink.

## Values in root .env

| Variable | Enter locally |
| --- | --- |
| `INSTAGRAM_APP_SECRET` | The Meta app secret used to sign webhook deliveries for this app; use the app identity associated with the Instagram webhook configuration |
| `INSTAGRAM_VERIFY_TOKEN` | Your generated random string; enter the identical string in Meta's Verify token field |
| `INSTAGRAM_ACCOUNT_ID` | Receiving professional Instagram account's numeric ID from the Instagram Login connection; must match webhook entry.id and recipient.id |
| `INSTAGRAM_SENDER_ID` | Your test sender's Instagram-scoped ID, discovered below; this is not a username or the receiving account ID |
| `INSTAGRAM_ACCESS_TOKEN` | Unified Login: Business Integration System User Access Token (SUAT). Legacy Instagram Login: Instagram User token. Keep the token paired with its login flow. |
| `INSTAGRAM_LOGIN_FLOW` | `unified` for graph.facebook.com; `instagram` for legacy graph.instagram.com. Missing setting preserves legacy behavior. |
| `INSTAGRAM_API_VERSION` | Supported version selected by your Meta dashboard, including the `v`, for example `v25.0`; the example is not a promise that this version is available to your account |
| `INSTAGRAM_REPLIES_ENABLED` | Keep `false` through enrollment; set `true` when you are ready to receive Saved replies in your own test conversation |

Leave Gemini/Telegram values alone. Never paste tokens in chat, command arguments, screenshots, fixture files, URLs, or public configuration. Access logging is disabled because the Meta challenge query contains your verify token. Sender IDs shown by the local admin command are private local configuration data. Application logs contain only fixed outcomes/counts. Saved replies use Authorization headers on the host selected from the fixed two-host allowlist by `INSTAGRAM_LOGIN_FLOW`; provider response bodies and transport exception details are not persisted or printed.

## Configure Meta and the tunnel

1. Use a dedicated Instagram Business or Creator account for Revero. Use your personal/test account as the sender. For **Unified Login**, select the matching Instagram use case and Facebook Login for Business configuration, authorize `instagram_basic` and `instagram_manage_messages`, select the professional account/business portfolio, and obtain the Business Integration System User token. Set `INSTAGRAM_LOGIN_FLOW=unified`: requests use `graph.facebook.com`. For an existing **Instagram Login** integration, use its Instagram User token and `instagram_business_basic` / `instagram_business_manage_messages`, with `INSTAGRAM_LOGIN_FLOW=instagram` on `graph.instagram.com`. Add required developer/tester roles and accept invitations. Follow the dashboard's access requirements for this account; a test callback succeeding does not establish real DM eligibility. If current Meta rules require publishing or review for real events, stop and check those requirements before enabling a broader audience.
2. On the receiving Instagram account, enable **Allow access to messages** under **Connected tools** (Messages and story replies → Message requests or Message controls; labels vary). Meta error 200 stating that the account owner disabled Direct Messaging outside Instagram means this account setting is blocking integration access even when scopes and subscriptions are correct. Change it in Instagram; changing the token alone does not enable this permission. Send a greeting manually and check it appears in Revero's Instagram inbox.
3. Put the required values and matching login flow into `.env`, leaving sender ID blank and replies disabled initially. Start the webhook. Install `cloudflared` following Cloudflare's installation instructions, then run:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8001
   ```

4. In Instagram webhook configuration enter callback URL `https://<printed-host>.trycloudflare.com/webhooks/instagram` and your exact `INSTAGRAM_VERIFY_TOKEN`. Choose Verify and save. Keep the tunnel running. Quick Tunnel hostnames change after restart; update and reverify the callback. Do not tunnel port 8000 or 5173.
5. Subscribe the app webhook to **messages**. Also subscribe the professional account to the app's messages field using the Instagram dashboard control. If the control is absent, use the selected login flow's `subscribed_apps` operation with `subscribed_fields=messages` and verify the subscription via GET. Unified Login uses `POST /<INSTAGRAM_ACCOUNT_ID>/subscribed_apps` on `graph.facebook.com`, authenticated by its system-user token. Legacy Instagram Login uses `graph.instagram.com` with its Instagram User token. Do not substitute a Page ID. On Unified Login, `/me` represents the system user; query the Instagram account ID directly or discover it with `/me/assigned_instagram_accounts`. Use the dashboard API explorer or a local header-auth client so the access token never appears in shell history. Check the returned account ID matches configured `INSTAGRAM_ACCOUNT_ID`.
6. Run the dashboard test, then send a **fresh real plain text DM** from your test sender. Run:

   ```sh
   PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_admin
   ```

   The local report's `sender_candidates_local_only` contains scoped sender IDs for correctly signed deliveries to the configured receiver. Confirm the candidate by sending from your own known account; set its ID as `INSTAGRAM_SENDER_ID`. Unknown senders are never saved or replied to, and their message bodies are not stored. Restart the webhook. Send another fresh greeting: inbound text count should increase, with no Reel save or Saved job.
7. Set replies enabled to `true`, run the Instagram reply worker, and share one real Reel using Instagram's share sheet. Expect one inbox record and one Saved reply. Inspect the admin report for saved/share counts and sent state; refresh the private workspace. Share the same Reel again: a distinct inbound message may get its own Saved reply, while reusing the existing Reel. A replay of the same account/message ID creates no additional job or saved item.
8. Tell the coding agent that setup is connected and report the nonsecret outcome. Jointly verify the real DM and Reel event, refresh/restart persistence, and any payload differences. Do not send credentials or a raw private payload in chat. If no delivery arrives, check roles/invitations, account and app subscriptions, access level/app mode, permissions, token expiry, connected-tool access, and conversation ownership/routing.

The standard reply window for normal messages is 24 hours. Jobs past that window expire. Plain greetings receive no Saved acknowledgment. Successful sends are durable; delayed connect failures and 429s retry at most four attempts. Read/write timeouts, 5xx, invalid success responses, unexpected exceptions, and interrupted sending leases become uncertain and are never automatically resent. Inspect the actual Instagram conversation before resolving:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_admin --resolve 1 --outcome delivered
# Only if you established the reply was NOT delivered:
PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_admin --resolve 1 --outcome not-delivered
```

Replace 1 with the actual outbox ID. There is no external-send exactly-once guarantee after an ambiguous network outcome.

## Measure real shares before Gemini

The admin report shows attachment type, presence of provider ID/reference/title/canonical permalink, and `access_class=unmeasured`. A URL does not prove readable media. `ig_reel`/`reel` payloads use `reel_video_id` when present; other undocumented layouts should be captured as a redacted local fixture only after a real observation. No speculative media-fetch path is enabled.

For 10–20 unique shares, keep a private log under ignored `evaluation/local/`: date, local Reel/inbound IDs, attachment type/field presence, title/caption availability, and access result: **unmeasured**, **reference only**, **caption only**, **authorized playable full video**, or **unreadable**. Count real downloads only after an authorized access check verifies content type, bounded file bytes, valid media/duration, and actual playback. Do not fetch arbitrary webhook URLs blindly: a later access-check implementation must constrain hosts, redirects, timeouts, byte limits and private-network destinations. Record expiry/authentication failures without logging URLs or tokens. The local admin report is metadata availability, not the video-access experiment itself.

Report numerator/denominator for readable full videos and fallback needs. Include an inaccessible share and a DaVinci Resolve tutorial. Only after those results, extend the existing short takeaway model into timestamped walkthrough segments, index the steps, and follow the tutorial to assess correctness. Keep unknown timestamps/UI values explicit. Existing upload/caption intake remains the fallback for unreadable shares.

## Local verification

```sh
backend/.venv/bin/python -m pytest backend/tests -q
npm run build --prefix frontend
npm run test:e2e --prefix frontend
```

`backend/tests/test_instagram.py` uses authored Python payload fixtures, dummy signing secrets, temporary databases and `httpx.MockTransport`. It checks challenge responses, isolated routes, raw bytes/signatures/size, malformed payloads, account/sender filters, echo/unsupported events, batches, concurrent replay, manual URL reuse/provider identity, atomic rollback, restart persistence, exact Saved Send API request, retry/uncertain states and expiry. No test sends a real Instagram message.

## Official references

- [Unified Login authentication and token types](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/authentication)
- [Current account webhook subscription setup](https://developers.facebook.com/documentation/instagram-platform/webhooks/setup)
- [Meta webhook verification and signatures](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/)
- [Instagram Login account and permission requirements](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login)
- [Instagram API with Instagram Login — Meta collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Instagram messaging webhook fields](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/webhooks)
- [Meta attachment changelog](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog/)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

### Direct-reference access experiment

Run `PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_media_check` from the root. It checks supplied CDN references only, requires HTTPS and public addresses on the fixed CDN host allowlist, disables redirects/proxy environment settings, limits downloads to 20 MiB and bounded time, and verifies duration plus full video decoding with local ffprobe/ffmpeg. Temporary media is deleted. The private report is `evaluation/local/instagram-access-report.json`; reference URLs and titles are excluded. This experiment does not discover video behind Instagram page links or establish whether a separate authorized API lookup could obtain media.

The initial 12 unique shares all supplied references hosted on www.instagram.com. None supplied a direct allowlisted CDN URL, so no video was downloaded or playback-tested. All had titles. Authorized media discovery and caption completeness remain unmeasured; these results do not establish that the underlying videos are inaccessible.
