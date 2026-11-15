# Revero Instagram DM intake

The first milestone is to share a Reel from Instagram's share sheet to the Revero professional account, receive **Saved** in the same chat, and see one saved item in the local inbox. The website remains the workspace for walkthroughs, search, and actions. Telegram remains the nightly delivery channel.

Local implementation and signed/mock tests are now available. See [exact commands, environment values and live acceptance procedure](docs/instagram-intake.md). Live DM/Reel verification and media access measurement remain pending.

## Current login flow correction

The pilot account uses **Unified Login**. Set `INSTAGRAM_LOGIN_FLOW=unified` and use the Business Integration System User token on `graph.facebook.com`, with `instagram_basic` and `instagram_manage_messages`. The older Instagram Login instructions below apply only when `INSTAGRAM_LOGIN_FLOW=instagram`, with an Instagram User token on `graph.instagram.com`. Follow the corrected setup guide above for the live pilot. Unified Login account subscriptions use the Instagram account ID, not the system user returned by `/me`.

## 1. Create the accounts and Meta app

1. Create a dedicated Instagram account for Revero and switch it to a professional account (Business or Creator). Keep your personal account as the sender.
2. In [Meta for Developers](https://developers.facebook.com/apps/), create an app and select the Instagram use case that supports messaging with **Instagram Login**. Dashboard wording may vary. Use the setup for a professional Instagram account on `graph.instagram.com`.
3. Connect the Revero professional account and authorize `instagram_business_basic` and `instagram_business_manage_messages`. Generate an Instagram user access token using the dashboard's Instagram setup flow. Record the connected professional account ID and API version. Start with the dashboard's test/development setup for the pilot and configure the required app roles for test accounts. Check current Instagram Login delivery/access requirements before real testing; dashboard test success alone does not establish real DM eligibility. Accept any pending tester invitation before testing.
4. Check that message access for connected tools is enabled in the receiving account if Instagram presents that setting. Send a manual DM from your test sender and check that it reaches the Revero inbox.
5. Keep three credentials in an ignored local environment file. The **app secret** validates POST signatures, the **verify token** is a random string you choose for the GET handshake, and the **Instagram access token** authorizes calls on behalf of the professional account. Also configure the account ID and API version. Put names and placeholders in the example environment file. Generate the verify token locally with `openssl rand -hex 32`. For the personal pilot, enroll the test sender locally by its Instagram-scoped ID before enabling automatic replies.

[Instagram Login reference](https://www.postman.com/meta/instagram/folder/1z5vxzu/instagram-api-with-instagram-login) · [Meta app access and webhook testing](https://developers.facebook.com/docs/graph-api/webhooks/)

## 2. Implement and test the local webhook

Have Codex implement this section before trying to verify the callback in Meta. Use a minimal FastAPI entry point on `127.0.0.1:8001` that serves the webhook and shares the app's existing SQLite storage. Keep the private inbox API and frontend on their local ports.

- **GET /webhooks/instagram** reads `hub.mode`, `hub.verify_token`, and `hub.challenge`. Return HTTP 200 with the raw challenge as plain text when the mode is `subscribe` and the token matches. Reject incorrect tokens.
- **POST /webhooks/instagram** computes HMAC-SHA256 over the exact request bytes using the Meta app secret and compares it in constant time against `X-Hub-Signature-256` in `sha256=<hex>` format. Reject invalid or missing signatures before processing JSON. Set a request size limit. Handle batched entries and ignore echo events and unsupported message types.
- Parse Instagram message events and `ig_reel` attachments. Save the message ID, receiving account, sender ID, and provider Reel identity and reference when present. Prefer the documented Reel identifier for deduplication. Keep a provider reference separate from any verified canonical permalink. Allow a record with a provider ID even when the attachment URL isn't shaped like an Instagram permalink.
- Save the inbound record, Reel, and acknowledgment job in one SQLite transaction. Deduplicate incoming messages using the receiving account ID plus message ID. Deduplicate Reels within the user's inbox by provider ID or a verified canonical Reel URL. Return HTTP 200 after the transaction commits. The worker handles outgoing DMs and later media processing outside the request.
- Scope the pilot to the configured account and test sender. Use sanitized fixtures and log event type, processing outcome and counts. Keep access tokens, full message bodies and attachment URLs out of logs.

Test the GET handler locally with a dummy verify token and challenge. Test the POST handler with programmatically signed fixtures using a dummy app secret. Verify that one signed share produces one saved item and one reply job, that replay produces neither twice, and that invalid signatures and echo events create no records.

[Meta webhook verification and signatures](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/) · [Meta Instagram Reel attachment format](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/changelog/)

## 3. Connect your callback to Meta

1. Install `cloudflared` using Cloudflare's instructions. With the webhook service running locally on port 8001, run:

   ```sh
   cloudflared tunnel --url http://127.0.0.1:8001
   ```

2. Copy the printed HTTPS base URL and append `/webhooks/instagram`. Enter that callback URL and your chosen verify token in the Instagram webhook setup in the Meta app dashboard, then choose **Verify and save**. Keep the tunnel running. A new Quick Tunnel generates a new hostname, so update and re-verify the callback after a restart.
3. Subscribe to the **messages** field in the app's webhook configuration. Also confirm that the connected Instagram professional account is subscribed to the app for that field. Use the account subscription control in the dashboard where available. If the dashboard requires an API call, use the Instagram Login **subscribed_apps** operation on `graph.instagram.com` with your Instagram access token and `subscribed_fields=messages`. Follow the current Instagram Login reference for the account identifier and version. Check the listed fields after subscribing.
4. Trigger a dashboard webhook test to check delivery. Then send a real text DM and share a real Reel from the test sender using Instagram's share sheet. A dashboard test checks connectivity. The real share establishes the payload your app needs to parse.
5. For the acknowledgment worker, use Instagram's Send API for the connected professional account with the inbound sender's Instagram-scoped ID as the recipient. Send within the standard reply window. A replay must reuse the existing job. Track a timeout after a possibly accepted send as uncertain before retrying.

Quick Tunnel is a development option. Keep it pointed at the webhook-only service. Your Mac, server, and tunnel need to be running while testing.

[Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) · [Meta Instagram Messaging](https://developers.facebook.com/documentation/business-messaging/instagram-messaging) · [Meta's Instagram API collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)

## 4. Verify the live pilot and investigate media access

| Symptom | Check |
|---|---|
| Meta cannot verify the callback | Check the current tunnel URL, exact path, matching verify token, and plain-text challenge response. |
| Dashboard test arrives but real DMs are missing | Check both levels of subscription, account connection, messaging scope, app mode, tester roles, pending invitations, and connected-tool message access. |
| Real DM arrives but no Reel is saved | Inspect the attachment type and field names with a redacted payload. Confirm the sender is enrolled. |
| Reel saves but no reply arrives | Check the acknowledgment job, token and account IDs, sender's scoped ID, and Meta's returned error. |
| Reel saves but can't be analyzed | Classify what arrived as usable video, caption only, or reference only. Keep the saved record and offer a local upload or caption fallback. |

Sample 10–20 real shares. Count how many provide playable video through the authorized integration. A webhook attachment URL may only identify the share. Build full Gemini walkthroughs only on readable clips. Preserve timestamps and unreadable values in searchable walkthrough segments. Test one DaVinci Resolve tutorial by following the extracted steps, then use the short takeaway in the existing digest plan.

## Codex CLI prompt

```text
Read project.md and instagram-webhook-plan.md. Inspect the current
workspace and implement the Instagram-first change for me, starting
with the local webhook milestone. Keep any existing manual URL intake
as a fallback and reuse the current schema and save logic where possible.
If no app exists yet, scaffold the smallest FastAPI and SQLite base
needed for this milestone. Edit files, run tests, and fix failures.

Implement the webhook-only FastAPI entry point, challenge verification,
raw-body signature validation, signed fixture tests, idempotent Reel
intake, and a durable acknowledgment job. Use a mocked Send API for
local verification. Add example config and exact startup commands.
Keep real credentials local and out of logs and commits. Update
project.md to make Instagram DM intake the first milestone and make
timestamped walkthroughs the full-video extraction target.

Stop after the local tests pass and give me the exact Meta dashboard
steps and config values I need to supply locally. Once I confirm setup,
verify the real DM flow with me and report what the sample shares
actually provide. Do not infer playable video from a URL alone. Keep
the build free and defer Gemini, search, actions, and the digest until
the Instagram intake milestone works.
```
