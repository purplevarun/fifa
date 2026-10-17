# Screenshot OCR audit — 17 October 2026

> Follow-up: [Dashboard and screenshot review](DASHBOARD_REVIEW.md) found malformed
> profile text, seven split club identities, and omitted transfer-profile fields.
> The numeric checks below passed, but do not establish complete data correctness.

## Scope and method

Every current original from `raw_screenshots/1.png` through `2240.png` was read
in numeric order. All 2,240 files are distinct and readable. At the user's request,
original screenshot 830 (opponent Sam Hoskins) was removed, and originals
831–2241 became 830–2240. All retained image contents and the confirmed order
were preserved; the numbering has no gaps.

The OCR corrections and screenshot changes were committed locally as `3985b64`
before a fresh `./run process`. This clean RapidOCR rebuild completed at
**2026-10-17 14:52:06 UTC**, replacing `processing/data/career.sqlite` and
regenerating the dashboard export. It used fresh extraction, not saved approvals.
The separate full-archive audit completed at **2026-10-17 14:52:37 UTC**.

Apple Vision independently read the original 2,241-image archive during the
earlier audit. Those local readings were reused, not regenerated: the excluded
image was omitted, paths were renumbered, and all 2,240 retained image hashes
were verified against the independent evidence before this audit. No images
were uploaded. This is an automated evidence audit, **not a claim that every
pixel or field was manually visually verified**.

## Results

| Check | Result |
| --- | ---: |
| Originals extracted | 2,240 / 2,240 |
| Sources yielding imported records | 2,240 / 2,240 |
| OCR execution errors / skipped imports / database errors | 0 / 0 / 0 |
| Source issues / expected-field issues | 0 / 0 |
| Numeric fields read | 49,382 |
| Isolated numeric cells compared with independent OCR | 35,090 |
| Independent numeric disagreements | 0 |
| Read numeric cells without an isolated second-reader match | 14,292 |
| Cumulative-count comparisons against preceding captures | 448 match, 0 mismatch |
| Unshown leaderboard metrics not compared | 26 |
| Match-coverage warnings | 0 |
| Processing/export exit status / audit exit status | 0 / 0 |
| Python tests, including real-image regressions | 196 passed |

Canonical records: 148 matches, 296 team-stat rows, 1,981 player appearances,
2,006 player snapshots, 158 competition snapshots, eight distinct transfers,
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
  background prefixes from Sunderland (1859) and ESTAC Troyes (1895), without
  taking a neighbouring score as part of a club name.
- EFL Championship and UEFA Champions/Europa League competition names are
  supported, including their league/cup classification.
- Trophy-news variants and confirmed promotions are extracted. One-line and
  wrapped article titles have separate body boundaries; repeated identical
  dated headlines no longer lose an otherwise unambiguous award date.
- Goals/assists leaderboards (1876–1881) supply the visible Notts County totals
  and appearances. Surnames resolve against recorded players; unshown metrics
  remain unknown.
- Haaland's dated, immediate outbound-loan email (1942) records the move to Ajax
  and the one-year loan length.
- Identical transfer captures are deduplicated only when player, clubs, terms,
  displayed day/month and supported season context agree. Different seasons or
  terms are not silently merged.

Screenshot references above use the current, renumbered archive.

## User-confirmed corrections applied

| Screenshot | Evidence and handling |
| --- | --- |
| 203, 270 | Both now store `tackles_won = 1` and `tackles_lost = 1`, using the confirmed absolute-value rule. The displayed negative values and normalization basis remain in evidence. Displayed percentages are checked against the original counts, not rewritten. |
| Original 830 | Removed from the active archive and retained as `removed-830.png` in the corrections backup. Sam Hoskins is absent from the rebuilt player data. Current `830.png` is original `831.png` and must not be removed again. |
| Original 1588, now 1587 | Seydou Doumbia is imported as a completed permanent transfer from Sporting Cp to Notts County. Accepted contract-panel transfers, including pre-contracts, follow the user's confirmed archive rule. The capture date is not treated as a known completion date. |

These corrections were checked in the freshly rebuilt database, not only in
extraction candidates. The earlier three missing-field exceptions are resolved.

## Remaining verification limits

The successful audit exit does not certify complete visual accuracy. **14,292
numeric fields still lack an isolated independent match**; they are unverified,
not necessarily incorrect. Agreement between two OCR readers is not proof either.

All 158 cumulative snapshots still lack exact observation dates. The 448 matching
count checks use the confirmed screenshot order, not invented dates. Standard
date-based reconciliation therefore still reports unconfirmed cutoffs. Ratings,
off-screen metrics, spelling/diacritic differences and cells without an isolated
independent reading are not claimed to have complete independent verification.

## Saved artifacts

- `processing/data/career.sqlite`: freshly rebuilt active database.
- `frontend/public/data/dashboard.json`: export from the same completed run.
- `processing/data/ocr-audit.json`: fresh ordered report for every retained image,
  including independent numeric comparisons, coverage, and reconciliation.
- `../fifa-career-mode-backups/2026-10-17-200054-rerun/`: external pre-rerun database,
  dashboard, and Markdown backups; new processing/test logs and exit statuses;
  independent-evidence hash verification; audit summary and a copy of the fresh
  `ocr-audit.json` report.
- `../fifa-career-mode-backups/2026-10-17-corrections/`: earlier audit databases and
  reports, original independent readings, `independent-renumbered.jsonl`, the
  removed screenshot, and the hash-checked `renumbering.json` mapping.

Paths above are relative to the repository root. The sibling backup folders
survive a rebuild and are not part of the Git commit.

`./run process` deletes the data folder and refreshes the database/dashboard;
it does not automatically run the audit or update this maintained Markdown
summary. The README's **Full-archive audit** section describes the separate
read-only audit command. Preserve reports outside `processing/data/` before
the next rebuild.
