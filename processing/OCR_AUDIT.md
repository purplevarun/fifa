# Screenshot OCR audit — 17 October 2026

## Scope and method

Every original from `raw_screenshots/1.png` through `2241.png` was read in numeric
order. All 2,241 files are distinct and readable; filenames and originals were
not changed. The user's confirmed order was used for fixture context.

A baseline RapidOCR pass was followed by a fresh corrected pass, an additional
recheck of all 160 match summaries, and clean imports using only current OCR
evidence, not earlier approvals. Apple Vision independently read all 2,241
originals locally. No images were uploaded. This is an automated evidence audit,
**not a claim that every pixel or field was manually visually verified**.

## Results

| Check | Result |
| --- | ---: |
| Originals extracted | 2,241 / 2,241 |
| Sources yielding imported records | 2,240 |
| OCR execution errors / skipped imports / database errors | 0 / 0 / 0 |
| Missing expected fields, baseline → corrected | 543 → 3 |
| Isolated numeric cells compared with independent OCR | 35,108 |
| Numeric disagreements, baseline → corrected | 6 → 0 |
| Read numeric cells without an isolated second-reader match | 14,296 |
| Cumulative-count comparisons against preceding captures | 448 match, 0 mismatch |
| Unshown leaderboard metrics not compared | 26 |
| Match-coverage warnings | 0 |
| Python tests, including real-image regressions | 193 passed |

Canonical records: 148 matches, 296 team-stat rows, 1,982 player appearances,
2,006 player snapshots, 158 competition snapshots, seven distinct transfers,
and 24 competition events across three seasons. Repeat screenshots do not add
extra match appearances. Sammy Ameobi's repeated signing captures are one
transfer, with separate review evidence retained for both sources.

## Logic corrected

- White-on-dark season-table numbers now receive contrast/scale retries.
  Low-confidence but parseable counts are checked too: several `41` readings
  previously became `4`. Agreeing three-copy/five-copy evidence is required;
  conflicting confident variants prevent replacement.
- Complete profile lines supply age, nationality and all displayed positions,
  avoiding separator contamination and shifted multi-position crops.
- Additional match-header separators are parsed. Tight-crop consensus removes
  background prefixes from Sunderland (1860) and ESTAC Troyes (1896), without
  taking a neighbouring score as part of a club name.
- EFL Championship and UEFA Champions/Europa League competition names are
  supported, including their league/cup classification.
- Trophy-news variants and confirmed promotions are extracted. One-line and
  wrapped article titles have separate body boundaries; repeated identical
  dated headlines no longer lose an otherwise unambiguous award date.
- Goals/assists leaderboards (1877–1882) supply the visible Notts County totals
  and appearances. Surnames resolve against recorded players; unshown metrics
  remain unknown.
- Haaland's dated, immediate outbound-loan email (1943) records the move to Ajax
  and the one-year loan length.
- Identical transfer captures are deduplicated only when player, clubs, terms,
  displayed day/month and supported season context agree. Different seasons or
  terms are not silently merged.

## Exceptions deliberately not guessed

| Screenshot | Evidence and handling |
| --- | --- |
| 203, 270 | Both OCR readers read tackles as `1/-1`. The negative displayed count is retained in evidence; `tackles_lost` remains null rather than being fabricated as zero. |
| 830 | No readable overall rating was recovered for opponent Sam Hoskins. Other performance statistics are imported; overall remains null. |
| 1588 | Seydou Doumbia's accepted pre-contract says he will join when the transfer window opens. It is retained as reference, not imported as an already-completed move. |

The audit intentionally exits nonzero for these exceptions. No-record reference
screens and missing values are not hidden merely to produce a green result.

All 158 cumulative snapshots lack exact observation dates. The 448 matching
count checks use the confirmed screenshot order, not invented dates. Standard
date-based reconciliation therefore still reports unconfirmed cutoffs. Ratings,
off-screen metrics, spelling/diacritic differences and cells without an isolated
independent reading are not claimed to have complete independent verification.

## Saved artifacts

- `processing/data/ocr-audit-corrected.sqlite`: corrected, isolated database.
- `processing/data/ocr-audit-corrected.json`: ordered report for every original.
- `processing/data/ocr-audit-corrected-import.json`: import and integrity results.
- `processing/data/ocr-audit-vision.jsonl`: independent original-image readings.
- `processing/data/ocr-audit-identity-comparison.json`: baseline identity
  comparisons that identified the club-prefix errors, alongside spelling,
  diacritic and merged-token differences.

The existing `processing/data/career.sqlite` was not replaced. The corrected OCR
logic is used by future processing runs. `./run process` deletes the data folder,
including these generated artifacts; retain a copy elsewhere if needed.

See the README's **Full-archive audit** section for the read-only audit command.
