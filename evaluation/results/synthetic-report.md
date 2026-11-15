# Synthetic evaluation results

**Scope:** authored synthetic samples and deterministic provider output. These results are not real-world AI accuracy or proof of better user relevance.

- Sample: 16 authored cases; 14 have supplied content; 0 real Reels evaluated.
- Initial ready: 13; after retry: 14; link-only entries retained: 2.
- Supplied-input processing coverage: 14/14. Total inbox ready fraction: 14/16.
- Reference evidence checks: 14/14; date-wording checks: 2/2. These compare fixture output against fixture labels, not Gemini output.
- Automatically created deadlines: 0; confirmed dates require explicit user input.

| Ranking on the same 14 ready candidates | Precision@3 | nDCG@3 |
| --- | ---: | ---: |
| Revero | 1.000 | 1.000 |
| Newest first | 0.000 | 0.000 |

Ranked top three: onscreen-text, sqlite-indexes, sqlite-joins.
Newest-first top three: habits, retry-case, blue-clip.

Precision counts grades above zero as relevant. nDCG uses gains `2^grade - 1`, discounted by `log2(position + 1)`, relative to the ideal ordering of this same candidate pool. Grades 0–3 were authored for interests ['backend interviews', 'SQLite']. This toy sample favors those interests and cannot establish real-world ranking improvement.

Duplicate detection, invalid-link rejection, failed extraction recovery, sourced retrieval, unsupported-question decline, and repeated-digest suppression were exercised. No external provider was contacted. The accompanying JSON records individual check outcomes.

Pending: collect 10–20 real Reels, review real provider output, complete seven days of use, and repeat the comparison using your relevance labels.
