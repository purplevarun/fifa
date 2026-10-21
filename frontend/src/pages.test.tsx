import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { fixture } from "../tests/fixture";
import App from "./App";
import { Audit, CareerRecords, Explorer } from "./archive";
import nottsCountyCrest from "./assets/notts-county-crest.png";
import { CareerContext } from "./context";
import { createModel, defaultFilters } from "./data";
import {
	Competitions,
	MatchDetail,
	Matches,
	Overview,
	PlayerDetail,
	Players,
} from "./pages";
import { CareerLink } from "./ui";

const model = createModel(fixture);

describe("local stats pages", () => {
	it("shows the club crest while career data loads", () => {
		const html = renderToStaticMarkup(<App />);
		expect(html).toContain(`src="${nottsCountyCrest}"`);
		expect(html).toContain('alt="Notts County crest"');
		expect(html).toContain('draggable="false"');
		expect(html).not.toContain("lucide-shield");
	});

	it("labels goalkeeper zero assumptions in otherwise matched verification rows", () => {
		const reviewed = createModel({
			...fixture,
			season_reconciliation: {
				...fixture.season_reconciliation,
				comparisons: fixture.season_reconciliation.comparisons.map(
					(row) => ({
						...row,
						result: "match",
						metrics: {
							...row.metrics,
							goals: {
								observed: 0,
								derived: 0,
								result: "match",
								difference: 0,
								missing_match_values: 0,
								assumed_zero_match_values: 1,
							},
						},
					}),
				),
			},
		});
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/audit"]}>
				<CareerContext
					value={{
						model: reviewed,
						filters: defaultFilters,
						matches: reviewed.matches,
					}}
				>
					<Audit />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("1 goalkeeper goal values assumed zero");
		expect(html).toContain("Matched");
		expect(html).not.toContain("nine comparisons unavailable");
	});

	it.each([
		{ result: "unconfirmed_cutoff", label: "Cutoff unconfirmed" },
		{ result: "partial_comparison", label: "Partial" },
	])("distinguishes $result in verification rows", ({ result, label }) => {
		const verification = createModel({
			...fixture,
			season_reconciliation: {
				...fixture.season_reconciliation,
				comparisons: fixture.season_reconciliation.comparisons.map(
					(row) => ({ ...row, result, metrics: {} }),
				),
			},
		});
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/audit"]}>
				<CareerContext
					value={{
						model: verification,
						filters: defaultFilters,
						matches: verification.matches,
					}}
				>
					<Audit />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain(`>${label}<`);
		expect(html).not.toContain(
			result === "unconfirmed_cutoff"
				? ">Partial<"
				: ">Cutoff unconfirmed<",
		);
	});

	it.each([
		{
			code: "missing_player_core_fields",
			title: "Missing player statistics",
			detail: "Missing player stats: Test Goalkeeper (assists).",
		},
		{
			code: "incomplete_team_statistics",
			title: "Incomplete team statistics",
			detail: "Missing team stats: Notts County (corners); Portsmouth (corners).",
		},
		{
			code: "fewer_than_11_player_records",
			title: "Fewer than 11 player records",
			detail: "Only 8 player appearances are recorded.",
		},
		{
			code: "possession_total_mismatch",
			title: "Possession does not total 100%",
			detail: "Recorded possession adds up to 95% instead of 100%.",
		},
		{
			code: "missing_match_score",
			title: "Incomplete match score",
			detail: "Missing goal total for Portsmouth.",
		},
		{
			code: "player_goal_difference",
			title: "Player goals exceed team score",
			detail: "Credited player goals exceed the team score.",
			team_goals: 1,
			credited_player_goals: 2,
		},
	])("explains $title on verification and match pages", (warning) => {
		const matchId = fixture.matches[1].id;
		const warningModel = createModel({
			...fixture,
			match_coverage: {
				...fixture.match_coverage,
				warnings: [{ ...warning, match_id: matchId }],
			},
		});
		for (const view of [
			{
				entry: "/audit?tab=warnings",
				path: "/audit",
				element: <Audit />,
			},
			{
				entry: `/matches/${matchId}`,
				path: "/matches/:id",
				element: <MatchDetail />,
			},
		]) {
			const html = renderToStaticMarkup(
				<MemoryRouter initialEntries={[view.entry]}>
					<CareerContext
						value={{
							model: warningModel,
							filters: defaultFilters,
							matches: warningModel.matches,
						}}
					>
						<Routes>
							<Route path={view.path} element={view.element} />
						</Routes>
					</CareerContext>
				</MemoryRouter>,
			);
			expect(html).toContain(warning.title);
			expect(html).toContain(warning.detail);
			expect(html).toContain("Portsmouth");
			expect(html).toContain("Notts County");
			expect(html).toContain("8 August 2018");
			expect(html).not.toContain("undefined");
			if (warning.code !== "player_goal_difference") {
				expect(html).not.toContain("Credited player goals:");
			}
		}
	});

	it("keeps own-goal reconciliation data without displaying assumption notices", () => {
		const match = fixture.matches[1];
		const assumed = createModel({
			...fixture,
			match_coverage: {
				...fixture.match_coverage,
				summary: {
					...fixture.match_coverage.summary,
					assumed_own_goals: 1,
					warning_count: 0,
				},
				matches: [
					{
						match_id: match.id,
						home_club: "Portsmouth",
						away_club: "Notts County",
						team_goals: 1,
						credited_player_goals: 0,
						assumed_own_goals: 1,
					},
				],
				warnings: [],
			},
		});
		for (const view of [
			{
				entry: "/audit?tab=warnings",
				path: "/audit",
				element: <Audit />,
			},
			{
				entry: `/matches/${match.id}`,
				path: "/matches/:id",
				element: <MatchDetail />,
			},
		]) {
			const html = renderToStaticMarkup(
				<MemoryRouter initialEntries={[view.entry]}>
					<CareerContext
						value={{
							model: assumed,
							filters: defaultFilters,
							matches: assumed.matches,
						}}
					>
						<Routes>
							<Route path={view.path} element={view.element} />
						</Routes>
					</CareerContext>
				</MemoryRouter>,
			);
			expect(html).not.toContain("Assumed opponent own goals");
			expect(html).not.toContain(
				"Team goals: 1. Credited player goals: 0.",
			);
			expect(html).not.toContain("Individual goal credits unchanged.");
			expect(html).not.toContain("undefined");
			expect(html).not.toContain('class="warning-record"');
			expect(html).not.toContain('class="notice warning"');
			if (view.path === "/audit") {
				expect(html).toContain("No reconciliation warnings");
			}
		}
		expect(assumed.data.match_coverage.summary.assumed_own_goals).toBe(1);
	});

	it.each(["passes_completed", "key_passes", "interceptions"])(
		"ranks recorded %s within selected fixtures and preserves unknowns",
		(statistic) => {
			const detailed = createModel({
				...fixture,
				player_matches: fixture.player_matches.map((row, index) => ({
					...row,
					passes_completed_short:
						index === 0 ? 5 : index === 4 ? 999 : null,
					passes_completed_medium:
						index === 0 || index === 4 ? 4 : null,
					passes_completed_long:
						index === 0 || index === 4 ? 1 : null,
					key_passes: index === 0 ? 2 : null,
					interceptions: index === 0 ? 3 : null,
				})),
			});
			const matches = detailed.matches.filter(
				(match) => match.competition.id === fixture.competitions[0].id,
			);
			const html = renderToStaticMarkup(
				<MemoryRouter initialEntries={[`/players?stat=${statistic}`]}>
					<CareerContext
						value={{
							model: detailed,
							filters: defaultFilters,
							matches,
						}}
					>
						<Players />
					</CareerContext>
				</MemoryRouter>,
			);
			expect(html).toContain("recorded totals");
			expect(html).toContain("1/3 appearances recorded");
			expect(html).toContain("Apps recorded");
			expect(html).toContain("1/2");
			expect(html).toContain('aria-label="partial data"');
			expect(html).not.toContain("999");
			expect(html).not.toContain("Test Opponent");
		},
	);

	it("merges chart statistics with active filters in player links", () => {
		const html = renderToStaticMarkup(
			<MemoryRouter
				initialEntries={[
					"/?season=first&competition=league&preseason=false&stat=goals",
				]}
			>
				<CareerLink to="/players?stat=passes_completed">
					Passing
				</CareerLink>
				<CareerLink to="/players?stat=tackles_won#rankings">
					Tackles
				</CareerLink>
			</MemoryRouter>,
		);
		expect(html).toContain(
			'href="/players?season=first&amp;competition=league&amp;preseason=false&amp;stat=passes_completed"',
		);
		expect(html).toContain(
			'href="/players?season=first&amp;competition=league&amp;preseason=false&amp;stat=tackles_won#rankings"',
		);
		expect(html).not.toContain("passes_completed?");
	});

	it.each([
		{
			completedAt: "2026-09-13T06:27:18+00:00",
			extractedAt: "2026-09-13T06:20:00+00:00",
			expected: "Last processed:",
			date: "2026-09-13T06:27:18+00:00",
			skipped: 36,
		},
		{
			completedAt: null,
			extractedAt: "2026-09-13T06:20:00+00:00",
			expected: "Last OCR saved:",
			date: "2026-09-13T06:20:00+00:00",
			skipped: 0,
		},
		{
			completedAt: null,
			extractedAt: null,
			expected: "Last processed: Not recorded",
			date: null,
			skipped: 0,
		},
	])(
		"shows $expected independently of page load time",
		({ completedAt, extractedAt, expected, date, skipped }) => {
			const processed = createModel({
				...fixture,
				generated_at: "2030-01-01T00:00:00+00:00",
				data_source: {
					label: "Fresh processing preview",
					preview: true,
				},
				processing: {
					last_run: completedAt
						? {
								id: "00000000-0000-4000-8000-000000000900",
								completed_at: completedAt,
								mode: "incremental",
								status: skipped ? "partial" : "completed",
								extracted_images: 0,
								imported_sources: 0,
								skipped_sources: skipped,
								extraction_errors: 0,
							}
						: null,
					last_extracted_at: extractedAt,
				},
			});
			const html = renderToStaticMarkup(
				<MemoryRouter initialEntries={["/"]}>
					<CareerContext
						value={{
							model: processed,
							filters: defaultFilters,
							matches: processed.matches,
						}}
					>
						<Overview />
					</CareerContext>
				</MemoryRouter>,
			);
			expect(html).toContain("Fresh processing preview");
			expect(html).toContain(expected);
			expect(html).not.toContain("2030");
			if (date) expect(html).toContain(`dateTime="${date}"`);
			if (skipped) expect(html).toContain("36 sources not imported");
		},
	);

	it("replaces the overview goal trend with six player ranking charts", () => {
		const ranked = createModel({
			...fixture,
			player_matches: fixture.player_matches.map((row) => ({
				...row,
				passes_completed_short: 5,
				passes_completed_medium: 2,
				passes_completed_long: 1,
				tackles_won: 3,
			})),
		});
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/"]}>
				<CareerContext
					value={{
						model: ranked,
						filters: defaultFilters,
						matches: ranked.matches,
					}}
				>
					<Overview />
				</CareerContext>
			</MemoryRouter>,
		);
		for (const title of [
			"Leading scorers",
			"Most assists",
			"Most appearances",
			"Most passes completed",
			"Most tackles won",
			"Highest rated players",
		]) {
			expect(html).toContain(title);
		}
		expect(html).not.toContain("Goals across the career");
		expect(html.match(/data-ranking-count=/g)).toHaveLength(6);
		expect(html).toContain('data-ranking-variant="lollipop"');
		expect(html).toContain('data-ranking-variant="rating"');
		expect(html).toContain("Average match rating by player");
		expect(html).toContain("/players?stat=passes_completed");
		expect(html).toContain("/players?stat=tackles_won");
	});

	it.each([
		{
			name: "overview",
			route: "/",
			location: "/",
			element: <Overview />,
			title: "Career overview",
		},
		{
			name: "matches",
			route: "/matches",
			location: "/matches",
			element: <Matches />,
			title: "Matches",
		},
		{
			name: "match detail",
			route: "/matches/:id",
			location: `/matches/${fixture.matches[2].id}`,
			element: <MatchDetail />,
			title: "4-3 on penalties",
		},
		{
			name: "players",
			route: "/players",
			location: "/players",
			element: <Players />,
			title: "Players",
		},
		{
			name: "player detail",
			route: "/players/:id",
			location: `/players/${fixture.players[0].id}`,
			element: <PlayerDetail />,
			title: "Test Forward",
		},
		{
			name: "competitions",
			route: "/competitions",
			location: "/competitions",
			element: <Competitions />,
			title: "Competitions",
		},
		{
			name: "career records",
			route: "/career",
			location: "/career",
			element: <CareerRecords />,
			title: "Career records",
		},
		{
			name: "verification",
			route: "/audit",
			location: "/audit",
			element: <Audit />,
			title: "Verification",
		},
		{
			name: "data explorer",
			route: "/data",
			location: "/data",
			element: <Explorer />,
			title: "Data explorer",
		},
	])(
		"renders $name without image metadata",
		({ route, location, element, title }) => {
			const html = renderToStaticMarkup(
				<MemoryRouter initialEntries={[location]}>
					<CareerContext
						value={{
							model,
							filters: defaultFilters,
							matches: model.matches,
						}}
					>
						<Routes>
							<Route path={route} element={element} />
						</Routes>
					</CareerContext>
				</MemoryRouter>,
			);
			expect(html).toContain(title);
			expect(html).not.toContain("View source screenshot");
			expect(html).not.toContain("/evidence/");
		},
	);
	it("shows yearly winners from any team independently of league filters", () => {
		const outsidePlayer = {
			id: "00000000-0000-4000-8000-000000000130",
			name: "Lionel Messi",
			nationality: null,
		};
		const model = createModel({
			...fixture,
			schema_version: 4,
			players: [...fixture.players, outsidePlayer],
			competition_events: [
				{
					id: "00000000-0000-4000-8000-000000000131",
					event_type: "player_of_the_year",
					player_id: fixture.players[0].id,
					competition_season_id: null,
					period: "2018",
					announced_on: null,
					description: "2018 annual winner",
				},
				{
					id: "00000000-0000-4000-8000-000000000132",
					event_type: "player_of_the_year",
					player_id: outsidePlayer.id,
					competition_season_id: null,
					period: "2019",
					announced_on: null,
					description: "2019 annual winner",
				},
			],
		});
		const filters = {
			...defaultFilters,
			season: fixture.seasons[0].id,
			competition: fixture.competitions[0].id,
			preseason: false,
		};
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{ model, filters, matches: model.matches }}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("Player of the Year");
		expect(html).toContain("Search yearly award winners");
		expect(html).toContain("Lionel Messi");
		expect(html).toContain(fixture.players[0].name);
		expect(html).toContain(">2019</td>");
		expect(html).toContain(">2018</td>");
		expect(html.indexOf(">2019</td>")).toBeLessThan(
			html.indexOf(">2018</td>"),
		);
		expect(html).toContain("Annual award");
		expect(html).not.toContain("Unknown competition");
	});
	it("shows championship winners by season and competition including other clubs", () => {
		const model = createModel({
			...fixture,
			schema_version: 4,
			competition_events: [
				{
					id: "00000000-0000-4000-8000-000000000133",
					event_type: "champion",
					club_id: fixture.clubs[1].id,
					competition_season_id: fixture.competition_seasons[0].id,
					period: "2018/19",
					description: "League title",
				},
				{
					id: "00000000-0000-4000-8000-000000000134",
					event_type: "champion",
					club_id: fixture.clubs[0].id,
					competition_season_id: fixture.competition_seasons[1].id,
					period: "2018/19",
					description: "Cup title",
				},
			],
		});
		const filters = {
			...defaultFilters,
			season: fixture.seasons[0].id,
			competition: fixture.competitions[0].id,
		};
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{ model, filters, matches: model.matches }}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("Champions");
		expect(html).toContain("Search champions");
		expect(html).toContain(fixture.clubs[1].name);
		expect(html).toContain(fixture.seasons[0].label);
		expect(html).toContain(fixture.competitions[0].name);
		expect(html).toContain("League title");
		expect(html).not.toContain("Cup title");
	});
	it("keeps yearly award and championship sections visible before awards are recorded", () => {
		const model = createModel({ ...fixture, competition_events: [] });
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{
						model,
						filters: defaultFilters,
						matches: model.matches,
					}}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("No Player of the Year awards recorded");
		expect(html).toContain("No championships in this selection");
	});
	it("separates announcement dates and spaces compact Golden Boot headlines without changing stored text", () => {
		const event = {
			id: "00000000-0000-4000-8000-000000000135",
			event_type: "golden_boot",
			player_id: fixture.players[0].id,
			competition_season_id: fixture.competition_seasons[0].id,
			period: "2018/19",
			announced_on: "2019-05-04",
			description: "ZokoWinsGoldenBoot.",
		};
		const model = createModel({ ...fixture, competition_events: [event] });
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{
						model,
						filters: defaultFilters,
						matches: model.matches,
					}}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain(
			'<div class="event-date"><span>2018/19</span><small class="muted">Announced 4 May</small></div>',
		);
		expect(html).toContain("Zoko wins Golden Boot.");
		expect(html).not.toContain("ZokoWinsGoldenBoot");
		expect(model.data.competition_events[0].description).toBe(
			"ZokoWinsGoldenBoot.",
		);
	});
	it("groups monthly honours by player and season and shows the award month", () => {
		const data = {
			...fixture,
			competition_events: [
				{
					id: "00000000-0000-4000-8000-000000000090",
					player_id: fixture.players[0].id,
					competition_season_id: fixture.competition_seasons[0].id,
					event_type: "player_of_the_month",
					period: "2018-08",
					announced_on: null,
					description: "August winner",
				},
				{
					id: "00000000-0000-4000-8000-000000000091",
					player_id: fixture.players[0].id,
					competition_season_id: fixture.competition_seasons[0].id,
					event_type: "player_of_the_month",
					period: "2018-09",
					announced_on: "2018-10-05",
					description: "September winner",
				},
				{
					id: "00000000-0000-4000-8000-000000000092",
					player_id: fixture.players[1].id,
					competition_season_id: fixture.competition_seasons[1].id,
					event_type: "goalkeeper_of_the_competition",
					period: "2018/19",
					description: "Cup winner",
				},
			],
		};
		const model = createModel(data);
		const filters = {
			...defaultFilters,
			season: fixture.seasons[0].id,
			competition: fixture.competitions[0].id,
		};
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{ model, filters, matches: model.matches }}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("Player of the Month");
		expect(html).toContain("August 2018");
		expect(html).toContain("September 2018");
		expect(html).toContain(">2</td>");
		expect(html).not.toContain("Cup winner");
		expect(html).not.toContain("Date not recorded");
	});
	it("shows career and season leaders for braces and hat-tricks", () => {
		const data = {
			...fixture,
			player_matches: fixture.player_matches.map((row) =>
				row.id.endsWith("000000000031")
					? {
							...row,
							player_id: fixture.players[0].id,
							match_id: fixture.matches[1].id,
							goals: 3,
						}
					: row,
			),
		};
		const scoringModel = createModel(data);
		const html = renderToStaticMarkup(
			<MemoryRouter initialEntries={["/career?tab=events"]}>
				<CareerContext
					value={{
						model: scoringModel,
						filters: defaultFilters,
						matches: scoringModel.matches,
					}}
				>
					<CareerRecords />
				</CareerContext>
			</MemoryRouter>,
		);
		expect(html).toContain("Scoring feats");
		expect(html).toContain("Career totals");
		expect(html).toContain("Season by season");
		expect(html).toContain("Braces");
		expect(html).toContain("Hat-tricks");
		expect(html).toContain("Test Forward");
	});
});
