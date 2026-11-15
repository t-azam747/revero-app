# Evaluation and release evidence

Milestone 6 has two separate evidence tracks: a reproducible synthetic integration benchmark, and a real-content/user-usage study. The former is implemented; the latter needs actual reviewed content and elapsed usage time. Do not label a fixture result as Gemini quality, Instagram accessibility, or user relevance.

## Reproduce the authored benchmark

From the repository root:

```sh
backend/.venv/bin/python -m evaluation.benchmark
```

This uses a temporary SQLite database, authored captions and two small locally generated clips, deterministic extraction/answer fixtures, and a fake Telegram sender. It does not read or modify the personal inbox and makes no external provider calls. It writes:

- `evaluation/results/synthetic-report.json`: machine-readable outcomes and limitations.
- `evaluation/results/synthetic-report.md`: observed sample size, coverage, evidence/date checks, and ranking comparison.
- `evaluation/results/sample-digest.txt`: public-safe example with deliberately synthetic Reel URLs.

The 16 cases include caption-only input, on-screen video text, a blue clip, an old relative date, an explicit date, an initial extraction failure followed by retry, a duplicate tracking variant, unrelated content, and two link-only/inaccessible-share stand-ins. The placeholders do not assert that any real Instagram Reel is available or unavailable.

Relevance grades are 0–3 for the stated interests: 0 irrelevant, 1 tangential, 2 useful, 3 highly useful. Both rankings use the same ready candidate pool. Precision@3 counts grades above zero. nDCG@3 uses gains `2^grade - 1` with `log2(position + 1)` discounts and is normalized to the ideal ordering of that same pool. Empty pools and pools without any relevant candidate have no nDCG value rather than a fabricated zero or perfect score.

The fixture sample intentionally contains older relevant and newer unrelated material. Its improvement over newest-first demonstrates that the scoring path runs; it does not establish real-world improvement. Exact source/date checks compare supplied fixture output against known fixture labels, not an actual model prediction. A successful deterministic retry is not proof that all real videos can be extracted.

## Collect 10–20 real samples

Working copies have been created in ignored `evaluation/local/`:

- `real-review.json`: one entry per unique real saved Reel.
- `week-journal.json`: seven unfilled daily entries.

Templates are tracked as `evaluation/real-review.example.json` and `evaluation/week-journal.example.json`. Keep captions, private links, personal notes, provider credentials, and real screenshots out of the public fixture dataset.

1. Configure the billing-disabled Gemini project and, for delivery checks, your private Telegram bot using the README.
2. Save 10–20 real Reels you are permitted to use. Include caption-only material, an on-screen-text clip, an old relative date, a duplicate share, and a share that cannot be processed without supplied content. Count unique Reels, not repeated submissions.
3. In `evaluation/local/real-review.json`, replace the placeholder ID with the actual `id` shown by `GET /api/reels` in local `/docs`. Duplicate the entry for each sample. Set `input_kind` to `caption`, `video`, or `link_only`.
4. Before inspecting the digest order, state your expected takeaway/date wording and assign the 0–3 relevance grade for the interests at the top of the review file. This reduces hindsight bias.
5. Process each supplied caption/clip in the app. Compare the summary with the actual source; check every excerpt and any timestamp against the clip. Set `takeaway_correct`, `evidence_correct`, and `dates_correct` to true or false only after review; unknown values stay null. `expected_date_mentions: []` means you expect no date mentions; null means you have not reviewed date wording.
6. Judge `link_sufficient` separately. The app intentionally does not download Instagram media or infer a transcript from embed HTML. A successful save does not establish that the link alone supplies usable content. If you have not actually assessed accessibility, leave the field null.
7. Confirm/correct dates in Actions. Relative wording such as “tomorrow” from an old post must not turn into an assumed current deadline. Review this behavior directly; date-wording exact-match scores do not measure due-date reasoning.

Generate a private aggregate report:

```sh
backend/.venv/bin/python -m evaluation.real_review
```

The command opens the personal database read-only, invokes no model or messaging provider, and writes `evaluation/local/real-report.json`. It exports aggregate counts and local IDs, not captions, private links, or credentials. Ready status, manual-content counts, link sufficiency, evidence judgments, date-wording matches, and ranking outcomes have explicit denominators. Unknown judgments are excluded, not counted as failures or successes. Ranking is computed only when every ready sample in the reviewed pool has a relevance label. It covers that selected sample, not all saves.

If there are zero reviewed samples, the report records zero samples and null rates. It never manufactures real-world results from the synthetic fixture run. Copy only genuinely reviewed, privacy-safe aggregate results into the public README when available.

## Seven-day use journal

Fill one entry in `evaluation/local/week-journal.json` after using Revero that day. Record the India-local date, set `used_app: true`, and enter observed counts and notes. Suggested observations:

- New saves, duplicates, manual captions/clips, and links still needing content.
- Useful takeaways, unsupported/invented claims, excerpt/timestamp mistakes, and date errors.
- Supported and unsupported questions, including any false answer rather than a no-match response.
- Whether the chosen digest picks were useful compared with newest-first.
- Whether scheduled delivery happened, whether the computer was awake, and any failed/uncertain send.

Run the private aggregate command again after recording use. Seven placeholders do not count as seven days. Future dates and duplicate dates cannot inflate use counts. The report labels the journal as self-reported and marks seven days recorded only after seven distinct recorded use dates spanning at least seven calendar days. This session cannot substitute for that elapsed use.

## Release checklist

- [x] Reproducible authored fixture dataset and benchmark.
- [x] Shared production ranking function used by both app and evaluator.
- [x] Same-pool comparison with newest-first and explicit metric denominators.
- [x] Public-safe digest sample and architecture/setup documentation.
- [x] Real-review and seven-day journal templates plus read-only aggregation.
- [x] Narrated offline 120-second MP4, subtitles, disclosure manifest, and visual/audio checks.
- [ ] Live caption and video evidence reviewed against real Gemini output.
- [ ] 10–20 unique real Reels labeled and accessibility/coverage recorded.
- [ ] Seven days of real use recorded.
- [ ] Real ranking comparison and date/evidence judgments reported.
- [ ] Live Telegram delivery observed, including the scheduled run.
- [ ] Live two-minute portfolio demo recorded if presenting this as a fully validated live integration.

See `docs/demo.md` for the clearly labeled offline recording and the live recording plan. The generated offline video is a demonstration artifact, not a substitute for the live acceptance checks above.
