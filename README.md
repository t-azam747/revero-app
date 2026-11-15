# Revero

A local-first, single-user workspace for the Reels you save: share a Reel to a dedicated Instagram account, get a durable **Saved** reply, and keep a searchable library of sourced takeaways, timestamped walkthroughs, trackable actions, and a nightly Telegram digest. Built to run on your own machine with no paid services.

> **Status:** v1 is feature-complete locally and verified on 2026-11-15 (129 backend tests, 11 browser tests, production build). Live Instagram intake and caption extraction are accepted on 13 real shares. Live Ask is accepted for cited answers and no-match retrieval, and live Telegram delivery is accepted for manual and scheduled digests. Real-Reel video analysis remains unmeasured; the unsupported-question decline path and delivery uncertainty are covered by automated tests only. The DM webhook supplies permalinks, not playable media.

## Features

- **Instagram DM intake** — signed webhook, exact raw-body HMAC verification, replay deduplication, atomic intake, and a durable `Saved` outbox with retry and uncertainty handling.
- **Sourced takeaways** — Gemini structured output validated locally with Pydantic: summary, topics, actionable suggestions, verbatim date mentions, source excerpts, and uncertainties.
- **Timestamped walkthroughs** — ordered steps with start/end seconds, spoken text, on-screen text, and validated duration bounds for instructional videos.
- **Automatic caption jobs** — titled DM shares are queued as caption-only jobs, backfilled on worker start, cached by content revision, batched, and drained under a persistent free-tier token bucket.
- **Track actions** — turn a suggestion into an action, confirm or correct a due date, and mark it done or dismissed. Evidence is snapshotted.
- **Ask your saves** — SQLite FTS5 retrieval with evidence-bound Gemini answers and validated citation IDs. Unsupported questions return a clear no-match response.
- **Nightly digest** — deterministic ranking, confirmed deadlines independent of ranking, pending-content count, and Telegram delivery with duplicate/uncertainty controls.
- **Manual fallback** — paste a Reel URL or attach a caption/clip when the link alone provides no readable content. Revero never scrapes Instagram or treats embed HTML as a transcript.

## Architecture

```mermaid
flowchart LR
    I["Instagram DM"] --> H["Webhook service<br/>localhost:8001"]
    H --> DB[("SQLite + FTS5")]
    W1["Instagram reply worker"] --> DB
    W1 --> IG["Saved reply"]
    UI["React workspace<br/>localhost:5173"] -->|"/api via Vite proxy"| API["FastAPI<br/>localhost:8000"]
    API <--> DB
    W2["Extraction + scheduler worker"] <--> DB
    API --> AI["Gemini free-tier project"]
    W2 --> AI
    W2 --> TG["Private Telegram chat"]
```

All services bind to localhost. Only the webhook service is exposed to Meta, through an HTTPS tunnel. Provider keys stay in the ignored root `.env`; the database, uploads, local reports, and demo artifacts are excluded from Git.

## Tech stack

| Layer | Choice |
| --- | --- |
| Web | React 19 + Vite 6 |
| API | FastAPI + Uvicorn |
| Storage/search | SQLite + FTS5 |
| AI | Google Gemini free tier, billing disabled (HTTP, no SDK) |
| Jobs | SQLite job table, Python worker, timezone-aware scheduler |
| Delivery | Telegram Bot API |
| Tests | pytest, Playwright |

## Quick start

Prerequisites: Python 3.14, Node 22, and `ffmpeg`/`ffprobe` on your `PATH`.

```sh
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm install --prefix frontend
```

Create the ignored environment file from the placeholder example, then fill in only what you need:

```sh
cp .env.example .env
chmod 600 .env
```

Run each service in its own terminal from the repository root:

```sh
# Private workspace API
backend/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# Web workspace: http://127.0.0.1:5173
npm run dev --prefix frontend

# Webhook-only service (expose only this port through your tunnel)
backend/.venv/bin/python -m uvicorn app.instagram_webhook:app --app-dir backend --host 127.0.0.1 --port 8001

# Extraction + nightly digest scheduler
PYTHONPATH=backend backend/.venv/bin/python -m app.worker

# Instagram Saved replies only (enabled after configuring a test sender)
PYTHONPATH=backend backend/.venv/bin/python -m app.instagram_worker
```

All services default to `backend/data/revero.sqlite3`. Set the same absolute `REVERO_DB_PATH` in every terminal to use another database. See [Instagram intake setup](docs/instagram-intake.md) for Meta app configuration, tunneling, and acceptance steps.

## Configuration

Copy `.env.example` to `.env`; never commit real values.

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Google AI Studio key for a billing-disabled project |
| `GEMINI_MODEL` | An available model that supports structured output and video |
| `GEMINI_FREE_TIER_CONFIRMED` | Local safeguard; set `true` only after confirming billing is disabled |
| `GEMINI_RPM`, `GEMINI_RPD` | Persistent token-bucket minute and day limits |
| `GEMINI_BATCH_SIZE` | Caption jobs per model request |
| `GEMINI_MAX_ATTEMPTS` | Retry attempts before a job is marked failed |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Private bot delivery |
| `INSTAGRAM_APP_SECRET`, `INSTAGRAM_VERIFY_TOKEN` | Webhook signature and handshake |
| `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_SENDER_ID` | Receiving account and enrolled test sender |
| `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_API_VERSION` | Send API credentials |
| `INSTAGRAM_REPLIES_ENABLED` | Enables the Saved reply worker |
| `INSTAGRAM_LOGIN_FLOW` | `unified` for `graph.facebook.com` or `instagram` for `graph.instagram.com` |

## How it works

1. **Intake** verifies the webhook signature before parsing bounded JSON, scopes events to the receiving account and enrolled sender, and commits the inbound message, saved reference, and outbox row atomically.
2. **Queueing** creates a deduplicated caption job from a share title. A worker-start backfill covers shares that arrived before processing was configured.
3. **Processing** claims jobs under a lease, consumes tokens from the persisted free-tier bucket, batches caption-only jobs, and sends inline video for single jobs. Temp files are deleted after each provider call.
4. **Validation** rejects invented caption excerpts, caption timestamps, invalid source indices, out-of-range video timestamps, and date wording that is not in the source. Relative dates are preserved verbatim; no deadline is inferred.
5. **Retry** uses exponential backoff with jitter, honors `Retry-After`, briefly circuit-breaks the queue on 429s, and falls back to isolated calls when a batch result is misordered or invalid.
6. **Use** the workspace to inspect evidence, track actions, ask questions against indexed excerpts, and preview or send the digest.

## API

| Area | Endpoints |
| --- | --- |
| Reels | `POST /api/reels`, `GET /api/reels` |
| Content | `GET/POST /api/reels/{id}/content`, `POST /api/reels/{id}/retry`, `POST /api/reels/{id}/process` |
| Config | `GET /api/processing` |
| Actions | `POST /api/actions`, `GET /api/actions`, `PATCH /api/actions/{id}` |
| Search/Ask | `GET /api/search?q=...`, `POST /api/ask` |
| Digest | `GET /api/digest`, `PUT /api/digest/preferences`, `POST /api/digest/send`, `POST /api/digest/YYYY-MM-DD/resolve` |
| Webhook | `GET/POST /webhooks/instagram` (separate service on port 8001) |

Interactive API docs are available at `http://127.0.0.1:8000/docs` while the private API runs.

## Testing

```sh
backend/.venv/bin/python -m pytest backend/tests -q

cd frontend
npx playwright install chromium
npx playwright test
npm run build
```

Backend tests use temporary databases and injected providers; browser tests use an ignored database on API port 8002 and never call real providers. The suite covers intake signatures and replays, extraction and validation, batching and rate limits, retry/lease recovery, actions, search, digest scheduling, delivery uncertainty, migration, and cleanup.

## Data, privacy, and security

- Captions and clips are sent to Google when processing starts. Free-tier inputs may be used by Google to improve its products. Videos are sent inline; no Files API upload is used.
- Provider keys and tokens live only in the ignored `.env`. The SQLite database, uploads, local evaluation reports, and demo artifacts are also ignored.
- The webhook service verifies the exact raw-body HMAC signature and should be the only service exposed through a tunnel.
- Revero does not download Instagram media or bypass login/DRM gates. Full video analysis requires a user-supplied clip.
- Logs avoid provider payloads and credentials; Telegram request tracing is suppressed for credential-bearing URLs.

## Project structure

```text
backend/
  app/            FastAPI apps, intake, extraction, actions, search, digest, workers
  tests/          pytest suite and fixtures
  data/           ignored local SQLite database
frontend/
  src/            React workspace
  tests/          Playwright end-to-end tests
evaluation/       synthetic benchmark, fixtures, and milestone-2 sample record
docs/             setup, evaluation, and demo guides
project.md        product scope and working order
```

## Status and limitations

- Live Instagram intake and Saved replies: accepted on 13 real shares.
- Live caption extraction: 13/13 real shares produced validated caption-only takeaways that survived a restart.
- Link-only Reel media: 0/13 accessible through the DM webhook; uploads remain the full-video path.
- Live video extraction: accepted with an authored clip; real-Reel video quality is still unmeasured.
- Live Ask: two real questions returned cited answers whose source IDs matched supplied excerpts; an unrelated question returned no-match with zero sources and no provider call. The decline-with-evidence case could not be run because the free-tier daily quota was exhausted and remains automated-test-only.
- Live Telegram: a manual digest delivered in one part, replaying the same request sent nothing new, a scheduled digest delivered once, and a worker restart did not resend. Uncertainty and crash recovery remain automated-test-only.
- Actions, digest ranking, and delivery edge cases: covered by automated/browser tests.
- Free-tier quota is small and model-specific (20 requests per day per model in observed runs). If the configured model is exhausted, select another available model in `.env` and keep the queue limits conservative. An exported `GEMINI_MODEL` in the shell overrides `.env`, so unset it before starting services.
- Retrieval is lexical (FTS5), not semantic. Live model output should be checked against cited excerpts.

## Documentation

- [Instagram intake setup and acceptance](docs/instagram-intake.md)
- [Evaluation guide](docs/evaluation.md)
- [Demo recording guide](docs/demo.md)
- [Milestone 2 real-sample record](evaluation/milestone-2.md)
- [Product scope and milestones](project.md)

## License

MIT. See [LICENSE](LICENSE).
