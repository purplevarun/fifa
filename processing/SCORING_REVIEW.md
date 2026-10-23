# Hat-tricks and homepage statistics review

> Owner follow-up: the four hat-tricks and two opponent own goals are now
> confirmed. See [MANUAL_FOLLOWUP.md](MANUAL_FOLLOWUP.md) for the fresh scoreboard
> retries and the resolved 459 score confirmation: Carlisle 1–2 Notts after extra time.

Reviewed 22 October 2026 against the current export: **169 matches and 2,253
Notts County appearances**. This is an automated evidence review, not exhaustive
human visual verification or proof that every career fixture was captured.

## Recorded hat-tricks

The current data supports **4 hat-trick performances**: Takefusa Kubo 2,
Reiss Nelson 1, Seydou Doumbia 1.

| Player         | Goals | In-game date | Fixture                        | Competition    | Player screenshot                       |
| -------------- | ----- | ------------ | ------------------------------ | -------------- | --------------------------------------- |
| Takefusa Kubo  | 3     | 2020-01-11   | Notts County 4–2 Colchester    | EFL League One | [1500.png](../raw_screenshots/1500.png) |
| Takefusa Kubo  | 3     | 2020-02-08   | Notts County 3–0 Rotherham Utd | EFL League One | [1559.png](../raw_screenshots/1559.png) |
| Reiss Nelson   | 3     | 2020-02-22   | Shrewsbury 1–5 Notts County    | EFL League One | [1589.png](../raw_screenshots/1589.png) |
| Seydou Doumbia | 3     | 2020-08-26   | Ipswich 0–4 Notts County       | Carabao Cup    | [2035.png](../raw_screenshots/2035.png) |

The existing threshold was already `goals >= 3`, not `goals === 3`. No goal
credits have been increased or rewritten. Four-or-more-goal performances count
as one hat-trick each; duplicate screenshots, cumulative season totals and
penalty-shootout scores must not inflate the count.

Previously the career scoring tables used every match regardless of the active
filters. Homepage and career records now share a filter-aware calculation, with
player totals, season totals, match links, goal coverage and missing-lineup notices.

## Independent goal readings

Re-ran the saved comparison in `processing/data/check_goal_ocr.py` against the
saved Apple Vision crop readings and source diagnostics. The comparison checks
that each reading's source hash matches its diagnostic source.

- **2,116 saved player-goal crop readings agree** with the source candidates.
  This is a screenshot-reading count, not a unique-appearance count.
- All four hat-trick screenshot readings above independently return 3.
- There are no disagreements on player-goal cells in those saved checks.
- **23 scoreboard cells** were unreadable to the independent reader, rather
  than contradictory numeric readings. They come from screenshots **111, 459,
  662, 814, 860, 1028, 1043, 1222, 1296, 1309, 1662, 1722, 2199, 2285, 2496**.
  This does not establish that the primary OCR's scores are incorrect.

The generated comparison is `processing/data/hat-trick-goal-checks.json`.
Like other diagnostics in that directory, it is ignored by Git and deleted by
`./run process`; this summary is outside that directory and survives a rebuild.
Agreement between OCR readers cannot rule out shared misreads. Missing goal
credits must not be reconstructed from cumulative totals or assigned from team
scores without evidence of the scorer.

Two existing own-goal assumptions also remain unconfirmed: Portsmouth on
2019-10-09 (Kubo 1, Lorch 1; team 3) and Rochdale on 2020-08-11 (Skipp 1,
Doumbia 1; team 3). Assigning either missing team goal to one of those recorded
scorers would make a brace, not a hat-trick. These assumptions were not changed.

**Manual help:** if another hat-trick is remembered, provide its player,
opponent, in-game date or screenshot number. That is more useful than guessing
additional goal credits from the season total. The four screenshots above are
also direct starting points for visual confirmation.

## Stray FIFA text

The fragment `PA FIFA19 AFIFA19 EAFIFA19 EFL ...` comes from sponsor-board logos
below news articles, not a statistic or competition name. Seven exported monthly
award descriptions contain these logo tails. Display cleanup removes only a
trailing sequence of known logo fragments with at least two FIFA marks; ordinary
article text is preserved. Old exported full records remain unchanged. Extractor
1.4.6 cleans future parsed articles while keeping their original OCR evidence.

## Joined-word vocabulary

The shared root `vocab.json` now repairs unambiguous word joins in new news
extraction and in displayed descriptions from older exports. On the current
dataset, **10 descriptions receive spacing repairs**, including `Countyearned`,
`impressiveperformanceforNotts`, `LeagueTwo` and `Ramsdalehas`.

Only spaces are inserted: original characters and raw evidence remain intact.
Known whole words are protected; ambiguous splits, unknown tokens, numbers and
non-English tokens are left unchanged. Python and frontend tests share the same
spacing fixtures. The development server's browser module import of the shared
JSON was verified without widening filesystem access.

## Stats-based role leaders

Updated 23 October 2026: every recorded player is considered for every award,
regardless of position. The previous CAM/forward and other position filters are
removed. Missing statistics still remain unknown rather than being fabricated.

Scores now use **60% accumulated contribution, 25% per-game performance and 15%
games played**, retaining each award's internal stat weights. With all current
fixtures selected, including preseason:

| Award      | Leader         | Relative score / 100 | Complete appearances used |
| ---------- | -------------- | -------------------- | ------------------------- |
| Forward    | Takefusa Kubo  | 94.8                 | 147                       |
| Playmaker  | Takefusa Kubo  | 95.2                 | 147                       |
| Midfielder | Danny Williams | 89.4                 | 159                       |
| Defender   | Danny Williams | 95.7                 | 159                       |
| Goalkeeper | Aaron Ramsdale | 97.3                 | 140                       |

The debut-hat-trick regression compares 3 goals in one appearance against 100
goals in 100 appearances (no assists): the forward scores are **21.6 versus 69.7**.
Both players remain candidates; the experienced player's sustained contribution
outweighs the debutant's scoring-rate spike. Samples under five are provisional,
not excluded. At least 80% of selected appearances need the relevant category stats.

The homepage exposes the contribution/rate/games breakdown and raw totals.
Results change with the filters; these are not FIFA ratings or cross-award
comparisons. The full formula and missing-data rules are documented in
[README.md](../README.md#performance-awards).

## Verification

- 140 frontend unit/render tests passed, including the debut-veteran and universal-eligibility regressions.
- Python suite passed: 206 tests passed, 26 optional tests skipped.
- Frontend lint, production build, real-data score checks, eight server-rendered
  views, and development/production JSON checks passed.
- Desktop/mobile browser tests were added but could not execute here. The bundled
  Chromium download failed; installed Chrome reports **“DevTools remote debugging
  is disallowed by the system admin.”** The policy-blocked run was stopped. No
  browser-test pass or manual visual verification is claimed.
- These local checks do not verify a deployment; publishing is checked separately.
