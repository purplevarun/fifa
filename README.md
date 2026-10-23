# FIFA Career Stats

A local React dashboard and Python screenshot processor. No cloud service,
authentication, sync, or `.env` configuration is needed.

```text
raw_screenshots/             Put all original screenshots here
processing/                 Python OCR, in-memory records, and validation
processing/data/diagnostics.json  OCR evidence and review records (generated)
processing/data/processing-report.json  Latest processing result (generated)
frontend/                   Vite/React dashboard
frontend/public/data/dashboard.json  Published UI dataset (versioned)
run                         Commands below
```

The launcher has three commands: `./run start`, `./run process`, and `./run format`.
`./run process` accepts no flags or other arguments and always rebuilds from scratch.

## Setup

Use Python 3.11+ and Node 22.12+ (or Node 24).

```sh
python3 -m pip install -r processing/requirements.txt
npm --prefix frontend ci
```

## Format Code

```sh
./run format
```

This formats frontend files in place with Prettier, using the existing
`frontend/.prettierrc` tab settings and `frontend/.gitignore` exclusions. It then
formats Python source and tests under `processing/` with Ruff. Generated
`processing/data/` contents, frontend build output, test results, and dependencies
are excluded. Formatting does not process screenshots or reset generated data.

The command accepts no arguments and works from any working directory. Ruff is
pinned in `processing/requirements.txt`; the setup commands above install both
formatters.

## Open the Dashboard

```sh
./run start
```

Open http://127.0.0.1:5000. If port 5000 is already in use, startup stops instead
of silently choosing another port. Both local development and production read
`data/dashboard.json`, generated at `frontend/public/data/dashboard.json` by
`./run process`. No Python process or database is needed to serve the dashboard
once that JSON exists. Processing and maintenance also use Python records and
JSON only; there is no SQLite dependency or database-serving API.

The local dashboard checks the JSON every three seconds, using HTTP ETags to
avoid downloading unchanged data when supported. A successful processing run
atomically replaces the export; the open page then loads the new dataset without
a dev-server restart or manual reload. While processing runs, or if it fails,
the last successful export remains visible. Deleting `processing/data/` does not
remove the published JSON, although it still deletes the diagnostics, backups, and
saved corrections in that folder.

If `dashboard.json` is missing, the page asks you to run `./run process`; local
development automatically loads the file once it appears. Production builds
include a copy in `dist/data/dashboard.json` and load it on page open or when
**Reload exported data** is selected. Rebuild and redeploy to publish a new export
to a static host.

The homepage identifies `dashboard.json` and shows **Last processed** from the
processing metadata in that export, in your local timezone. This time does not
change when the page reloads. Older exports without run history show **Last OCR
saved** instead; this is the timestamp of their last saved extraction, not a
claimed command-completion time. Skipped sources and OCR errors from a recorded
run are displayed separately.

## Overview Rankings

The overview shows the top five Notts County players for goals, assists,
appearances, completed passes, tackles won, and average match rating. All six
rankings follow the season, competition, and preseason filters. Ratings average
only recorded match ratings, not player overall ratings. Passing totals require
all three distance components for each counted appearance. Unknown measurements
are excluded, partial totals are marked, and chart tooltips show record coverage.

### Best Players by Position

The homepage also shows a winner and up to two runners-up for each role, following
all active filters. These are custom stats-based scores, not FIFA overall ratings
or official awards. The cards expose their weights, per-appearance measurements,
coverage and an expandable explanation.

| Role                               | Weights                                                                      |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| Forward (ST, CF, LW, RW, LF, RF)   | 80% goals + 20% assists                                                      |
| Midfielder (CM, CAM, CDM, LM, RM)  | 40% completed passes + 50% key passes + 10% tackles won                      |
| Defender (CB, LB, RB, LWB, RWB)    | 45% tackles won + 45% interceptions/blocks/clearances + 10% completed passes |
| Goalkeeper                         | 50% saves (caught + parried) + 30% clean sheets + 20% fewer goals conceded   |
| Playmaker (all outfield positions) | 50% goals + 50% assists                                                      |

Each component uses the same complete appearances, averages per appearance, and
is scaled against the best eligible average within that role before weighting.
An all-zero component contributes zero. For goals conceded, the scaling factor is
`(1 + lowest average) / (1 + player average)`. Scores are out of 100 but are not
comparable between roles or filter selections. Minutes are not consistently
recorded, so per-90 statistics are not invented.

Eligibility requires five complete appearances in that role (or the number of
selected fixtures if fewer), at least 80% complete records, and a positive score.
Incomplete appearances are excluded rather than filled with zeros, and samples
under five are marked provisional. Ties use more complete appearances, then name.
Recorded match positions take priority; otherwise the first displayed position
is used. Role changes are scored separately, and unknown positions are excluded.
Goalkeeper clean sheets require a recorded zero goals-conceded value, without
claiming that the player completed 90 minutes.

Playmaker is an additional overlapping contribution category, not a new match
position. All recognised outfield appearances qualify, including those by
defenders; goalkeepers and unknown positions do not. A player can feature in
both the playmaker ranking and their usual positional ranking. Outfield
appearances across position changes are combined for playmaker eligibility.

### Recorded Hat-tricks

The homepage includes a count, player totals and an expandable, searchable,
exportable match list. **Career records > Honours & events** uses the same
calculation and active filters for player totals, season totals and match details.
A hat-trick is one unique player/match appearance with **3 or more goals**;
4, 5 or 6 goals still count as one. Braces mean exactly two goals. Extra-time goals
count, but penalty shootouts and cumulative season snapshots do not.

Goal coverage, assumed goalkeeper zeros, missing goal values and incomplete
lineups are explicit. These totals describe captured matches, not proof that every
career fixture was captured. See [the scoring review](processing/SCORING_REVIEW.md)
for the checked screenshots and remaining audit limitations.

## Player Statistics and Honours

On **Players**, choose a season and use **Player statistic** to rank completed
or attempted passes, key passes, interceptions, tackles, crosses, possession,
and other recorded counts. Totals use unique match appearances in the selected
season and competition; the preseason toggle applies too. **Apps recorded**
shows coverage, and missing values stay unknown rather than becoming zero.
Passing totals combine short, medium, and long passes only when all components
are available. Per-recorded-appearance figures exclude missing records.

Each player's **Season totals** tab includes match-derived detailed totals
separately from captured cumulative season snapshots. **Career records >
Honours & events** shows Player of the Month counts by player and season, with
the award month kept separate from its announcement date.

The same page has searchable, exportable **Player of the Year** and **Champions**
tables. Yearly awards list calendar years and named winners, including players
outside Notts County, and remain visible independently of league/season filters.
Champions are listed by competition and season and follow those filters, without
restricting winners to Notts County. Both sections are visible before any awards
have been recorded.

Repeated FIFA sponsor-board logos at the end of news articles are no longer
shown as award descriptions. Older exports are cleaned for display only; their
full records remain inspectable. Future OCR runs clean the parsed article while
retaining the original text and token boxes in diagnostic evidence. Legitimate
FIFA mentions and competition names are not removed.

### OCR Vocabulary

[vocab.json](vocab.json) is the single shared word list for Python processing and
the frontend. It lives outside generated data, so `./run process` does not delete
it. Add known English words or proper-name components to its `words` array;
matching is case-insensitive. Keep `schema_version` at 1. Invalid entries fail
explicitly rather than silently affecting extraction.

News titles and article bodies are repaired before parsing. Existing exported
event descriptions also get display-only repair, so old joined text improves
without rerunning OCR. Examples include `Countyearned` → `County earned`,
`impressiveperformancefor` → `impressive performance for`, and
`EFLChampionship` → `EFL Championship`.

The splitter accepts a token only when **all** its characters form one unique
sequence of vocabulary words. Whole known words take precedence, ambiguous or
unknown tokens stay unchanged, and no partial-prefix guesses are made. A known
possessive followed by joined text can be separated, e.g.
`Kubo'simpressive` → `Kubo's impressive`. Original casing, punctuation and existing
whitespace are preserved. Tokens containing numbers/IDs, hyphenated names and
non-English letters are not split. Tokens longer than 160 characters are skipped.

This is spacing repair, not a spell-checker or an automatic OCR-word learner:
`Aviard` and other misspellings remain unknown until deliberately addressed.
Include legitimate compound words such as `within` to protect them from splitting.
The helper is not applied to numeric stat cells or stored record identifiers;
raw OCR fields, token boxes and old exported records remain untouched.

Vocabulary edits are picked up by the next processing command and by Vite's
normal module reload during development. Rebuild/redeploy the frontend for a
published dashboard to use changes. Python and frontend tests share spacing
fixtures to keep their behaviour aligned.

## Process Screenshots

Put new images into `raw_screenshots/`, then run:

```sh
./run process
```

**Every run deletes the entire `processing/data/` folder first.** This includes
the previous diagnostics, saved corrections, review history, reports, and any
backups inside that folder. No automatic backup is created. The published
`frontend/public/data/dashboard.json` is outside that folder and is retained.

The flow is **screenshots → OCR → normalize, deduplicate and link → validate →
`dashboard.json`**. One Python command does the entire job, using in-memory
records rather than an intermediate database. It inventories all remaining
original screenshots and runs OCR on every distinct image. Previously processed images are processed again;
identical file contents are deduplicated within the new scan. Entity UUIDs and
processing history are regenerated on every run. Original screenshots and source
code are not deleted or rewritten.

After a successful rebuild, Python atomically publishes
`frontend/public/data/dashboard.json`, the sole UI dataset
for both local development and production. This generated JSON file is tracked
in Git for static builds such as GitHub Pages; failed or
partial rebuilds do not overwrite it.

The processor also writes `processing/data/diagnostics.json` (source hashes,
paths, OCR readings, normalized records, aliases, review history, and run metadata)
and `processing/data/processing-report.json` (counts and errors). These are
auxiliary troubleshooting outputs, not inputs to the next full rebuild and not
UI data sources. All relationship, uniqueness, type, and range checks run in
Python. A failed source import rolls back its in-memory changes without losing
other valid sources. Previous diagnostic JSON is never a substitute for fresh OCR.
Explicit owner confirmations in `processing/confirmed_context.json` are reapplied
only to matching image content hashes: season-end cutoffs, captured news purpose,
assumed observation dates and confirmed own goals. A reused filename with different
image content does not inherit those confirmations. Conflicting final scores stay
pending rather than being forced to agree with player totals.

**No flags and no review or approval step are required.** The former `--clean`,
`--reextract`, `--limit`, and `--screenshots` options are rejected before deletion,
as are any other arguments to `./run process`. The command always publishes the
main dashboard; `--db` is retired and `--diagnostics` cannot redirect processing.
Symlinked processing or data
directories are rejected to avoid deleting data outside the intended location.

The open local dashboard automatically detects the replacement JSON and shows
the new run's processing timestamp. It keeps displaying the last successful
export during processing; partial results are not published.

If processing fails, the latest diagnostics and processing report identify the
failed sources while the previous dashboard JSON stays unchanged. An interrupted
run may end before diagnostics are saved. Rerunning `./run process` starts from
the beginning; it does not resume a cache. With no screenshots, a successful run
publishes an empty statistical dataset.

Unreadable single-digit player and team counts get a contrast-normalized,
enlarged-glyph retry.
Three-copy and five-copy readings must agree before a digit is recovered; the
original and retry readings remain in the OCR evidence. Blank or ambiguous cells
stay unknown. Each rebuild uses the current OCR implementation on every image.

Player names are also checked against text detected within their on-screen name
fields. A conflicting name crop is changed only when two tighter crops agree with
the full-image reading and meaningfully improve confidence; all readings are kept.
Repeated, unambiguous corrections from at least two screenshots of the same club
can resolve the same OCR name variant elsewhere in that run. Existing reviewed
identities are not rewritten.

Supported screens include:

- Match/team stats, player performances, selected-player profiles and season totals.
- Visible Notts County goals/assists leaderboard rows, including appearances,
  kept as separate cumulative observations rather than extra match records.
- Completed transfers and loans, weekly wages, contract lengths and loan lengths.
- Dated outbound-loan confirmation emails that explicitly state an immediate move.
- Player of the Month, Player of the Year, player/goalkeeper competition awards, Golden Boot headlines and competition winners, including championship dashboard banners.

EFL Championship and UEFA Champions/Europa League competition names are supported.
Trophy articles with “Win the …” or “… winners” headlines are recognized, as are
confirmed promotion articles. A pre-contract for a future transfer window is not
treated as a completed move.

Offers still in negotiation and award shortlists are not treated as completed
signings or wins. Missing years, selling clubs, fees and competition context stay
unknown unless related screenshot evidence resolves them unambiguously. Contract
offers are not mistaken for transfer fees. News surnames are resolved again at
import time, after earlier player records are available; ambiguous names are rejected.

Undated profiles and season totals use compatible neighboring dated fixtures or
competition tables to establish a season. Conflicting season boundaries are not
guessed, and an exact observation date is never invented. Monthly awards can use
the named player's recorded league appearances in the award month. A Golden Boot
headline can use a same-screen championship and individual award only when their
competition, season, and announcement date agree. Inferred context is retained in
the import history and does not come from a saved-answer file.

Player of the Year is a calendar-year event, not a league-season award. Its year
comes from explicit award text or the article/dashboard date context; its named
winner can be recorded without any team membership, appearance, or competition.
The standard news strip and raised headline text are supported. Names come only
from the news text, never a portrait, training panel, standings, or fixture.
Dashboard calendars do not supply an exact announcement date. Missing award
years and conflicting winners remain unresolved rather than being guessed.

Multiple captures of the same annual award or competition-season championship
share one event. Each screenshot keeps its own OCR and review evidence; repeat
captures do not inflate honour counts. The published schema remains version 4,
including competition-independent annual awards; the dashboard also accepts
older schema-3 exports. Historical database migrations are no longer supported:
rebuild from the original screenshots instead.

Player and goalkeeper screenshots are linked to the preceding match summary in
numeric screenshot order. An unrelated or unrecognized screen breaks that
context, so a player is never automatically attached across it. Goalkeeper
counts that include penalties are separated from the recorded shootout score.

The archive uses consecutive filenames such as `1.png`, `2.png`, and `3.png`.
Append new screenshots with numbers above the current highest number, keeping
each match summary before its player screenshots. Renumbering is safe only when
the existing numeric order is preserved; alphabetical order is not equivalent.

Each source is validated and added in its own in-memory transaction. Missing required
context and conflicting records are reported under
`import.skipped_sources`; they do not block attempts to import other valid
screenshots. OCR failures, unimportable extracted records, and record validation
errors produce a nonzero exit code and an incomplete result, leaving the last
published dashboard unchanged. Non-stat screens with no records are reported separately
under `import.ignored_sources`; they do not make a successful run incomplete.
Their OCR evidence is retained. Recognized statistics screens that yield no records
still require attention and produce a nonzero exit code.
Automatically imported values
are not manually verified, so OCR mistakes that pass validation can still occur.

## OCR Reliability

OCR improvements are implemented in the processor and tested against values
visible in original screenshots. Processing does not load a saved-answer file
to override fresh extraction. Each rebuild starts without earlier manual
corrections or learned aliases, so its results may differ from manually corrected
archives.
Recognition and relationship validation cannot guarantee 100% accuracy for
arbitrary screenshots. Unsupported screens and missing context are reported;
zero coverage warnings does not mean every screenshot yielded a record.

### Full-archive audit

`./run process` rebuilds the dashboard JSON and diagnostics; it does **not** run
the audit automatically. After processing finishes, generate a fresh JSON report
with the separate command below. `processing/OCR_AUDIT.md` is a maintained summary,
not an automatically generated processing output.

```sh
python3 -m processing.audit --output processing/data/ocr-audit.json
```

This is a **read-only check**, not a rebuild. It visits every original path in
numeric order, verifies image hashes against OCR evidence, and reports files
that are new, changed, unextracted, unimported, or produced no records. Identical
files are listed individually even though processing deduplicates their content.
Use `--diagnostics /absolute/path/to/diagnostics.json` to inspect a saved run.
The report's `validation_errors` field contains record-integrity failures.

The report checks every expected on-screen player/team count, percentage
consistency, profile metadata, and competition-row sums against displayed totals.
Leaderboard checks require only the metrics actually shown. The separate
`ordered_snapshot_comparisons` section compares cumulative counts with preceding
match captures, relying on the confirmed chronological order without inventing
an observation date or silently marking an undated snapshot as season-end.
Standard date-based reconciliation still reports unconfirmed cutoffs explicitly.

An optional `--independent /path/to/readings.jsonl` accepts a second local OCR
reader's evidence (`path`, `tokens` with normalized four-point `box`, `text` and
`confidence`, and optional `error`). Numeric comparisons require isolated cells
at matching coordinates. Disagreements, second-reader errors and unmatched
numeric fields are counted separately. Agreement is not proof of correctness.

Season-table recovery handles white text on dark backgrounds as well as dark
text on light backgrounds. Low-confidence numbers, including already-parseable
multi-digit counts, are checked with contrast/scale variants. Three-copy and
five-copy readings must agree; confident conflicting variants prevent a
correction. Profile positions, age and nationality come from the complete
details line so separators and extra positions cannot shift the age crop.
Fixture club names use the same conservative tight-crop consensus as player
names; tokens spanning a neighbouring score are excluded. Original readings and
all retry evidence remain available.

An audit exits nonzero for unresolved source/field issues or numeric disagreements;
it does not rewrite them to make checks pass. The archive owner's confirmed rule
stores the absolute value of negative displayed tackle counts, retaining the
original values and adjustment basis in OCR evidence. Displayed percentages are
checked against the original counts, not silently rewritten after normalization.
Accepted contract-panel transfers, including pre-contracts, are treated as
completed under the owner's confirmed archive rule; exact completion dates are
not invented. Neither successful import nor this automated audit is manual visual
verification. Reports in `processing/data/` are deleted by the next `./run process`;
copy any report or diagnostics JSON outside that folder to retain it.

## Delete Old Screenshots

**Keep the original screenshots for any statistics you want to rebuild.** Deleting
an image does not immediately change the displayed dashboard, but the next
`./run process` rebuilds from only the remaining files. Data supported only by
deleted originals will be lost. Images are identified by content hash, not by
the highest filename number:

- A new image reusing an old filename is processed.
- Identical copied files are processed once per rebuild.
- An empty screenshot folder produces an empty statistical dataset on the next run.
- The website reads `dashboard.json`; it needs neither SQLite nor the original images.

Keep `dashboard.json` to display the published statistics and retain a copy of
`diagnostics.json` outside `processing/data/` if you need its evidence or review
history later. Processing diagnostics are ignored by Git; the published dashboard
JSON is versioned. Processing does not make
another permanent copy of your images or delete the originals automatically.

## Optional Maintenance

Owner confirmations can be applied to the current diagnostics without resetting
the archive using `python3 -m processing.confirmed_context --apply`. Back up the
diagnostics first. This preserves existing entity IDs, records the context changes
in review history, and republishes the dashboard. These versioned confirmations
survive a clean rebuild; ad-hoc review changes saved only in diagnostics do not.

For read-only scoreboard retries, use
`python3 -m processing.recheck_scoreboards --screenshots 111,459,662 --vision --output processing/data/scoreboard-followup.json`.
`--vision` adds independent Apple Vision readings and requires macOS and Swift;
omit it for RapidOCR-only checks. The command never imports or resets data. Its
report, like other generated diagnostics, is deleted by the next full rebuild.

See [the manual follow-up](processing/MANUAL_FOLLOWUP.md) for applied confirmations
and the resolved screenshot 459 score review. Transfer-interest articles are
kept as news events, not completed transfers or cumulative-stat snapshots.

Backups, review tools, and developer checks are available directly through
Python and npm; they are not additional `./run` commands.

`review` and `approve` remain optional maintenance tools for intentional manual
corrections, not requirements for processing. Replacing existing values through
those tools still requires `--replace-reviewed`; those manual changes are lost
on the next full processing run. Store any manual backup **outside**
`processing/data/` if it needs to survive processing.

After manual corrections, publish the reviewed JSON records to the UI without
rerunning OCR (which would discard those corrections):

```sh
python3 -m processing export
```

The local dashboard picks up this export automatically. `approve` and batch
review tools save changes to `diagnostics.json`; they do not update the published
UI until you export. `./run process` already publishes after a successful rebuild.
Maintenance commands can read another saved run with
`python3 -m processing --diagnostics /absolute/path/to/diagnostics.json status`.

```sh
python3 -m processing status
python3 -m processing validate
python3 -m processing backup backups/my-backup.json
python3 -W error::ResourceWarning -m unittest discover -s processing/tests -q
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
npm --prefix frontend run validate:data
npm --prefix frontend run test:e2e
```

Use a new backup filename each time. Git history is not rewritten automatically.
`validate` checks the diagnostic records and confirms the published dashboard
matches them (excluding the export timestamp). A partial failed run or unpublished
manual changes therefore fail this consistency check until resolved.

After building, `validate:data` loads the actual generated dataset into the React
model, checks hat-tricks and positional scores, server-renders the main pages and
honours view, and checks development and production preview JSON responses, ETags,
and missing-file behavior. It needs no browser
automation permissions; Playwright remains the separate interactive UI check.

`npm --prefix frontend run preview` opens a production build locally and reads
its bundled `dist/data/dashboard.json`, with no database endpoint. Rebuild the
frontend after exporting new data to update this production preview. A static
upload to a hosting provider is not part of this local app.

Missing goals scored default to zero for appearances recorded as GK in the
dashboard and reconciliation, with assumed values marked in the data and
verification tooltips. A recorded match position takes precedence over the
displayed position. Existing goal counts are never replaced, and the raw diagnostic
values are retained. Other missing values, including outfield goals, stay
unknown. Shootout scores stay separate from match goals, and cumulative season
totals are not added to match totals.

When the recorded player goal total is lower than the team score, the difference
is treated as **assumed opponent own goals** by the reconciliation logic, without
displaying an assumption notice. Team scores and individual player
credits are never rewritten or assigned to an invented player. Excess player
goal credits still produce a warning, and unknown goal totals stay unknown.
Other warnings identify the fixture and the missing player or team statistics.

Optional real-image OCR regression tests use
`CAREER_OCR_TESTS=1 python3 -W error::ResourceWarning -m unittest discover -s processing/tests -q`
while those original fixtures remain available.
