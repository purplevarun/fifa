import { splitJoinedWords } from "./vocabulary";

export type Row = Record<string, unknown>;
export interface Entity extends Row {
	id: string;
}
export interface Player extends Entity {
	name: string;
	nationality: string | null;
}
export interface Club extends Entity {
	name: string;
}
export interface Season extends Entity {
	label: string;
}
export interface Competition extends Entity {
	name: string;
	kind: string;
	is_preseason: boolean;
}
export interface Edition extends Entity {
	competition_id: string;
	season_id: string;
}
export interface Fixture extends Entity {
	competition_season_id: string;
	played_on: string;
	home_club_id: string;
	away_club_id: string;
	home_goals: number | null;
	away_goals: number | null;
	home_penalties: number | null;
	away_penalties: number | null;
	venue: string | null;
	duration_minutes: number | null;
	extra_time: boolean | null;
	round: string | null;
}
export interface Performance extends Entity {
	player_id: string;
	club_id: string;
	match_id: string;
	rating: number | null;
	overall: number | null;
	displayed_position: string | null;
	goals: number | null;
	goals_assumed_zero?: boolean;
	assists: number | null;
	minutes_played: number | null;
	goals_conceded: number | null;
	goals_conceded_displayed: number | null;
}
export interface Snapshot extends Entity {
	player_id: string;
	club_id: string | null;
	season_id: string;
	match_id: string | null;
	overall: number | null;
	displayed_position: string | null;
	snapshot_kind: string;
	observed_on: string | null;
	date_precision: string;
}
export interface MetricComparison {
	observed: number | null;
	derived: number | null;
	result: string;
	difference: number | null;
	missing_match_values: number;
	assumed_zero_match_values?: number;
	raw_match_average?: number | null;
	display_rule?: string;
}
export interface Comparison extends Row {
	snapshot_id: string;
	player_id: string;
	player: string;
	season: string;
	competition: string | null;
	scope: string;
	result: string;
	metrics: Record<string, MetricComparison>;
}
export interface Dataset {
	schema_version: number;
	generated_at: string;
	data_source?: { label: string; preview: boolean };
	processing?: {
		last_run: {
			id: string;
			completed_at: string;
			mode: "incremental" | "reextract" | "clean";
			status: "completed" | "partial";
			extracted_images: number;
			imported_sources: number;
			skipped_sources: number;
			extraction_errors: number;
		} | null;
		last_extracted_at: string | null;
	};
	players: Player[];
	clubs: Club[];
	seasons: Season[];
	competitions: Competition[];
	competition_seasons: Edition[];
	matches: Fixture[];
	team_matches: Entity[];
	player_matches: Performance[];
	player_snapshots: Snapshot[];
	player_competition_snapshots: Entity[];
	player_transfers: Entity[];
	competition_events: Entity[];
	coverage: {
		records: Record<string, number>;
	};
	match_coverage: {
		summary: Row;
		matches?: Row[];
		warnings: Row[];
		player_field_availability: Row;
	};
	season_reconciliation: {
		summary: Row;
		comparisons: Comparison[];
		limitations: string[];
	};
}
export interface Match extends Fixture {
	home: string;
	away: string;
	competition: Competition;
	season: Season;
	isHome: boolean;
	opponent: string;
	goalsFor: number | null;
	goalsAgainst: number | null;
	result: "W" | "D" | "L" | null;
	shootout: "W" | "L" | null;
}
export interface Model {
	data: Dataset;
	nottsId: string;
	players: Map<string, Player>;
	clubs: Map<string, Club>;
	competitions: Map<string, Competition>;
	seasons: Map<string, Season>;
	editions: Map<string, Edition>;
	matches: Match[];
	matchById: Map<string, Match>;
}
export interface Filters {
	season: string;
	competition: string;
	preseason: boolean;
}
export const defaultFilters: Filters = {
	season: "all",
	competition: "all",
	preseason: true,
};
const index = <Value extends Entity>(values: Value[]) =>
	new Map(values.map((value) => [value.id, value]));

export function createModel(input: unknown): Model {
	if (!input || typeof input !== "object")
		throw new Error("The career export is not valid JSON data.");
	const data = input as Dataset;
	const tables = [
		"players",
		"clubs",
		"seasons",
		"competitions",
		"competition_seasons",
		"matches",
		"team_matches",
		"player_matches",
		"player_snapshots",
		"player_competition_snapshots",
		"player_transfers",
		"competition_events",
	] as const;
	if (
		![3, 4].includes(data.schema_version) ||
		tables.some((table) => !Array.isArray(data[table]))
	)
		throw new Error("The local stats use an unsupported schema-version.");
	const notts = data.clubs.find((club) => club.name === "Notts County");
	if (!notts && data.matches.length)
		throw new Error("Notts County is missing from the career export.");
	const clubs = index(data.clubs),
		players = index(data.players),
		competitions = index(data.competitions);
	const seasons = index(data.seasons),
		editions = index(data.competition_seasons);
	const matches: Match[] = data.matches
		.map((fixture): Match => {
			const edition = editions.get(fixture.competition_season_id);
			const competition =
				edition && competitions.get(edition.competition_id);
			const season = edition && seasons.get(edition.season_id);
			const home = clubs.get(fixture.home_club_id)?.name,
				away = clubs.get(fixture.away_club_id)?.name;
			if (!competition || !season || !home || !away)
				throw new Error(`Broken fixture relationship: ${fixture.id}`);
			const isHome = fixture.home_club_id === notts?.id;
			const goalsFor = isHome ? fixture.home_goals : fixture.away_goals;
			const goalsAgainst = isHome
				? fixture.away_goals
				: fixture.home_goals;
			const penaltiesFor = isHome
				? fixture.home_penalties
				: fixture.away_penalties;
			const penaltiesAgainst = isHome
				? fixture.away_penalties
				: fixture.home_penalties;
			return {
				...fixture,
				home,
				away,
				competition,
				season,
				isHome,
				opponent: isHome ? away : home,
				goalsFor,
				goalsAgainst,
				result:
					goalsFor === null || goalsAgainst === null
						? null
						: goalsFor > goalsAgainst
							? "W"
							: goalsFor < goalsAgainst
								? "L"
								: "D",
				shootout:
					penaltiesFor === null || penaltiesAgainst === null
						? null
						: penaltiesFor > penaltiesAgainst
							? "W"
							: "L",
			};
		})
		.sort(
			(left, right) =>
				left.played_on.localeCompare(right.played_on) ||
				left.id.localeCompare(right.id),
		);
	return {
		data,
		nottsId: notts?.id ?? "",
		clubs,
		players,
		competitions,
		seasons,
		editions,
		matches,
		matchById: index(matches),
	};
}

export function selectMatches(model: Model, filters: Filters): Match[] {
	return model.matches.filter(
		(match) =>
			(filters.season === "all" || match.season.id === filters.season) &&
			(filters.competition === "all" ||
				match.competition.id === filters.competition) &&
			(filters.preseason || !match.competition.is_preseason),
	);
}
export function selectPerformances(
	model: Model,
	matches: Match[],
	clubId: string | null = model.nottsId,
): Performance[] {
	const ids = new Set(matches.map((match) => match.id));
	return model.data.player_matches.filter(
		(row) =>
			ids.has(row.match_id) &&
			(clubId === null || row.club_id === clubId),
	);
}
export function metric(rows: Row[], field: string | readonly string[]) {
	const fields = typeof field === "string" ? [field] : field;
	const values = rows
		.map((row) => {
			if (!fields.length) return null;
			let total = 0;
			for (const component of fields) {
				const value = row[component];
				if (typeof value !== "number" || !Number.isFinite(value))
					return null;
				total += value;
			}
			return total;
		})
		.filter(
			(value): value is number =>
				typeof value === "number" && Number.isFinite(value),
		);
	return {
		value: values.length
			? values.reduce((total, value) => total + value, 0)
			: null,
		known: values.length,
		total: rows.length,
	};
}
export function average(rows: Row[], field: string) {
	const result = metric(rows, field);
	return result.value === null ? null : result.value / result.known;
}
export function summarize(matches: Match[]) {
	const wins = matches.filter((match) => match.result === "W").length;
	const draws = matches.filter((match) => match.result === "D").length;
	const losses = matches.filter((match) => match.result === "L").length;
	return {
		played: matches.length,
		wins,
		draws,
		losses,
		goalsFor: metric(matches, "goalsFor"),
		goalsAgainst: metric(matches, "goalsAgainst"),
		cleanSheets: matches.filter((match) => match.goalsAgainst === 0).length,
		winRate:
			wins + draws + losses
				? (wins / (wins + draws + losses)) * 100
				: null,
		leaguePoints: matches
			.filter((match) => match.competition.kind === "league")
			.reduce(
				(total, match) =>
					total +
					(match.result === "W" ? 3 : match.result === "D" ? 1 : 0),
				0,
			),
	};
}
export function snapshotOrder(snapshot: Snapshot, model: Model) {
	if (snapshot.observed_on) return snapshot.observed_on;
	const season = model.seasons.get(snapshot.season_id)?.label ?? "0000/00";
	return snapshot.snapshot_kind === "season_end"
		? `${Number(season.slice(0, 4)) + 1}-06-30`
		: `${season.slice(0, 4)}-07-01`;
}
export function playerSummary(
	model: Model,
	player: Player,
	matches: Match[],
	clubId: string | null = model.nottsId,
) {
	const rows = selectPerformances(model, matches, clubId).filter(
		(row) => row.player_id === player.id,
	);
	const seasons = new Set(matches.map((match) => match.season.id));
	const snapshots = model.data.player_snapshots
		.filter(
			(row) => row.player_id === player.id && seasons.has(row.season_id),
		)
		.sort((left, right) =>
			snapshotOrder(left, model).localeCompare(
				snapshotOrder(right, model),
			),
		);
	const last = snapshots.at(-1);
	return {
		...player,
		rows,
		appearances: rows.length,
		goals: metric(rows, "goals"),
		assists: metric(rows, "assists"),
		rating: average(rows, "rating"),
		overall: last?.overall ?? rows.at(-1)?.overall ?? null,
		position:
			last?.displayed_position ?? rows.at(-1)?.displayed_position ?? null,
		snapshots,
	};
}
export type OverviewStatistic =
	| "goals"
	| "assists"
	| "appearances"
	| "passes_completed"
	| "tackles_won"
	| "rating";

export interface PlayerRanking {
	id: string;
	name: string;
	value: number;
	known: number;
	total: number;
}

export function overviewRankings(model: Model, matches: Match[]) {
	const players = model.data.players
		.map((player) => playerSummary(model, player, matches))
		.filter((player) => player.appearances > 0);
	const statistics: OverviewStatistic[] = [
		"goals",
		"assists",
		"appearances",
		"passes_completed",
		"tackles_won",
		"rating",
	];
	return Object.fromEntries(
		statistics.map((statistic) => [
			statistic,
			players
				.flatMap((player) => {
					const measured =
						statistic === "appearances"
							? {
									value: player.appearances,
									known: player.appearances,
									total: player.appearances,
								}
							: performanceMetric(player.rows, statistic);
					const value =
						statistic === "rating" ? player.rating : measured.value;
					return value === null
						? []
						: [
								{
									id: player.id,
									name: player.name,
									value,
									known: measured.known,
									total: measured.total,
								},
							];
				})
				.sort(
					(left, right) =>
						right.value - left.value ||
						left.name.localeCompare(right.name) ||
						left.id.localeCompare(right.id),
				)
				.slice(0, 5),
		]),
	) as Record<OverviewStatistic, PlayerRanking[]>;
}

export function referenceLabel(
	model: Model,
	field: string,
	value: unknown,
): string {
	if (typeof value !== "string") return display(value);
	if (field === "player_id") return model.players.get(value)?.name ?? value;
	if (field.endsWith("club_id")) return model.clubs.get(value)?.name ?? value;
	if (field === "season_id") return model.seasons.get(value)?.label ?? value;
	if (field === "competition_id")
		return model.competitions.get(value)?.name ?? value;
	if (field === "competition_season_id") {
		const edition = model.editions.get(value);
		return edition
			? `${model.competitions.get(edition.competition_id)?.name} ${model.seasons.get(edition.season_id)?.label}`
			: value;
	}
	if (field === "match_id") {
		const match = model.matchById.get(value);
		return match
			? `${match.played_on} ${match.home} ${match.home_goals ?? "-"}-${match.away_goals ?? "-"} ${match.away}`
			: value;
	}
	return value;
}
export function display(value: unknown, digits = 0): string {
	if (value === null || value === undefined || value === "") return "-";
	if (typeof value === "number")
		return value.toLocaleString("en-GB", {
			minimumFractionDigits: digits,
			maximumFractionDigits: digits,
		});
	if (typeof value === "boolean") return value ? "Yes" : "No";
	return String(value);
}
export function dateLabel(value: string | null, short = false) {
	if (!value) return "Date not recorded";
	return new Date(`${value}T12:00:00`).toLocaleDateString("en-GB", {
		day: "numeric",
		month: short ? "short" : "long",
		...(short ? {} : { year: "numeric" }),
	});
}
export function label(value: string) {
	return value
		.replace(/_/g, " ")
		.replace(/\b\w/g, (character) => character.toUpperCase())
		.replace(/\bPct\b/g, "%")
		.replace(/\bId\b/g, "ID");
}
export function eventDescription(event: Row): string {
	let text = typeof event.description === "string" ? event.description : "";
	// Older exports included sponsor-board logos below the news article. Only
	// remove a trailing run of known logo tokens with at least two FIFA marks.
	const tail = text.match(
		/(?:^|\s)(?:(?:[A-Z]{0,3}FIF[AR]\s*19|PA|RA|GA|EA|EFL|LEASUETW|A)\s*)+$/,
	);
	if (tail && (tail[0].match(/FIF[AR]\s*19/g)?.length ?? 0) >= 2)
		text = text.slice(0, tail.index).trimEnd();
	text = splitJoinedWords(text);
	return event.event_type === "golden_boot"
		? text.replace(/\s*Wins\s*Golden\s*Boot\b/i, " wins Golden Boot")
		: text;
}
export function downloadJson(value: unknown, filename: string) {
	const blob = new Blob([JSON.stringify(value, null, 2)], {
		type: "application/json",
	});
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.href = url;
	link.download = filename;
	link.click();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const performanceGroups: Record<string, string[]> = {
	"Match record": [
		"rating",
		"overall",
		"displayed_position",
		"played_position",
		"started",
		"minutes_played",
	],
	Attacking: [
		"goals",
		"assists",
		"shots_on_target",
		"shots_off_target",
		"shot_accuracy_pct",
		"key_passes",
	],
	Passing: [
		"passes_completed_short",
		"passes_completed_medium",
		"passes_completed_long",
		"passes_failed_short",
		"passes_failed_medium",
		"passes_failed_long",
		"crosses_successful",
		"crosses_failed",
		"pass_accuracy_pct",
	],
	Defending: [
		"tackles_won",
		"tackles_lost",
		"tackle_accuracy_pct",
		"fouls",
		"penalties_conceded",
		"interceptions",
		"blocks",
		"out_of_position",
		"clearances",
		"headers_won",
		"headers_lost",
	],
	"Possession & movement": [
		"possession_won",
		"possession_lost",
		"key_dribbles",
		"fouled",
		"successful_dribbles",
	],
	Goalkeeping: [
		"goals_conceded",
		"goals_conceded_displayed",
		"goals_conceded_basis",
		"shots_caught",
		"shots_parried",
		"crosses_caught",
		"balls_stripped",
	],
};

const completedPassFields = [
	"passes_completed_short",
	"passes_completed_medium",
	"passes_completed_long",
];
const failedPassFields = [
	"passes_failed_short",
	"passes_failed_medium",
	"passes_failed_long",
];
const combinedPerformanceFields: Record<string, string[]> = {
	passes_completed: completedPassFields,
	passes_failed: failedPassFields,
	passes_attempted: [...completedPassFields, ...failedPassFields],
};

export function performanceMetric(rows: Row[], field: string) {
	return metric(rows, combinedPerformanceFields[field] ?? field);
}

export const seasonStatGroups: Record<string, string[]> = Object.fromEntries(
	Object.entries(performanceGroups)
		.filter(([group]) => group !== "Match record")
		.map(([group, fields]) => {
			const counts = fields.filter(
				(field) =>
					!field.endsWith("_pct") &&
					!field.endsWith("_basis") &&
					field !== "goals_conceded_displayed" &&
					field !== "key_passes",
			);
			return [
				group,
				group === "Passing"
					? [
							"passes_completed",
							"passes_attempted",
							"passes_failed",
							"key_passes",
							...counts,
						]
					: counts,
			];
		}),
);
