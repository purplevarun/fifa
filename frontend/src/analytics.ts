import type { Match, Model, Performance, Row } from "./data";
import { metric, performanceMetric, selectPerformances } from "./data";

// One appearance, not one screenshot. The exporter enforces this key too.
function appearances(model: Model, matches: Match[]) {
	const seen = new Set<string>();
	return selectPerformances(model, matches).filter((row) => {
		const key = `${row.player_id}:${row.match_id}`;
		if (seen.has(key)) return false;
		seen.add(key);
		return true;
	});
}

const isCount = (value: unknown): value is number =>
	typeof value === "number" && Number.isInteger(value) && value >= 0;

export interface ScoringRow extends Row {
	id: string;
	player_id: string;
	name: string;
	season: string;
	braces: number;
	hat_tricks: number;
}

export function scoringFeats(model: Model, matches: Match[]) {
	const rows = appearances(model, matches);
	const seasonal = new Map<string, ScoringRow>();
	const career = new Map<string, ScoringRow>();
	const hatTricks: {
		id: string;
		player_id: string;
		name: string;
		goals: number;
		match: Match;
	}[] = [];
	for (const row of rows) {
		if (!isCount(row.goals) || row.goals < 2) continue;
		const match = model.matchById.get(row.match_id);
		if (!match) continue;
		const name = model.players.get(row.player_id)?.name ?? "Unknown player";
		for (const [group, id, season] of [
			[
				seasonal,
				`${row.player_id}:${match.season.id}`,
				match.season.label,
			],
			[career, row.player_id, ""],
		] as const) {
			const current = group.get(id) ?? {
				id,
				player_id: row.player_id,
				name,
				season,
				braces: 0,
				hat_tricks: 0,
			};
			if (row.goals === 2) current.braces += 1;
			// Four or more goals still count as ONE hat-trick performance.
			if (row.goals >= 3) current.hat_tricks += 1;
			group.set(id, current);
		}
		if (row.goals >= 3) {
			hatTricks.push({
				id: `${row.player_id}:${match.id}`,
				player_id: row.player_id,
				name,
				goals: row.goals,
				match,
			});
		}
	}
	const recorded = rows.filter((row) => isCount(row.goals));
	return {
		seasonal: [...seasonal.values()],
		career: [...career.values()],
		hatTricks: hatTricks.sort(
			(left, right) =>
				right.match.played_on.localeCompare(left.match.played_on) ||
				left.name.localeCompare(right.name) ||
				left.id.localeCompare(right.id),
		),
		total: rows.length,
		known: recorded.length,
		assumedZero: recorded.filter((row) => row.goals_assumed_zero).length,
		missingLineups: matches.filter(
			(match) =>
				rows.filter((row) => row.match_id === match.id).length < 11,
		).length,
	};
}

export type AwardRole =
	"forward" | "playmaker" | "midfielder" | "defender" | "goalkeeper";
export const awardScoring = {
	contribution: 60,
	perGame: 25,
	games: 15,
	minimumCoverage: 0.8,
	provisionalAppearances: 5,
} as const;

interface ScoreMetric {
	field: string;
	label: string;
	weight: number;
	lowerIsBetter?: boolean;
}
interface PositionDefinition {
	role: AwardRole;
	title: string;
	color: string;
	metrics: ScoreMetric[];
}

export const positionDefinitions: PositionDefinition[] = [
	{
		role: "forward",
		title: "Best forward",
		color: "#276f54",
		metrics: [
			{ field: "goals", label: "Goals", weight: 80 },
			{ field: "assists", label: "Assists", weight: 20 },
		],
	},
	{
		role: "playmaker",
		title: "Best playmaker",
		color: "#76519a",
		metrics: [
			{ field: "goals", label: "Goals", weight: 50 },
			{ field: "assists", label: "Assists", weight: 50 },
		],
	},
	{
		role: "midfielder",
		title: "Best midfielder",
		color: "#356a9a",
		metrics: [
			{
				field: "passes_completed",
				label: "Completed passes",
				weight: 40,
			},
			{ field: "key_passes", label: "Key passes", weight: 50 },
			{ field: "tackles_won", label: "Tackles won", weight: 10 },
		],
	},
	{
		role: "defender",
		title: "Best defender",
		color: "#a04d67",
		metrics: [
			{ field: "tackles_won", label: "Tackles won", weight: 45 },
			{
				field: "defensive_actions",
				label: "Interceptions + blocks + clearances",
				weight: 45,
			},
			{
				field: "passes_completed",
				label: "Completed passes",
				weight: 10,
			},
		],
	},
	{
		role: "goalkeeper",
		title: "Best goalkeeper",
		color: "#9d731b",
		metrics: [
			{ field: "saves", label: "Saves (caught + parried)", weight: 50 },
			{ field: "clean_sheets", label: "Clean sheets", weight: 30 },
			{
				field: "goals_conceded",
				label: "Goals conceded (lower is better)",
				weight: 20,
				lowerIsBetter: true,
			},
		],
	},
];

function scoreValue(row: Performance, field: string) {
	if (field === "clean_sheets")
		return isCount(row.goals_conceded)
			? Number(row.goals_conceded === 0)
			: null;
	const combined: Record<string, string[]> = {
		saves: ["shots_caught", "shots_parried"],
		defensive_actions: ["interceptions", "blocks", "clearances"],
	};
	const result = combined[field]
		? metric([row], combined[field])
		: performanceMetric([row], field);
	// Invalid components must not cancel out into a plausible combined count.
	const fields =
		combined[field] ??
		(field === "passes_completed"
			? [
					"passes_completed_short",
					"passes_completed_medium",
					"passes_completed_long",
				]
			: [field]);
	return fields.every((key) => isCount(row[key])) ? result.value : null;
}

export interface PositionCandidate {
	id: string;
	name: string;
	score: number;
	known: number;
	total: number;
	breakdown: { contribution: number; perGame: number; games: number };
	metrics: (ScoreMetric & {
		total: number;
		perAppearance: number;
		contributionPoints: number;
		perGamePoints: number;
		points: number;
	})[];
}

function metricImpact(
	metric: PositionCandidate["metrics"][number],
	games: number,
) {
	// Conceding more must never earn more points. Invert the conceded rate,
	// then multiply by recorded games for its accumulated contribution.
	const perGame = metric.lowerIsBetter
		? 1 / (1 + metric.perAppearance)
		: metric.perAppearance;
	return {
		contribution: metric.lowerIsBetter ? perGame * games : metric.total,
		perGame,
	};
}

export function positionRankings(model: Model, matches: Match[]) {
	const rows = appearances(model, matches);
	// Awards describe statistical contributions, not the player's position.
	const grouped = new Map<string, Performance[]>();
	for (const row of rows) {
		const current = grouped.get(row.player_id) ?? [];
		current.push(row);
		grouped.set(row.player_id, current);
	}
	const roles = positionDefinitions.map((definition) => {
		const candidates: PositionCandidate[] = [];
		let insufficientDataPlayers = 0;
		let noContributionPlayers = 0;
		for (const [id, playerRows] of grouped) {
			// Use the SAME complete appearances for every component of a score.
			const complete = playerRows
				.map((row) =>
					definition.metrics.map((component) =>
						scoreValue(row, component.field),
					),
				)
				.filter((values): values is number[] =>
					values.every((value) => value !== null),
				);
			if (
				!complete.length ||
				complete.length / playerRows.length <
					awardScoring.minimumCoverage
			) {
				insufficientDataPlayers += 1;
				continue;
			}
			const candidate: PositionCandidate = {
				id,
				name: model.players.get(id)?.name ?? "Unknown player",
				known: complete.length,
				total: playerRows.length,
				score: 0,
				breakdown: { contribution: 0, perGame: 0, games: 0 },
				metrics: definition.metrics.map((component, index) => {
					const total = complete.reduce(
						(sum, values) => sum + values[index],
						0,
					);
					return {
						...component,
						total,
						perAppearance: total / complete.length,
						contributionPoints: 0,
						perGamePoints: 0,
						points: 0,
					};
				}),
			};
			// Playing games alone cannot win an award with no measured contribution.
			if (
				candidate.metrics.every(
					(metric) =>
						metricImpact(metric, candidate.known).contribution ===
						0,
				)
			) {
				noContributionPlayers += 1;
				continue;
			}
			candidates.push(candidate);
		}
		for (const [index, component] of definition.metrics.entries()) {
			const impacts = candidates.map((player) =>
				metricImpact(player.metrics[index], player.known),
			);
			const bestContribution = Math.max(
				0,
				...impacts.map((impact) => impact.contribution),
			);
			const bestPerGame = Math.max(
				0,
				...impacts.map((impact) => impact.perGame),
			);
			for (const player of candidates) {
				const value = player.metrics[index];
				const impact = metricImpact(value, player.known);
				value.contributionPoints =
					bestContribution > 0
						? (((awardScoring.contribution * component.weight) /
								100) *
								impact.contribution) /
							bestContribution
						: 0;
				value.perGamePoints =
					bestPerGame > 0
						? (((awardScoring.perGame * component.weight) / 100) *
								impact.perGame) /
							bestPerGame
						: 0;
				value.points = value.contributionPoints + value.perGamePoints;
				player.breakdown.contribution += value.contributionPoints;
				player.breakdown.perGame += value.perGamePoints;
			}
		}
		const mostGames = Math.max(
			0,
			...candidates.map((player) => player.known),
		);
		for (const player of candidates) {
			player.breakdown.games =
				(awardScoring.games * player.known) / mostGames;
			player.score =
				player.breakdown.contribution +
				player.breakdown.perGame +
				player.breakdown.games;
		}
		const ranked = candidates
			.filter((player) => player.score > 0)
			.sort(
				(left, right) =>
					right.score - left.score ||
					right.known - left.known ||
					left.name.localeCompare(right.name) ||
					left.id.localeCompare(right.id),
			);
		return {
			...definition,
			candidates: ranked,
			insufficientDataPlayers,
			noContributionPlayers,
			consideredPlayers: grouped.size,
		};
	});
	return { roles };
}
