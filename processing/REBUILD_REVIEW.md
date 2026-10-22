# Rebuild review — 22 October 2026

Existing changes were committed locally as `d4a7597` before running
`./run process`. The clean rebuild completed successfully at 07:26:17 UTC.
No screenshots or extraction rules were changed during this review.

## Rebuild and verification

| Check | Result |
| --- | ---: |
| Readable, distinct screenshots / extracted / imported | 2,537 / 2,537 / 2,537 |
| Extraction errors / skipped imports / validation errors | 0 / 0 / 0 |
| Sources without records / automated expected-field issues | 0 / 0 |
| Canonical matches / player appearances / players | 169 / 2,253 / 30 |
| Matches with both complete team-stat rows and complete player core fields | 169 |
| Unlinked match-summary or player-performance sources | 0 |
| Match-coverage warnings | 0 |
| Chronological cumulative-count comparisons | 449 match, 0 mismatch, 28 not comparable |
| Standard date-based reconciliation | 159 cutoff unconfirmed, 0 partial comparisons, 0 mismatches |
| Fresh extraction candidates differing from pre-rebuild diagnostics | 0 |

The 28 non-comparable chronological metrics are not displayed in the relevant
leaderboards/news: 26 missing counterpart goal/assist metrics in screenshots
1876–1881, and appearances/goals in 2494. Missing metrics remain unknown, not zero.
The standard reconciliation's zero mismatches does **not** mean its undated rows
were verified: those comparisons are blocked by the unconfirmed cutoffs below.

Python tests: 225 run, 26 skipped, no failures. Frontend tests: 61 passed.
The frontend build and real-data validation passed, including rendering all seven
main pages and checking development/production JSON responses. The build retains
its existing large-bundle warning. Published JSON matches the fresh diagnostics.

## Confirmed partial extraction: transfer profiles

These eight screenshots produce transfer records and retain nationality, but
their readable age and position fields are not saved as profile snapshots.
Fresh OCR evidence contains the following values; the current transfer extractor
uses only nationality from that details line.

| Screenshot (`raw_screenshots/<number>.png`) | Player | Omitted age | Omitted position |
| --- | --- | ---: | --- |
| 977 | Matty James | 27 | CM/CDM |
| 1011 | Tosin Adarabioyo | 21 | CB/RB |
| 1084 | Dominic Calvert-Lewin | 22 | ST/LM |
| 1587 | Seydou Doumbia | 32 | ST |
| 1943, 2033 | Sammy Ameobi | 28 | RM/LM/RW |
| 2032 | Thiago Almada | 19 | CM |
| 2048 | Abdoulaye Dabo | 19 | CM/LM |

This is an extractor limitation, not a failed import or a reason to delete or
recapture these images. It remains unfixed in this reporting-only run and is not
detected by the automated expected-field audit. The two Ameobi captures correctly
represent one transfer.

Exact completion dates, transfer fees and currency codes also remain unknown for
these contract panels; a displayed day/month, wage or `$` is not sufficient.
Selling clubs are unknown except for Doumbia's captured Sporting Cp pre-contract.
Those missing facts can be supplied manually if known, with their evidence.

## Manual help: cumulative-stat cutoffs

All 159 cumulative rows come from these 29 screenshots. Their visible statistics
are imported; the missing information is the exact observation cutoff, not a
broken fixture link. The dashboard labels this **Cutoff unconfirmed**.

| Screenshots | Saved context | Rows | Useful confirmation |
| --- | --- | ---: | --- |
| 908–929 | 2018/19 squad competition/season totals | 132 | Were all captured after the final match of 2018/19? Otherwise, what was the in-game capture date? |
| 1876–1881 | 2019/20 goals/assists leaderboards | 26 | Are these final 2019/20 totals? Otherwise, what date do they cover? |
| 2494 | Kubo's 12 EFL Championship assists, 2020/21 | 1 | What was the in-game date of this article/cumulative observation? |

Chronological agreement uses the already-confirmed screenshot ordering. It does
not establish exact dates or verify average-rating reconciliation. No cutoff was
invented or marked as season-end during this run.

## Existing own-goal assumptions, not new failures

| Match-summary screenshot | Fixture | Reconciliation |
| --- | --- | --- |
| 1208 | Portsmouth–Notts County, 9 October 2019 | Notts team goals 3, player credits 2: one assumed opponent own goal |
| 1972 | Notts County–Rochdale, 11 August 2020 | Notts team goals 3, player credits 2: one assumed opponent own goal |

These follow the existing archive rule and do not raise coverage warnings.
If remembered, confirmation that each contained an opponent own goal would help;
neither a scorer nor a missing appearance has been invented.

## Evidence and limits

- Fresh outputs: `processing/data/processing-report.json`, `diagnostics.json`,
  and `ocr-audit.json`; the dashboard is `frontend/public/data/dashboard.json`.
- Before/after diagnostics, dashboards, audit reports and the processing log are
  preserved outside the rebuild directory at
  `../fifa-career-mode-backups/2026-10-22-rebuild-d4a7597/`, relative to repository root.
- No new independent-OCR pass or exhaustive visual verification was performed.
  This fresh automated audit has 55,892 extracted numeric fields but no supplied
  second-reader comparisons. The independent review in `OCR_AUDIT.md` is historical,
  not a new verification claim for this run.
- Successful processing and consistency checks do not guarantee every text field
  or visible detail was extracted; the transfer-profile omissions above demonstrate
  that distinction. No manual corrections or approvals were applied.
