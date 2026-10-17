# Dashboard and screenshot review — 17 October 2026

## Verdict

**All 2,240 current screenshots were processed, but the extraction is not fully
correct or complete.** The dashboard faithfully displays the saved statistics;
this review found remaining text/identity errors and omitted visible profile data.
The earlier audit's zero detected field issues did not validate country names,
position syntax, club-name identity, or every field visible on transfer screens.

Existing work was committed locally as `eb7b59a` before this review. All screenshot
numbers below refer to the current `1.png`–`2240.png` archive, unless explicitly
labelled original. This was a read-only review: no screenshot or statistic was
removed, merged, corrected, or reprocessed.

## Confirmed extraction issues

### Malformed profile fields

The saved extraction evidence and independent Apple Vision readings support the
following corrections. These values remain incorrect in the current database.

| Screenshot | Player | Saved value | Supported value |
| --- | --- | --- | --- |
| 911 | Frederik Schram | Position `GK I` | `GK` |
| 914 | Leo Ostigard | Nationality `IH Norway` | `Norway` |
| 915 | Scott Cuthbert | Nationality `IX Scotand` | `Scotland` |
| 921 | Nathan Delfouneso | Nationality `IE England` | `England` |
| 925 | Takefusa Kubo | Nationality `ID Japan` | `Japan` |

The profile-line parser includes separator/flag glyphs in country names and can
replace a cleaner initial crop reading with a contaminated full-line reading.
Schram's position crop retains a separator. These are not numeric OCR failures,
so the existing numeric-agreement results do not detect them.

### Seven split club identities

Each pair below has separate club IDs despite identifying the same opponent.
This fragments club identity and makes some fixture labels/searches inconsistent;
it does not create duplicate match appearances in the reviewed export.

| Variants in the database |
| --- |
| `Lincoln City` / `Lincolncity` |
| `Crawley Town` / `Crawleytown` |
| `Swindon Town` / `Swindontown` |
| `Port Vale` / `Portvale` |
| `Grimsby Town` / `Grimsbytown` |
| `Doncaster` / `..Doncaster` |
| `Coventry City` / `Coventrycity` |

The malformed `..Doncaster` fixture label comes from screenshot **1309**
(Doncaster–Notts County, 16 November 2019).

### Visible transfer profile information is omitted

Transfer records are imported, but these screens' nationality, age and position
lines are not used to populate player/profile records. All seven players below
currently have null nationality, despite independently readable source text.
Transfer-panel overall/profile observations also do not produce player snapshots.
For example, Thiago Almada has a completed transfer but no appearance or profile
snapshot, leaving his profile much less complete than the source screenshot.

| Screenshot | Player | Independently read profile information |
| --- | --- | --- |
| 977 | Matty James | CM/CDM; age 27; England |
| 1011 | Tosin Adarabioyo | CB/RB; age 21; England |
| 1084 | Dominic Calvert-Lewin | ST/LM; age 22; England |
| 1587 | Seydou Doumbia | ST; age 32; Ivory Coast |
| 1943, 2033 | Sammy Ameobi | RM/LM/RW; age 28; England |
| 2032 | Thiago Almada | CM; age 19; Argentina |
| 2048 | Abdoulaye Dabo | CM/LM; age 19; France |

Missing completion dates and transfer fees are separate limitations: an accepted
transfer or visible wage does not establish an exact completion date or fee.

## Screenshots involving non-Notts players

- **No additional opponent player-performance capture was found.** All **2,017**
  outfield/goalkeeper performance screenshots say Notts County in their extracted
  club field, and all 2,017 corresponding independent club-region readings agree.
- The **25 squad-profile captures** describe **20 players** who have explicit
  Notts County performance records. Profile ownership is established through
  those player identities and archive context, not an independently visible club
  header: the squad-profile OCR readings do not contain such a header.
- **1393:** the career dashboard includes the 2019 Player of the Year headline
  about **Lionel Messi**. This is a global-award reference, not a player-performance
  capture. It does not contribute Notts County appearances or goals.
- **906:** the selected article is **Aaron Ramsdale's EFL League Two goalkeeper
  award**, while the sidebar says **Zoko wins Golden Boot**. Zoko is retained as
  an award-only reference with no recorded club and no player appearances. Do not
  remove the whole screenshot merely to exclude that sidebar headline; Ramsdale's
  award is relevant Notts County evidence.
- Competition leaderboards, opponent team statistics, and transfer-origin clubs
  naturally mention other players/clubs. That alone does not make them stray
  Notts County player-stat screenshots.
- Original **830** (Sam Hoskins) remains excluded. Current `830.png` is the old
  `831.png`; no further deletion or renumbering was performed.

## Exact pixel duplicates

**No exact full-image pixel duplicates were found among all 2,240 PNGs.**

Every image was decoded to RGBA and every decoded pixel byte included in the
comparison. Images were grouped by dimensions and a digest of those pixel bytes;
any candidate match would be confirmed by direct byte-for-byte equality. There
were no matching pixel groups, no unreadable files and no animated images. This
is not merely a comparison of PNG file hashes: compression and metadata changes
would not conceal identical decoded pixels.

Dimensions: 2,238 images are 1366×768; two are 2732×1536.

There are **repeated captures of the same statistics with different pixels**:
12 match-summary pairs and 36 player-performance pairs. Examples include match
summaries **547/559** and **560/574**. They map to single canonical records and
are not double-counted as additional matches or appearances. Sammy Ameobi's
1943/2033 captures likewise produce one transfer. Pixel comparison does not label
resized, cropped, or otherwise visually similar images as exact duplicates.

## Dashboard validation performed

The live API, committed dashboard JSON and stored public record values agree for
all **12 exported tables**, apart from documented export behavior: provenance
fields are hidden and missing goalkeeper goals are exported as assumed zero.

| Check | Result |
| --- | ---: |
| Existing frontend tests | 52 passed |
| Additional real-data review tests | 3 passed |
| Season/competition/preseason combinations checked | 104 |
| Match detail views rendered | 148 |
| Player detail/tab views rendered | 116 (29 players × 4 tabs) |
| Individual performance dialogs rendered | 1,981 |
| Competition detail views rendered | 12 |
| Data explorer tables rendered | 12 |
| Total server-rendered views, including overview/career/verification | 2,382 |
| Rendering exceptions or detected invalid-value text | 0 |
| Latest OVR disagreements with last captured profile/performance observations | 0 |
| Frontend lint / production build | Passed / passed |
| Database integrity / foreign-key errors | OK / 0 |

Overview KPIs and all six rankings were independently recalculated from the real
records. Default all-career totals agree: **148 matches; 79 wins, 39 draws,
30 losses; 252 goals scored, 153 conceded; 48 clean sheets**. These include
preseason and count match results before penalty shootouts, as the UI states.
Known goalkeeper-zero and opponent-own-goal assumptions were not mistaken for
new extraction errors.

**Browser limitation:** installed Chrome rejects remote debugging under the
machine's administrator policy. That policy was not changed or bypassed. These
are real-data calculations, API checks and React server-side rendering checks,
not a completed interactive browser/layout or manual visual review. The build
also reports its existing large-bundle warning, unrelated to data correctness.

## Remaining confidence limits and follow-up

The previous fresh OCR audit compared **35,090 numeric cells with zero independent
disagreements**, but **14,292 read numeric fields still have no isolated second
reader match**. All 158 cumulative snapshots still have unconfirmed exact cutoff
dates; 448 count comparisons match when using the confirmed screenshot order.
OCR agreement and successful import do not guarantee visual correctness.

Recommended next corrections, without deleting source evidence:

1. Fix profile separator/flag parsing and add country/position validation.
2. Resolve the seven club-identity pairs conservatively, preserving aliases.
3. Extract the visible profile fields from accepted transfer panels.
4. Extend audit coverage to these text/metadata gaps, then rerun processing.
5. Continue targeted independent/manual verification of unmatched numeric fields.

## Evidence

Detailed JSON findings, pixel-check code/results, rendered HTML, calculation-test
results and frontend logs are in `processing/data/dashboard-review/`. The temporary
real-data rendering test is `frontend/test-results/real-data-review.test.tsx`.
Copies are preserved outside the rebuild directory at
`../fifa-career-mode-backups/2026-10-17-dashboard-review/` (relative to repository
root). Generated artifacts are ignored by Git; this summary is the durable
tracked review. No raw statistics were changed to make the checks pass.
