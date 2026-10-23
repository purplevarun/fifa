import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { fixture } from "../tests/fixture";
import {
	awardScoring,
	positionDefinitions,
	positionRankings,
	scoringFeats,
} from "./analytics";
import { CareerRecords } from "./archive";
import { CareerContext } from "./context";
import {
	createModel,
	defaultFilters,
	eventDescription,
	selectMatches,
} from "./data";
import type { Model, Performance } from "./data";
import { Overview } from "./pages";

type TestPerformance = Partial<Performance> & { player_id: string };
function career(rows: TestPerformance[], matchCount = 1) {
	return createModel({
		...fixture,
		players: [...new Set(rows.map((row) => row.player_id))].map((id) => ({
			id,
			name: id,
			nationality: null,
		})),
		matches: Array.from({ length: matchCount }, (_, index) => ({
			...fixture.matches[0],
			id: `match-${index}`,
			played_on: new Date(Date.UTC(2018, 7, index + 1))
				.toISOString()
				.slice(0, 10),
		})),
		player_snapshots: [],
		player_competition_snapshots: [],
		competition_events: [],
		player_matches: rows.map((row, index) => ({
			...fixture.player_matches[0],
			id: `appearance-${index}`,
			match_id: "match-0",
			goals: 0,
			assists: 0,
			passes_completed_short: 0,
			passes_completed_medium: 0,
			passes_completed_long: 0,
			key_passes: 0,
			tackles_won: 0,
			interceptions: 0,
			blocks: 0,
			clearances: 0,
			shots_caught: 0,
			shots_parried: 0,
			goals_conceded: 0,
			...row,
		})),
	});
}
const repeat = (player: string, count: number): TestPerformance[] =>
	Array.from({ length: count }, (_, index) => ({
		player_id: player,
		match_id: `match-${index}`,
		goals: 1,
	}));
const sampleRoles: TestPerformance[] = [
	{ player_id: "Striker", displayed_position: "ST", goals: 2 },
	{ player_id: "Assister", displayed_position: "RW", assists: 3 },
	{
		player_id: "Engine",
		displayed_position: "CM",
		passes_completed_short: 10,
		key_passes: 1,
		tackles_won: 4,
	},
	{
		player_id: "Playmaker",
		displayed_position: "CAM",
		passes_completed_short: 20,
		key_passes: 4,
		tackles_won: 1,
	},
	{
		player_id: "Passing defender",
		displayed_position: "RB",
		passes_completed_short: 100,
		tackles_won: 1,
		interceptions: 1,
	},
	{
		player_id: "Stopper",
		displayed_position: "CB",
		passes_completed_short: 10,
		tackles_won: 4,
		interceptions: 2,
		blocks: 1,
		clearances: 1,
	},
	{
		player_id: "Keeper",
		displayed_position: "GK",
		shots_caught: 4,
		shots_parried: 6,
		goals_conceded: 0,
	},
	{
		player_id: "Other keeper",
		displayed_position: "GK",
		shots_caught: 6,
		goals_conceded: 2,
	},
];

function render(
	model: Model,
	page: "overview" | "records" = "overview",
	matches = model.matches,
) {
	return renderToStaticMarkup(
		<MemoryRouter
			initialEntries={[page === "records" ? "/career?tab=events" : "/"]}
		>
			<CareerContext value={{ model, filters: defaultFilters, matches }}>
				{page === "records" ? <CareerRecords /> : <Overview />}
			</CareerContext>
		</MemoryRouter>,
	);
}

describe("scoring feats", () => {
	it("counts each 3+ goal appearance once, not just exact threes or screenshots", () => {
		const model = career(
			[
				{ player_id: "Scorer", goals: 2 },
				{ player_id: "Scorer", match_id: "match-1", goals: 3 },
				{ player_id: "Scorer", match_id: "match-2", goals: 4 },
				{ player_id: "Scorer", match_id: "match-3", goals: 6 },
				{ player_id: "Scorer", match_id: "match-2", goals: 4 },
				{
					player_id: "Opponent",
					goals: 9,
					club_id: fixture.clubs[1].id,
				},
			],
			4,
		);
		const feats = scoringFeats(model, model.matches);
		expect(feats.total).toBe(4);
		expect(feats.career).toEqual([
			expect.objectContaining({
				name: "Scorer",
				braces: 1,
				hat_tricks: 3,
			}),
		]);
		expect(feats.hatTricks.map((row) => row.goals)).toEqual([6, 4, 3]);
		expect(feats.seasonal[0]).toMatchObject({
			season: "2018/19",
			hat_tricks: 3,
		});
	});
	it("uses selected fixtures, including the preseason and competition filters", () => {
		const base = career(
			[
				{ player_id: "League scorer", goals: 3 },
				{
					player_id: "Preseason scorer",
					match_id: "match-1",
					goals: 4,
				},
			],
			2,
		);
		const model = createModel({
			...base.data,
			matches: base.data.matches.map((match, index) =>
				index
					? {
							...match,
							competition_season_id:
								fixture.competition_seasons[2].id,
						}
					: match,
			),
		});
		for (const filters of [
			{ ...defaultFilters, preseason: false },
			{ ...defaultFilters, competition: fixture.competitions[0].id },
		]) {
			const selected = selectMatches(model, filters);
			expect(
				scoringFeats(model, selected).hatTricks.map((row) => row.name),
			).toEqual(["League scorer"]);
			expect(
				positionRankings(model, selected).roles[0].candidates.map(
					(row) => row.name,
				),
			).toEqual(["League scorer"]);
			const html = render(model, "records", selected);
			expect(html).toContain("1 hat-tricks / selected fixtures");
			expect(html).not.toContain("Preseason scorer");
		}
	});
	it("separates seasons without counting cumulative snapshots or shootout scores", () => {
		const base = career(
			[
				{ player_id: "Scorer", goals: 3 },
				{ player_id: "Scorer", match_id: "match-1", goals: 4 },
				{
					player_id: "Keeper",
					match_id: "match-2",
					goals: 0,
					goals_assumed_zero: true,
				},
			],
			3,
		);
		const model = createModel({
			...base.data,
			seasons: [
				...base.data.seasons,
				{ id: "second-season", label: "2019/20" },
			],
			competition_seasons: [
				...base.data.competition_seasons,
				{
					id: "second-edition",
					season_id: "second-season",
					competition_id: fixture.competitions[0].id,
				},
			],
			matches: base.data.matches.map((match, index) =>
				index === 1
					? {
							...match,
							competition_season_id: "second-edition",
							played_on: "2019-08-01",
							extra_time: true,
						}
					: { ...match, home_penalties: 5, away_penalties: 4 },
			),
			player_competition_snapshots: [
				{ id: "snapshot", player_id: "Scorer", goals: 90 },
			],
		});
		const feats = scoringFeats(model, model.matches);
		expect(feats.career[0].hat_tricks).toBe(2);
		expect(feats.seasonal.map((row) => row.hat_tricks)).toEqual([1, 1]);
		expect(feats.assumedZero).toBe(1);
		expect(
			scoringFeats(
				model,
				selectMatches(model, {
					...defaultFilters,
					season: "second-season",
				}),
			).hatTricks,
		).toHaveLength(1);
	});
	it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -1])(
		"keeps invalid or missing goals (%s) out of counts",
		(goals) => {
			const model = career([{ player_id: "Unknown", goals }]);
			expect(scoringFeats(model, model.matches)).toMatchObject({
				total: 1,
				known: 0,
				hatTricks: [],
				career: [],
				missingLineups: 1,
			});
		},
	);
	it("does not declare zero hat-trick leaders, and surfaces incomplete coverage", () => {
		const model = career([
			{ player_id: "Brace scorer", goals: 2 },
			{ player_id: "Unknown", goals: null },
		]);
		const html = render(model, "records");
		expect(html).toContain("Most hat-tricks: None");
		expect(html).toContain("Partial goal data: 1 appearances are unknown");
		expect(html).toContain("Incomplete lineups: 1 fixtures");
		expect(html).toContain("No hat-tricks recorded in this selection");
		expect(scoringFeats(model, [])).toMatchObject({
			total: 0,
			known: 0,
			career: [],
			hatTricks: [],
		});
	});
});

describe("position rankings", () => {
	it("uses transparent, normalised weights rather than mixing unlike raw totals", () => {
		const model = career(sampleRoles);
		const { roles } = positionRankings(model, model.matches);
		expect(roles.map((role) => role.candidates[0].name)).toEqual([
			"Striker",
			"Assister",
			"Playmaker",
			"Stopper",
			"Keeper",
		]);
		const expected = [83, 57.5, 66.425, 92.35, 100];
		roles.forEach((role, index) =>
			expect(role.candidates[0].score).toBeCloseTo(expected[index]),
		);
		expect(
			awardScoring.contribution +
				awardScoring.perGame +
				awardScoring.games,
		).toBe(100);
		for (const group of roles) {
			expect(
				group.metrics.reduce(
					(sum, component) => sum + component.weight,
					0,
				),
			).toBe(100);
			for (const player of group.candidates) {
				expect(player.score).toBeGreaterThan(0);
				expect(player.score).toBeLessThanOrEqual(100 + 1e-9);
				expect(
					Object.values(player.breakdown).reduce(
						(sum, value) => sum + value,
						0,
					),
				).toBeCloseTo(player.score);
				expect(
					player.metrics.reduce(
						(sum, metric) => sum + metric.points,
						0,
					),
				).toBeCloseTo(
					player.breakdown.contribution + player.breakdown.perGame,
				);
			}
		}
	});
	it.each([
		"ST",
		"CF",
		"LW",
		"RW",
		"LF",
		"RF",
		"CM",
		"CAM",
		"CDM",
		"LM",
		"RM",
		"CB",
		"LB",
		"RB",
		"LWB",
		"RWB",
		"GK",
		null,
		"unknown",
	])(
		"considers position %s for every award when the stats exist",
		(position) => {
			const model = career([
				{
					player_id: "Versatile",
					displayed_position: position,
					played_position: position,
					goals: 1,
					assists: 1,
					passes_completed_short: 10,
					key_passes: 1,
					tackles_won: 1,
					interceptions: 1,
					blocks: 1,
					clearances: 1,
					shots_caught: 1,
					shots_parried: 1,
				},
			]);
			for (const award of positionRankings(model, model.matches).roles) {
				expect(award.consideredPlayers).toBe(1);
				expect(award.candidates[0]).toMatchObject({
					name: "Versatile",
					known: 1,
					total: 1,
					score: 100,
				});
			}
		},
	);
	it("combines all games despite position changes or future profile snapshots", () => {
		const rows = repeat("Versatile", 10).map((row, index) => ({
			...row,
			displayed_position: "CB",
			played_position: index < 5 ? "ST" : "CM",
			key_passes: 2,
			passes_completed_short: 10,
		}));
		const base = career(rows, 10);
		const model = createModel({
			...base.data,
			player_snapshots: [
				{
					...fixture.player_snapshots[0],
					player_id: "Versatile",
					displayed_position: "GK",
				},
			],
		});
		const { roles } = positionRankings(model, model.matches);
		expect(roles[0].candidates[0]).toMatchObject({
			name: "Versatile",
			known: 10,
			total: 10,
		});
		expect(
			roles.find((role) => role.role === "midfielder")?.candidates[0],
		).toMatchObject({
			name: "Versatile",
			known: 10,
			total: 10,
		});
		for (const role of roles)
			expect(role.candidates[0]).toMatchObject({
				name: "Versatile",
				known: 10,
				total: 10,
			});
		expect(
			roles.find((role) => role.role === "playmaker")?.candidates[0],
		).toMatchObject({ name: "Versatile", known: 10, total: 10 });
	});
	it("allows keepers and unknown positions to win attacking awards but excludes opponents", () => {
		const model = career(
			[
				...repeat("Striker", 5).map((row) => ({
					...row,
					goals: 4,
					assists: 0,
				})),
				...repeat("Creator", 5).map((row) => ({
					...row,
					displayed_position: "CAM",
					goals: 1,
					assists: 4,
					key_passes: 2,
				})),
				...repeat("Creative defender", 5).map((row) => ({
					...row,
					displayed_position: "CB",
					goals: 0,
					assists: 1,
				})),
				...repeat("Keeper", 5).map((row) => ({
					...row,
					displayed_position: "GK",
					goals: 100,
					assists: 100,
				})),
				...repeat("Unknown", 5).map((row) => ({
					...row,
					displayed_position: null,
					goals: 100,
					assists: 100,
				})),
				...repeat("Opponent", 5).map((row) => ({
					...row,
					club_id: fixture.clubs[1].id,
					goals: 100,
					assists: 100,
				})),
			],
			5,
		);
		const { roles } = positionRankings(model, model.matches);
		expect(roles[0].candidates[0].name).toBe("Keeper");
		expect(
			roles.find((role) => role.role === "midfielder")?.candidates[0]
				.name,
		).toBe("Creator");
		const playmakers = roles.find(
			(role) => role.role === "playmaker",
		)!.candidates;
		expect(playmakers.map((row) => row.name)).toEqual([
			"Keeper",
			"Unknown",
			"Creator",
			"Striker",
			"Creative defender",
		]);
		expect(playmakers[0].score).toBe(100);
		expect(playmakers[0].metrics.map((metric) => metric.weight)).toEqual([
			50, 50,
		]);
		const selected = positionRankings(
			model,
			model.matches.slice(0, 1),
		).roles.find((role) => role.role === "playmaker")!;
		expect(selected.candidates[0]).toMatchObject({ known: 1, total: 1 });
	});
	it("rewards more games at the same rate without counting duplicate or opponent records", () => {
		const model = career(
			[
				...repeat("Regular", 6),
				...repeat("Reserve", 5),
				{ ...repeat("Regular", 1)[0], id: "duplicate" },
				{
					player_id: "Opponent",
					club_id: fixture.clubs[1].id,
					goals: 100,
				},
			],
			6,
		);
		const candidates = positionRankings(model, model.matches).roles[0]
			.candidates;
		expect(candidates.map((player) => player.name)).toEqual([
			"Regular",
			"Reserve",
		]);
		expect(candidates[0].score).toBeCloseTo(83);
		expect(candidates[1].score).toBeCloseTo(72.5);
		expect(candidates[0].breakdown.games).toBe(15);
		expect(candidates[1].breakdown.games).toBe(12.5);
		expect(candidates.map((player) => player.total)).toEqual([6, 5]);
		expect(candidates[0].metrics[0]).toMatchObject({
			total: 6,
			perAppearance: 1,
		});
	});
	it("requires 80% coverage and uses only the same complete games in every component", () => {
		const partial = repeat("Eligible partial", 6).map((row, index) => ({
			...row,
			assists: index === 5 ? null : 0,
		}));
		const lowCoverage = repeat("Low coverage", 7).map((row, index) => ({
			...row,
			assists: index >= 5 ? null : 0,
		}));
		const model = career(
			[...partial, ...lowCoverage, ...repeat("Tiny sample", 4)],
			7,
		);
		const result = positionRankings(model, model.matches);
		expect(result.roles[0].candidates).toHaveLength(2);
		expect(result.roles[0].candidates[0]).toMatchObject({
			name: "Eligible partial",
			known: 5,
			total: 6,
		});
		expect(result.roles[0].candidates[0].metrics[0].total).toBe(5);
		expect(result.roles[0].insufficientDataPlayers).toBe(1);
		expect(result.roles[0].candidates[0].breakdown.games).toBe(15);
		expect(result.roles[0].candidates[1].breakdown.games).toBe(12);
		const html = render(model);
		expect(html).toContain("5/6 appearances with complete scoring data");
		expect(html).toContain(
			"Partial data · incomplete appearances excluded",
		);
	});
	it("ranks 100 goals in 100 games above a hat-trick on debut without excluding the debutant", () => {
		const model = career(
			[...repeat("Veteran", 100), { player_id: "Debutant", goals: 3 }],
			100,
		);
		const candidates = positionRankings(model, model.matches).roles[0]
			.candidates;
		expect(candidates.map((player) => player.name)).toEqual([
			"Veteran",
			"Debutant",
		]);
		expect(candidates[0].score).toBeCloseTo(69.6666667);
		expect(candidates[1].score).toBeCloseTo(21.59);
		expect(candidates[0].breakdown).toMatchObject({
			contribution: 48,
			games: 15,
		});
		expect(candidates[1].known).toBe(1);
		expect(candidates[1].breakdown.games).toBeCloseTo(0.15);
		expect(
			positionDefinitions
				.find((group) => group.role === "forward")!
				.metrics.map((metric) => metric.weight),
		).toEqual([80, 20]);
		expect(
			positionDefinitions
				.find((group) => group.role === "playmaker")!
				.metrics.map((metric) => metric.weight),
		).toEqual([50, 50]);
	});
	it("balances quality with longevity rather than rewarding attendance alone", () => {
		const model = career(
			[
				...repeat("Quality", 50).map((row) => ({ ...row, goals: 2 })),
				...repeat("Veteran", 100),
				...repeat("No production", 100).map((row) => ({
					...row,
					goals: 0,
				})),
			],
			100,
		);
		const candidates = positionRankings(model, model.matches).roles[0]
			.candidates;
		expect(candidates.map((player) => player.name)).toEqual([
			"Quality",
			"Veteran",
		]);
		expect(candidates[0].score).toBeCloseTo(75.5);
		expect(candidates[1].score).toBeCloseTo(73);
	});
	it("applies the longevity balance to every award, including goalkeeper stats", () => {
		const model = career(
			[
				...repeat("Experienced", 100).map((row) => ({
					...row,
					assists: 1,
					passes_completed_short: 10,
					key_passes: 1,
					tackles_won: 1,
					interceptions: 1,
					shots_caught: 1,
				})),
				{
					player_id: "Debutant",
					displayed_position: "ST",
					goals: 3,
					assists: 3,
					passes_completed_short: 30,
					key_passes: 3,
					tackles_won: 3,
					interceptions: 3,
					shots_caught: 3,
				},
			],
			100,
		);
		for (const award of positionRankings(model, model.matches).roles) {
			expect(award.candidates.map((player) => player.name)).toEqual([
				"Experienced",
				"Debutant",
			]);
		}
	});
	it("does not reward conceding more, fabricate saves, or count unrelated missing games", () => {
		const model = career(
			[
				...repeat("Lower conceded", 5).map((row) => ({
					...row,
					shots_caught: 2,
					goals_conceded: 1,
				})),
				...repeat("Higher conceded", 5).map((row) => ({
					...row,
					shots_caught: 2,
					goals_conceded: 3,
				})),
				{
					player_id: "No keeper data",
					shots_caught: null,
					shots_parried: null,
					goals_conceded: null,
				},
			],
			5,
		);
		const keepers = positionRankings(model, model.matches).roles.find(
			(group) => group.role === "goalkeeper",
		)!;
		expect(keepers.candidates.map((player) => player.name)).toEqual([
			"Lower conceded",
			"Higher conceded",
		]);
		expect(
			keepers.candidates[0].metrics.find(
				(metric) => metric.field === "goals_conceded",
			)!.points,
		).toBeGreaterThan(
			keepers.candidates[1].metrics.find(
				(metric) => metric.field === "goals_conceded",
			)!.points,
		);
		expect(keepers.insufficientDataPlayers).toBe(1);
		expect(render(model)).toContain(
			"players lack enough recorded stats for this award; no position restriction",
		);
	});
	it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -1])(
		"does not turn unknown/invalid score components (%s) into zero",
		(value) => {
			const model = career([
				{ player_id: "Forward", goals: 2, assists: value },
				{
					player_id: "Midfield",
					displayed_position: "CM",
					key_passes: 2,
					passes_completed_medium: value,
				},
				{
					player_id: "Defence",
					displayed_position: "CB",
					tackles_won: 2,
					blocks: value,
				},
				{
					player_id: "Keeper",
					displayed_position: "GK",
					shots_caught: 2,
					shots_parried: value,
				},
			]);
			const roles = positionRankings(model, model.matches).roles;
			for (const [role, player] of [
				["forward", "Forward"],
				["midfielder", "Midfield"],
				["defender", "Defence"],
				["goalkeeper", "Keeper"],
			])
				expect(
					roles
						.find((group) => group.role === role)!
						.candidates.some(
							(candidate) => candidate.name === player,
						),
				).toBe(false);
		},
	);
	it("never assumes a clean sheet when goalkeeper goals conceded are missing", () => {
		const model = career([
			{
				player_id: "Keeper",
				displayed_position: "GK",
				shots_caught: 10,
				goals_conceded: null,
			},
		]);
		expect(
			positionRankings(model, model.matches).roles.find(
				(role) => role.role === "goalkeeper",
			)?.candidates,
		).toEqual([]);
	});
	it("handles empty selections, zero production, unknown positions and deterministic ties", () => {
		const model = career([
			{ player_id: "Zero" },
			{ player_id: "Unknown", displayed_position: null, goals: 20 },
		]);
		expect(
			positionRankings(model, model.matches).roles[0].consideredPlayers,
		).toBe(2);
		expect(
			positionRankings(model, model.matches).roles[0].candidates.map(
				(player) => player.name,
			),
		).toEqual(["Unknown"]);
		expect(
			positionRankings(model, model.matches).roles[0]
				.noContributionPlayers,
		).toBe(1);
		expect(
			positionRankings(model, []).roles.every(
				(group) => group.candidates.length === 0,
			),
		).toBe(true);
		const tied = career([
			{ player_id: "Zed", goals: 2 },
			{ player_id: "Alpha", goals: 2 },
		]);
		expect(
			positionRankings(tied, tied.matches).roles[0].candidates.map(
				(player) => player.name,
			),
		).toEqual(["Alpha", "Zed"]);
	});
	it("shows all five homepage cards in the requested order with weights and coverage", () => {
		const model = career([
			...sampleRoles,
			{
				player_id: "Hat-trick scorer",
				displayed_position: "RW",
				goals: 4,
			},
		]);
		const html = render(model);
		let previousCardIndex = -1;
		for (const title of [
			"Best forward",
			"Best playmaker",
			"Best midfielder",
			"Best defender",
			"Best goalkeeper",
		]) {
			const cardIndex = html.indexOf(`aria-label="${title}"`);
			expect(cardIndex).toBeGreaterThan(previousCardIndex);
			previousCardIndex = cardIndex;
		}
		expect(html.match(/role score/g)).toHaveLength(5);
		expect(
			html.match(/Provisional · fewer than 5 appearances/g),
		).toHaveLength(5);
		expect(html).toContain("80% of stat components");
		expect(html).toContain("20% of stat components");
		expect(html).toContain("50% of stat components");
		expect(html).toContain("All positions");
		expect(html).toContain("10% of stat components");
		expect(html).toContain("How the award scores work");
		expect(html).toContain(
			"60% contribution / 25% per-game performance / 15% games played",
		);
		expect(html.match(/score breakdown/g)).toHaveLength(5);
		expect(html).toContain("Games played");
		expect(html).not.toContain("All outfield positions");
		expect(html).toContain("Match-by-match breakdown (1)");
		expect(html).toContain('href="/matches/match-0"');
		expect(html).toContain("not per-90 scores");
	});
});

describe("news sponsor OCR cleanup", () => {
	const body =
		"Kubo grabs August Player of the Month Award. A deserved award.";
	it.each([
		"PA FIFA19 AFIFA19 EAFIFA19 EFL AFIFA19 AFIFA19",
		"PA FIFA19 AFIFA19 EAFIFR19 AFIFA19 FAFIFA19",
		"LEASUETW RA FIFA19 AFIFA19 EA FIFR19 EFL GA FIFA19 AFIFA19",
		"LEASUETW PA FIFR19 EFL AFIFA19 EAFIFA19 EFL AFIFA19 AFIFA19",
		"PA FIFA19 AFIFA19 EAFIFA19 EFL A FIFA19 AFIFA19",
	])("removes only the repeated sponsor footer: %s", (footer) => {
		const event = {
			event_type: "player_of_the_month",
			description: `${body} ${footer}`,
		};
		expect(eventDescription(event)).toBe(body);
		expect(event.description).toContain(footer);
	});
	it.each([
		"An award in FIFA 19.",
		"An award in FIFA19",
		"FIFA19 and FIFA19 players celebrate.",
		"Award confirmed. PA",
		"EFL League One champions",
		"",
	])('preserves legitimate article text "%s"', (description) => {
		expect(eventDescription({ description })).toBe(description);
	});
	it("cleans event cards without changing the archived source", () => {
		const event = {
			...fixture.competition_events[0],
			description: `${body} PA FIFA19 AFIFA19 EAFIFA19`,
			event_type: "player_of_the_month",
			player_id: fixture.players[0].id,
			period: "2018-08",
		};
		const model = createModel({ ...fixture, competition_events: [event] });
		const html = render(model, "records");
		expect(html).toContain(body);
		expect(html).not.toContain("AFIFA19");
		expect(model.data.competition_events[0].description).toBe(
			event.description,
		);
		expect(
			eventDescription({
				event_type: "golden_boot",
				description: "ZokoWinsGoldenBoot.",
			}),
		).toBe("Zoko wins Golden Boot.");
		expect(eventDescription({})).toBe("");
	});
});
