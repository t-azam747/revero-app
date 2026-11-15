# Two-minute Revero demo

The generated recording is an **offline demonstration** of the actual web UI and local APIs using authored content, a deterministic AI stand-in, and a fake Telegram sender. A persistent banner and narration disclose this. No Instagram content, private inbox data, real model output, or real Telegram delivery is claimed.

## Reproduce the recording

Requirements: installed project dependencies, Playwright Chromium, local `ffmpeg`/`ffprobe`, and macOS `say` with the Samantha voice for offline narration. The recording tools use no paid service or API key. Normal app setup is in the README.

First preflight the six scenes:

```sh
cd frontend
node scripts/record-demo.mjs --smoke
```

Record and encode the narrated 120-second video:

```sh
node scripts/record-demo.mjs
```

The script starts temporary API/Vite processes on available localhost ports with an isolated temporary SQLite database and provider credentials explicitly disabled. It opens the real React app, performs the six scenes, records Chromium video, creates narration locally, and encodes an MP4 with subtitles. Its temporary processes/database are cleaned up afterward. It does not start the production worker or modify the personal inbox. Test-provider injection exists only in this separate demo app; no production environment flag enables fake answers.

Generated artifacts are ignored by Git and available locally:

- `artifacts/revero-demo.mp4`: narrated 120-second video with a selectable subtitle track.
- `artifacts/revero-demo.srt`: subtitle text.
- `artifacts/demo-manifest.json`: disclosure, chapter timings, and narration.
- `artifacts/demo-verification.json`: measured video/audio/subtitle durations and audio level.
- `artifacts/demo-evidence.png`, `demo-question.png`, `demo-digest.png`: inspected representative frames.
- `artifacts/demo-server.log`: temporary server diagnostics, with no real credentials in the process configuration.

The checked-in authored on-screen clip can be inspected at `evaluation/fixtures/on-screen.mp4`. Neither it nor the blue clip is a real Instagram sample.

## Recording chapters

| Time | Scene | What the viewer can verify |
| --- | --- | --- |
| 0:00–0:20 | Save a Reel | A canonical link appears in the inbox |
| 0:20–0:40 | Duplicate and invalid links | Same record reused; invalid input rejected |
| 0:40–1:00 | Caption, evidence, Track this | Job state, source excerpt, persisted action |
| 1:00–1:20 | Confirm a date and complete another action | User-selected due date and active-list filtering |
| 1:20–1:40 | Ask saved Reels | Supporting excerpts and explicit unsupported-question reply |
| 1:40–2:00 | Digest | Ranked picks, score reasons, deadlines, and simulated send status |

## Record the live portfolio version later

After the real acceptance checks and week of use, repeat the same scenes with public-safe content in the normal app. Use a Reel with an actual caption/clip and verify its generated takeaway before recording. Include an older save for retrieval, manually confirm the action date, and use your configured private Telegram chat. Manual demo delivery has its own request identity and does not consume the scheduled delivery for the day. Do not show `.env`, tokens, personal links, or unrelated messages in the recording.

Describe limitations candidly: link-only shares may need supplied content, free-tier processing can defer, citation-ID validation is not independent factual verification, and scheduling requires the computer and worker to remain available. Keep measured real evaluation results separate from the authored benchmark.
