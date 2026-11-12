# AI-Assisted Screenshot Processing

Guide for adding a new batch of career-mode screenshots with an AI assistant.
The goal is not just "run the processor" — it is to review each new screen,
teach the Python code anything it does not already understand, and only then
rebuild.

## 1. Stage and deduplicate the batch

- Extract the archive to a temp folder, e.g. `/tmp/fifa_new_screenshots`.
- Hash every incoming file and compare against `raw_screenshots/`:
  - Exact SHA-256 duplicates: skip them.
  - Near-duplicates (same screen retaken seconds apart): compare OCR token
    sets and file mtimes. Two captures of an identical screen a few seconds
    apart are retakes — keep the first. The same player card in a *different*
    match or with a different rating is not a duplicate.
- Do not trust the filename; trust the image content.

## 2. Merge into `raw_screenshots/`

- Copy the unique screenshots as the next sequential numbers
  (`N.png`, where N = current highest + 1). The pipeline links player
  performance screens to the preceding match-facts screen **by numeric order**,
  so preserve the incoming order exactly.
- Record the incoming→archive number mapping; every later step refers to the
  new numbers.

## 3. Review every new screen

- Build contact sheets (e.g. 20 thumbnails per sheet) and visually inspect all
  of them. Zoom into anything unusual.
- OCR everything once up front and keep the token dump — it doubles as the
  duplicate check and lets you unit-test extractors without re-running OCR.
- Classify each screen against `processing/extraction.py: classify()`:
  `match_facts`, `player_performance`/`goalkeeper_performance`, `squad`,
  `transfer`, `news`, `inbox`, `player_leaderboard`, `competition_result`,
  `knockout_bracket`, `league_table`, `dashboard`/`dashboard_award`, `unknown`.

## 4. Add extraction logic where the pipeline is blind

Check whether the existing extractor already produces records for each new
screen type before writing code. Region coordinates in `detected_fields` are in
1366×768 base space; screenshots at other resolutions are normalized to 0–1.

Patterns that currently exist and how they were added:

- **Sent offers (incoming transfers)** — `extract_transfer`; accepted panel,
  player name, destination/club, wage/fee/contract, row date (day/month only).
- **Received offers (outgoing transfers)** — same function. The sub-tab reads
  `ALL RECEIVED OFFERS`; the completion sentence is
  "X has agreed terms with CLUB and is on his way to meet his new teammates."
  `from_club` is the managed club, `to_club` comes from that sentence, and
  "Free Transfer" parses as fee `0`.
- **Inbox emails** — `extract_inbox` handles: contract acceptance, immediate
  outbound loan, loan-return-both-ways, `[Info] X Sold` (fee + buying club,
  dated = completion), `X Has Left The Club` (dated free move), and
  `[Info] X Leaving` (pre-contract agreement; `effective_on` stays `null`
  because only the announcement is dated). Sentences are matched per-sentence
  so the player's name cannot swallow preceding body text.
- **Squad hub** — `squad` screens yield a `player_snapshot`, STATUS-tab
  `player_jersey` rows, and STATS-tab `player_competition_snapshot` totals.
  Competition labels live in `COMPETITION_LABELS`; add aliases there when a
  new competition appears (e.g. `europeanintlcup`).
- **Club names** — `CLUB_NAMES` in `processing/normalization.py` canonicalizes
  OCR variants and adds proper diacritics (`Nîmes Olympique`, `Göztepe`) or
  capitalization (`RB Leipzig`, `VfB Stuttgart`, `Hertha BSC`). Keep the
  on-screen spelling convention (`Manchester Utd`, `Nott'M Forest`).

Unit-test new paths directly against stored OCR tokens — normalize each token
box by image width/height and call `extract_transfer`/`extract_inbox`
on a `ScreenshotExtractor` created with `__new__` (no OCR engine needed).

## 5. Record owner-confirmed facts in `confirmed_context.json`

Never hard-code facts a screen does not show. Bind them to the image SHA-256:

- `season_ends` — screenshots captured after a season's last match; sets
  `season` + `snapshot_kind="season_end"` on snapshot records.
- `departures` — appends an outgoing `player_transfer` when the owner confirms
  a player left but no screen shows the deal (e.g. Müller → FC Barcelona,
  bound to the sent-offers screenshot showing his Barcelona badge).
- `transfer_interest`, `match_checks`, `opponent_own_goals`,
  `pending_conflicts` — existing sections; see the file for shapes.

Use `null` for dates/fees the screen does not display; explain the inference
in `basis`. Apply without a rebuild via
`python3 -m processing.confirmed_context --apply` (backs up diagnostics first).

## 6. Rebuild and validate

```sh
./run process                                              # full rebuild
python3 -m processing.audit --output processing/data/ocr-audit.json
python3 -W error::ResourceWarning -m unittest discover -s processing/tests -q
npm --prefix frontend test && npm --prefix frontend run lint && npm --prefix frontend run build
```

- A nonzero exit or `import.skipped_sources` entries in
  `processing/data/processing-report.json` mean screenshots still need logic.
- `ignored_sources` with "no supported statistics" is expected for non-stat
  screens (email lists, tactical views); read the list anyway for surprises.
- `./run start` and eyeball the dashboard — new players, transfers, and
  season totals should appear under the right seasons.

## 7. Publish

- Commit source, `confirmed_context.json`, the new `raw_screenshots/*.png`,
  and the regenerated `frontend/public/data/dashboard.json`.
- Push, then verify the GitHub Pages site serves the new `generated_at`
  timestamp and data.
