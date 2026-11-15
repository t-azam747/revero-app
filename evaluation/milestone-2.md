# Milestone 2 content usability sample

Status: sampled and accepted on 2026-11-15. Local database only; titles, links, and source text stay out of this tracked file. No personal content is recorded here.

## Summary

- Sample size: **13 unique real inbound shares** (within the 10–20 target).
- Usable from the link alone (authorized playable video): **0 / 13**. The DM webhook supplies permalinks and provider IDs, not playable media.
- Supplied content: **13 / 13 captions**, sourced from each share's Instagram title/caption field.
- Successful caption-only extractions: **13 / 13** (`ready`).
- Remaining failures: **0**.
- Evidence errors in automated validation: **0** (all caption excerpts are exact substrings, all caption timestamps are null).
- Date candidates preserved verbatim: **6** across the sample; none converted into confirmed deadlines.
- One caption-only sample: all 13 shares.
- One video sample: the authored `evaluation/fixtures/on-screen.mp4` clip, listed separately below because it is not a real Instagram sample.

## Real samples

| Sample | Local identifier | Link alone sufficient? | Caption/clip supplied | Extraction state | Evidence and timestamps checked? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Reel #6 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 2 | Reel #7 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 3 | Reel #8 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 4 | Reel #9 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 5 | Reel #10 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 6 | Reel #11 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 7 | Reel #12 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 8 | Reel #13 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 9 | Reel #14 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 10 | Reel #15 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 11 | Reel #16 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 12 | Reel #17 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |
| 13 | Reel #18 | No | Caption from share title | ready | Yes — exact excerpt; no caption timestamps | Caption-only |

Notes:

- Titles were supplied automatically by Meta's DM share payload; they were not typed in during evaluation.
- All 13 jobs are unique per Reel/content revision. Replays and retries reused the same job IDs.
- Two other local saves remain `needs_content` because they are manual saves with no caption or clip; they are not part of the 13-share sample.

## Authored video check

| Input | Link alone sufficient? | Caption/clip supplied | Extraction state | Evidence and timestamps checked? | Notes |
| --- | --- | --- | --- | --- | --- |
| `evaluation/fixtures/on-screen.mp4` (2 s, H.264) | Not applicable | Authored caption + local clip | ready | Yes — one `video` source at 0.0 s, within the probed duration; result labeled as video input | Authored fixture, not a real Instagram Reel |

The clip is not instructional enough to produce walkthrough steps, so the walkthrough path was exercised by automated synthetic tests rather than this live sample. Real-Reel video quality remains unmeasured because no playable media is available from the DM link.

## Initial failures and recovery

The first live backfill attempt marked 11 jobs `failed` because the batch response schema nested `$defs` under the array items, producing a provider 400 (`reference to undefined schema`). The schema was fixed by hoisting `$defs` to the root, and the same 11 jobs were requeued and retried in place. They reached `ready` without duplicate jobs or Reels. This is direct evidence that a failed real extraction can be corrected and retried without duplicate results.

## Live acceptance checklist

- [x] Billing-disabled Gemini project, key, and available free-tier model configured locally. Live acceptance used `gemini-3.8-flash`; the configured `gemini-3.5-flash` had exhausted its 20-request daily free-tier quota and the provider reported 3.5 as the same limited model.
- [x] A real caption produces a labeled caption-only takeaway with exact excerpts (13/13).
- [x] A real clip produces a video takeaway with checked excerpts/timestamps where supported (authored on-screen clip; `video` source at 0.0 s).
- [x] Both results survive API and worker restart: the 13 real takeaways persisted, and the authored video result persisted in a reopened database.
- [x] An unreadable Reel remains saved with `needs_content` (two manual saves with no supplied content; automated tests also cover this).
- [x] A failed real extraction can be corrected/retried without duplicate results (11 jobs retried in place).
- [x] 10–20 real samples assessed and counts recorded (13).

## Limitations

- Captions are model-derived summaries of Instagram titles, not transcripts of spoken audio or on-screen video.
- Video timestamps are model-reported and were validated only against probed duration; they have not been manually checked against the authored clip frame by frame.
- Caption quality was validated for grounding (exact excerpts) but not manually reviewed for semantic accuracy.
- The free-tier daily request limit is small and model-specific; the queue limits must stay configurable and conservative.
