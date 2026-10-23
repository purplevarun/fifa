# Owner-confirmed follow-up — 22 October 2026

This supersedes the open date/own-goal questions in REBUILD_REVIEW.md and
SCORING_REVIEW.md. Applied locally without a clean rebuild, commit or push.
Original OCR evidence and review history were retained. A backup was saved at
`../fifa-career-mode-backups/2026-10-22-200917-manual-followup/`.

## Applied confirmations

- **908–929:** marked 2018/19 season-end observations, including the selected-player
  profiles. The owner confirmed capture after the final match, with 907 supplying
  league-win context. No exact capture day was invented.
- **1876–1881:** marked 2019/20 season-end observations. Kept their actual scopes:
  League One (1876–1877), League One Play-Offs (1878–1879), and Invitational Cup
  (1880–1881). Goals and assists panels were not merged into League One totals.
- **2494:** removed its one cumulative-assists snapshot. It now records **Racing
  Club's reported interest in Takefusa Kubo**, not a completed transfer. The
  owner-authorised observation date **2021-02-03 is explicitly labelled assumed**;
  no exact article-announcement date was asserted. The article's original text,
  including its incidental assists mention, remains in diagnostic evidence.
- **1208 and 1972:** one opponent own goal each is now confirmed, not assumed.
  Team scores and individual player goal credits were not changed.
- **1500, 1559, 1589 and 2035:** owner accepted the four hat-trick entries; counts
  remain Kubo 2, Nelson 1, Doumbia 1.
- **111:** retained the confirmed 1–1 match score and separate 4–2 shootout.
- **459:** confirmed Carlisle United 1–2 Notts County after 120 minutes: a Notts
  County win. The stored score was already correct; its review warning is cleared.
- **662:** recorded the owner's shootout confirmation. Its numeric scores below
  remain OCR-derived, not extra manually supplied values.

The persistent `confirmed_context.json` binds these facts to image SHA-256
hashes, not reusable filenames. Future imports reapply the context. A fresh
store/import regression test verifies this does not depend on old diagnostics.
Explicit maintenance is idempotent: a second application changed no records.

## Reconciliation after applying context

- **169 matches / 2,253 appearances**, unchanged.
- **158 cumulative comparisons:** 132 fully matched, 26 partial, **0 mismatches**
  and **0 unconfirmed cutoffs**.
- The 26 partial rows are leaderboards missing a counterpart goals/assists metric
  and average rating. All recorded appearance/goal/assist values agree. They do
  not require another date confirmation or fabricated missing values.
- **2 confirmed opponent own goals / 0 assumed own goals**.
- **0 pending manual score conflicts / 0 match-coverage warnings** after the final
  confirmation of screenshot 459.
- Transfer-profile age/position omissions in the earlier report are a separate,
  still-unfixed extractor limitation; no recapture or transcription is requested.

## Fresh targeted scoreboard OCR

All 15 flagged screenshots were re-read using RapidOCR and independently checked
with padded Apple Vision crops. Clock/shootout text was readable with both
engines. Vision still skips or garbles some isolated score digits; repeated
identical digits are compared without interpreting `222` as 222 goals. Therefore
this is not a claim of independent agreement on every score cell or manual visual
verification. RapidOCR reproduced all saved score values; no new score correction
was supported. The extra-time parser now recognises spaced `1 20:00 ET` as 120 minutes.

Scores below are home–away, separate from shootout scores.

| Screenshot | Match score | Finish / shootout                          |
| ---------- | ----------- | ------------------------------------------ |
| 111        | 1–1         | Penalties 4–2; owner confirmed             |
| 459        | 1–2         | 120:00 ET; owner confirms Notts County won |
| 662        | 0–0         | Penalties 4–3                              |
| 814        | 0–0         | 90:00                                      |
| 860        | 0–0         | 90:00                                      |
| 1028       | 0–0         | 90:00                                      |
| 1043       | 2–2         | Penalties 3–2                              |
| 1222       | 0–0         | 90:00                                      |
| 1296       | 1–1         | Penalties 5–3                              |
| 1309       | 0–0         | 90:00                                      |
| 1662       | 0–0         | 90:00                                      |
| 1722       | 0–0         | 90:00                                      |
| 2199       | 1–1         | Penalties 3–1                              |
| 2285       | 1–1         | Penalties 2–0                              |
| 2496       | 0–0         | Penalties 1–2                              |

### Resolved: screenshot 459

Both fresh readers return **Carlisle United 1–2 Notts County, 120:00 ET**.
The owner has now confirmed this final score and Notts County's win. The earlier
1–1 review note caused the clarification request; the stored result was never
changed to a draw. The conflict is resolved, and [459.png](../raw_screenshots/459.png)
needs no further score review. No player goal credits were changed.

Detailed OCR results: `processing/data/scoreboard-followup.json` (generated and
removed by the next `./run process`). The retry command is documented in README.md.

## Checks

Python tests, frontend unit tests, lint, build, real-data rendering and export
consistency checks passed. Browser automation remains unavailable under the
previously reported Chrome administrator policy. The local dashboard receives
the updated export automatically; publication requires a separate commit/push.
