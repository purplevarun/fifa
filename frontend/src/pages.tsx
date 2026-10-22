import {
	ArrowLeft,
	ArrowRight,
	ArrowUpRight,
	CalendarDays,
	Clock3,
	Database,
	MapPin,
	Shield,
	Trophy,
} from "lucide-react";
import { type CSSProperties, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { RankingChart, TrendChart } from "./charts";
import { useCareer } from "./context";
import type { Match, Performance, Row } from "./data";
import {
	dateLabel,
	display,
	label,
	overviewRankings,
	performanceGroups,
	performanceMetric,
	playerSummary,
	seasonStatGroups,
	selectMatches,
	snapshotOrder,
	summarize,
} from "./data";
import type { Column } from "./ui";
import {
	CareerLink,
	DataTable,
	Empty,
	Kpis,
	Modal,
	PageHeading,
	Pill,
	RecordDetails,
	Result,
	SectionHeading,
	StatValue,
} from "./ui";

function Score({ match }: { match: Match }) {
	return (
		<span className="score-cell">
			<strong>
				{display(match.home_goals)} <span className="muted">-</span>{" "}
				{display(match.away_goals)}
			</strong>
			{match.home_penalties !== null && (
				<small>
					{match.home_penalties}-{match.away_penalties} pens
				</small>
			)}
			{match.extra_time && <small>AET</small>}
		</span>
	);
}
export function MatchTable({
	matches,
	compact = false,
}: {
	matches: Match[];
	compact?: boolean;
}) {
	const columns: Column<Match>[] = [
		{
			key: "played_on",
			title: "Date",
			render: (match) => (
				<span className="nowrap">
					{dateLabel(match.played_on, true)}{" "}
					<small className="muted">
						{match.played_on.slice(0, 4)}
					</small>
				</span>
			),
		},
		{
			key: "opponent",
			title: "Fixture",
			render: (match) => (
				<CareerLink
					to={`/matches/${match.id}`}
					className="fixture-link"
				>
					<span>{match.home}</span>
					<span className="versus">v</span>
					<span>{match.away}</span>
				</CareerLink>
			),
		},
		{
			key: "home_goals",
			title: "Score",
			render: (match) => (
				<CareerLink to={`/matches/${match.id}`}>
					<Score match={match} />
				</CareerLink>
			),
			numeric: true,
		},
		{
			key: "result",
			title: "Result",
			render: (match) => <Result match={match} />,
		},
		{
			key: "competition",
			title: "Competition",
			value: (match) => match.competition.name,
			render: (match) => (
				<div className="stack">
					<CareerLink to={`/competitions/${match.competition.id}`}>
						{match.competition.name}
					</CareerLink>
					{match.competition.is_preseason && (
						<span className="tiny muted">Preseason</span>
					)}
				</div>
			),
		},
	];
	if (compact)
		return (
			<div className="compact-fixtures">
				{[...matches]
					.reverse()
					.slice(0, 5)
					.map((match) => (
						<div className="compact-fixture" key={match.id}>
							<Result match={match} />
							<CareerLink to={`/matches/${match.id}`}>
								<strong>{match.opponent}</strong>
								<small>
									{dateLabel(match.played_on, true)} /{" "}
									{match.isHome ? "Home" : "Away"}
								</small>
							</CareerLink>
							<Score match={match} />
							<CareerLink
								to={`/matches/${match.id}`}
								className="icon-button"
								title="Open match"
							>
								<ArrowRight size={17} />
							</CareerLink>
						</div>
					))}
			</div>
		);
	return (
		<DataTable
			rows={matches}
			columns={columns}
			rowKey={(match) => match.id}
			defaultSort={{ key: "played_on", desc: true }}
			searchLabel="Search fixtures or opponents"
			searchText={(match) =>
				`${match.home} ${match.away} ${match.competition.name} ${match.played_on} ${match.venue}`
			}
			exportName="matches.json"
		/>
	);
}

const overviewCharts = [
	{
		statistic: "goals",
		title: "Leading scorers",
		name: "Goals",
		color: "#276f54",
		variant: "bar",
	},
	{
		statistic: "assists",
		title: "Most assists",
		name: "Assists",
		color: "#356a9a",
		variant: "bar",
	},
	{
		statistic: "appearances",
		title: "Most appearances",
		name: "Appearances",
		color: "#555b66",
		variant: "bar",
	},
	{
		statistic: "passes_completed",
		title: "Most passes completed",
		name: "Completed passes",
		color: "#167d7f",
		variant: "bar",
	},
	{
		statistic: "tackles_won",
		title: "Most tackles won",
		name: "Tackles won",
		color: "#a04d67",
		variant: "lollipop",
	},
	{
		statistic: "rating",
		title: "Highest rated players",
		name: "Average match rating",
		color: "#9d731b",
		variant: "rating",
	},
] as const;

export function Overview() {
	const { model, matches } = useCareer();
	const summary = summarize(matches);
	const rankings = overviewRankings(model, matches);
	const latest = matches.at(-1);
	const processing = model.data.processing;
	const lastRun = processing?.last_run;
	const processedAt = lastRun?.completed_at ?? processing?.last_extracted_at;
	const processedDate = processedAt ? new Date(processedAt) : null;
	const timestampAvailable =
		processedDate !== null && Number.isFinite(processedDate.getTime());
	const source = model.data.data_source;
	return (
		<>
			<PageHeading
				title="Career overview"
				eyebrow="Notts County / FIFA 19"
			>
				<Pill tone="positive">{matches.length} recorded matches</Pill>
			</PageHeading>
			<div className="processing-strip" aria-label="Dataset processing">
				<span
					className={`processing-source${source?.preview ? " preview" : ""}`}
				>
					<Database size={14} />
					{source?.label ?? "dashboard.json"}
				</span>
				<span
					className="processing-time"
					title={
						!lastRun && timestampAvailable
							? "Last saved OCR result; this export has no processing-run completion time."
							: undefined
					}
				>
					<Clock3 size={14} />
					<span>
						{lastRun || !timestampAvailable
							? "Last processed: "
							: "Last OCR saved: "}
						{timestampAvailable ? (
							<time dateTime={processedAt ?? undefined}>
								{processedDate.toLocaleString("en-GB", {
									day: "numeric",
									month: "short",
									year: "numeric",
									hour: "2-digit",
									minute: "2-digit",
									timeZoneName: "short",
								})}
							</time>
						) : (
							"Not recorded"
						)}
					</span>
				</span>
				{lastRun && lastRun.skipped_sources > 0 && (
					<span className="processing-issues">
						{display(lastRun.skipped_sources)} sources not imported
					</span>
				)}
				{lastRun && lastRun.extraction_errors > 0 && (
					<span className="processing-issues">
						{display(lastRun.extraction_errors)} OCR errors
					</span>
				)}
			</div>
			<Kpis
				items={[
					{
						label: "Played",
						value: summary.played,
						detail: `${summary.wins} wins / ${summary.draws} draws / ${summary.losses} losses`,
					},
					{
						label: "Goals scored",
						value: <StatValue {...summary.goalsFor} />,
						detail: `${display(summary.goalsAgainst.value)} conceded`,
					},
					{
						label: "Win rate",
						value: (
							<>
								{display(summary.winRate, 1)}
								<span className="unit">%</span>
							</>
						),
						detail: "Match results before shootouts",
					},
					{
						label: "Clean sheets",
						value: summary.cleanSheets,
						detail: `${matches.filter((match) => match.competition.is_preseason).length} preseason fixtures included`,
					},
				]}
			/>
			{!matches.length ? (
				<Empty />
			) : (
				<>
					<div className="overview-charts">
						{overviewCharts.map((chart, index) => (
							<section
								className="overview-ranking"
								key={chart.statistic}
								aria-label={chart.title}
								data-statistic={chart.statistic}
								style={
									{
										"--ranking-accent": chart.color,
										animationDelay: `${index * 40}ms`,
									} as CSSProperties
								}
							>
								<div className="ranking-kicker">
									{chart.statistic === "rating"
										? "Top 5 / average match rating"
										: "Top 5"}
								</div>
								<SectionHeading title={chart.title}>
									<CareerLink
										to={
											chart.statistic ===
												"passes_completed" ||
											chart.statistic === "tackles_won"
												? `/players?stat=${chart.statistic}`
												: "/players"
										}
										className="icon-button ranking-link"
										aria-label={`View players: ${chart.title.toLowerCase()}`}
										title={`View players: ${chart.title.toLowerCase()}`}
									>
										<ArrowUpRight size={16} />
									</CareerLink>
								</SectionHeading>
								<RankingChart
									rows={rankings[chart.statistic]}
									name={chart.name}
									color={chart.color}
									variant={chart.variant}
									digits={
										chart.statistic === "rating" ? 2 : 0
									}
								/>
							</section>
						))}
					</div>
					<div className="overview-lower">
						<section>
							<SectionHeading title="Recent fixtures">
								<CareerLink
									to="/matches"
									className="small-link"
								>
									All fixtures <ArrowRight size={14} />
								</CareerLink>
							</SectionHeading>
							<MatchTable matches={matches} compact />
						</section>
						<section className="latest-match">
							<SectionHeading title="Latest match">
								<span className="tiny muted">
									{latest?.competition.name}
								</span>
							</SectionHeading>
							{latest && (
								<div className="latest-caption">
									<CareerLink to={`/matches/${latest.id}`}>
										<strong>
											{latest.home}{" "}
											{display(latest.home_goals)}-
											{display(latest.away_goals)}{" "}
											{latest.away}
										</strong>
									</CareerLink>
									<span>
										{dateLabel(latest.played_on)} /{" "}
										{latest.venue}
									</span>
								</div>
							)}
						</section>
					</div>
				</>
			)}
			<div className="archive-note">
				<span className="status-dot" />
				<strong>
					{model.data.match_coverage.summary.matches as number}{" "}
					fixtures verified
				</strong>
				<span>
					{display(model.data.player_matches.length)} player records
				</span>
				<CareerLink to="/audit">
					{model.data.match_coverage.warnings.length} reconciliation
					warning <ArrowRight size={14} />
				</CareerLink>
			</div>
		</>
	);
}

export function Matches() {
	const { matches } = useCareer();
	const [result, setResult] = useState("all");
	const selected = matches.filter(
		(match) => result === "all" || match.result === result,
	);
	return (
		<>
			<PageHeading title="Matches" eyebrow="Fixture archive">
				<div className="segmented" aria-label="Match result filter">
					{["all", "W", "D", "L"].map((value) => (
						<button
							key={value}
							className={result === value ? "active" : ""}
							aria-pressed={result === value}
							onClick={() => setResult(value)}
						>
							{value === "all" ? "All results" : value}
						</button>
					))}
				</div>
			</PageHeading>
			<MatchTable matches={selected} />
		</>
	);
}

export function PerformanceDialog({
	performance,
	onClose,
}: {
	performance: Performance;
	onClose: () => void;
}) {
	const { model } = useCareer();
	const match = model.matchById.get(performance.match_id);
	return (
		<Modal
			title={
				model.players.get(performance.player_id)?.name ??
				"Player performance"
			}
			onClose={onClose}
			wide
		>
			<div className="performance-summary">
				<div>
					<Pill>
						{performance.displayed_position ?? "Position unknown"}
					</Pill>
					<h3>
						{match?.home} {display(match?.home_goals)}-
						{display(match?.away_goals)} {match?.away}
					</h3>
					<p className="muted">
						{match && dateLabel(match.played_on)} /{" "}
						{match?.competition.name}
					</p>
				</div>
				<div className="rating-large">
					{display(performance.rating, 1)}
					<small>Match rating</small>
				</div>
			</div>
			<div className="detail-groups">
				{Object.entries(performanceGroups)
					.filter(
						([group]) =>
							group !== "Goalkeeping" ||
							performance.displayed_position === "GK",
					)
					.map(([group, fields]) => (
						<section key={group}>
							<h3>{group}</h3>
							<dl className="stats-list">
								{fields.map((field) => (
									<div key={field}>
										<dt>{label(field)}</dt>
										<dd
											title={
												field === "goals" &&
												performance.goals_assumed_zero
													? "Missing goalkeeper goals assumed zero"
													: performance[field] == null
														? "Not recorded or not applicable"
														: undefined
											}
										>
											{display(
												performance[field],
												field === "rating" ? 1 : 0,
											)}
										</dd>
									</div>
								))}
							</dl>
						</section>
					))}
			</div>
			<details className="metadata">
				<summary>Record metadata</summary>
				<RecordDetails record={performance} />
			</details>
		</Modal>
	);
}

export function MatchDetail() {
	const { id } = useParams();
	const { model } = useCareer();
	const match = id && model.matchById.get(id);
	const [club, setClub] = useState("notts");
	const [selected, setSelected] = useState<Performance | null>(null);
	if (!match) return <Empty title="Match not found" />;
	const performances = model.data.player_matches.filter(
		(row) => row.match_id === match.id,
	);
	const shown = performances.filter(
		(row) =>
			club === "all" ||
			(club === "notts"
				? row.club_id === model.nottsId
				: row.club_id !== model.nottsId),
	);
	const homeStats = model.data.team_matches.find(
		(row) =>
			row.match_id === match.id && row.club_id === match.home_club_id,
	);
	const awayStats = model.data.team_matches.find(
		(row) =>
			row.match_id === match.id && row.club_id === match.away_club_id,
	);
	const warnings = model.data.match_coverage.warnings.filter(
		(row) => row.match_id === match.id,
	);
	const columns: Column<Performance>[] = [
		{
			key: "player_id",
			title: "Player",
			value: (row) => model.players.get(row.player_id)?.name,
			render: (row) => (
				<span className="player-name">
					{model.players.get(row.player_id)?.name}
				</span>
			),
		},
		{
			key: "displayed_position",
			title: "Pos",
			render: (row) => (
				<span className="position">{row.displayed_position}</span>
			),
		},
		{ key: "overall", title: "OVR", numeric: true },
		{
			key: "rating",
			title: "Rating",
			numeric: true,
			render: (row) => (
				<span
					className={`rating ${Number(row.rating) >= 8 ? "high" : ""}`}
				>
					{display(row.rating, 1)}
				</span>
			),
		},
		{ key: "goals", title: "G", numeric: true },
		{ key: "assists", title: "A", numeric: true },
		{ key: "shots_on_target", title: "On target", numeric: true },
		{ key: "goals_conceded", title: "GK conceded", numeric: true },
		{
			key: "profile",
			title: "",
			sortable: false,
			render: (row) => (
				<CareerLink
					to={`/players/${row.player_id}`}
					className="small-link"
				>
					Profile <ArrowRight size={14} />
				</CareerLink>
			),
		},
	];
	return (
		<>
			<CareerLink to="/matches" className="back-link">
				<ArrowLeft size={15} />
				Matches
			</CareerLink>
			<PageHeading
				title={match.competition.name}
				eyebrow={`${match.season.label} / ${dateLabel(match.played_on)}`}
			>
				<Result match={match} />
				{match.competition.is_preseason && <Pill>Preseason</Pill>}
			</PageHeading>
			<section className="scoreboard">
				<div className="team-name">
					<span>Home</span>
					<h2>{match.home}</h2>
				</div>
				<div className="match-score">
					<strong>
						{display(match.home_goals)} <span>:</span>{" "}
						{display(match.away_goals)}
					</strong>
					<small>
						{match.home_penalties !== null
							? `${match.home_penalties}-${match.away_penalties} on penalties`
							: match.extra_time
								? "After extra time"
								: match.duration_minutes
									? `${match.duration_minutes} minutes`
									: "Duration not recorded"}
					</small>
				</div>
				<div className="team-name away">
					<span>Away</span>
					<h2>{match.away}</h2>
				</div>
			</section>
			<div className="match-meta">
				<span>
					<MapPin size={15} />
					{match.venue ?? "Venue not recorded"}
				</span>
				<span>
					<CalendarDays size={15} />
					{dateLabel(match.played_on)}
				</span>
				<div className="grow" />
			</div>
			{warnings.map((warning, index) => (
				<div className="notice warning" key={index}>
					<div>
						<strong>
							{display(
								warning.title ??
									label(
										String(warning.code ?? "data_warning"),
									),
							)}
						</strong>
						{warning.code === "player_goal_difference" && (
							<p>
								Team goals: {display(warning.team_goals)}.
								Credited player goals:{" "}
								{display(warning.credited_player_goals)}.
							</p>
						)}
						<p>
							{display(
								warning.detail ??
									"Details unavailable for this warning.",
							)}
						</p>
					</div>
				</div>
			))}
			<section className="section">
				<SectionHeading title="Match facts">
					<span className="tiny muted">
						{match.home} / {match.away}
					</span>
				</SectionHeading>
				<div className="team-comparisons">
					{[
						"possession_pct",
						"shots",
						"shots_on_target",
						"tackles",
						"fouls",
						"corners",
						"shot_accuracy_pct",
						"pass_accuracy_pct",
					].map((field) => {
						const home =
							typeof homeStats?.[field] === "number"
								? (homeStats[field] as number)
								: null;
						const away =
							typeof awayStats?.[field] === "number"
								? (awayStats[field] as number)
								: null;
						const total = (home ?? 0) + (away ?? 0);
						return (
							<div className="comparison-stat" key={field}>
								<div>
									<strong>
										{display(home)}
										{field.endsWith("_pct") && home !== null
											? "%"
											: ""}
									</strong>
									<span>{label(field)}</span>
									<strong>
										{display(away)}
										{field.endsWith("_pct") && away !== null
											? "%"
											: ""}
									</strong>
								</div>
								<div className="comparison-bars">
									<span>
										<i
											style={{
												width: `${total ? ((home ?? 0) / total) * 100 : 0}%`,
											}}
										/>
									</span>
									<span>
										<i
											style={{
												width: `${total ? ((away ?? 0) / total) * 100 : 0}%`,
											}}
										/>
									</span>
								</div>
							</div>
						);
					})}
				</div>
			</section>
			<section className="section">
				<SectionHeading title="Player performance">
					<div className="segmented">
						{[
							["notts", "Notts County"],
							["opponent", match.opponent],
							["all", "Both clubs"],
						].map(([value, title]) => (
							<button
								key={value}
								aria-pressed={club === value}
								className={club === value ? "active" : ""}
								onClick={() => setClub(value)}
							>
								{title}
							</button>
						))}
					</div>
				</SectionHeading>
				{shown.length ? (
					<DataTable
						rows={shown}
						columns={columns}
						rowKey={(row) => row.id}
						onSelect={setSelected}
						defaultSort={{ key: "rating", desc: true }}
						searchLabel="Search match players"
						searchText={(row) =>
							`${model.players.get(row.player_id)?.name} ${row.displayed_position}`
						}
						exportName={`match-${match.played_on}-players.json`}
					/>
				) : (
					<Empty title="No player-performance captures for this club" />
				)}
			</section>
			{selected && (
				<PerformanceDialog
					performance={selected}
					onClose={() => setSelected(null)}
				/>
			)}
		</>
	);
}

export function Players() {
	const { model, matches } = useCareer();
	const [parameters, setParameters] = useSearchParams();
	const requestedStatistic = parameters.get("stat") ?? "summary";
	const statistic = Object.values(seasonStatGroups)
		.flat()
		.includes(requestedStatistic)
		? requestedStatistic
		: "summary";
	const [opposition, setOpposition] = useState(false);
	const [position, setPosition] = useState("all");
	const players = model.data.players
		.map((player) => {
			const summary = playerSummary(
				model,
				player,
				matches,
				opposition ? null : model.nottsId,
			);
			return {
				...summary,
				statistic: performanceMetric(
					summary.rows,
					statistic === "summary" ? "goals" : statistic,
				),
			};
		})
		.filter(
			(player) =>
				player.appearances > 0 &&
				(position === "all" ||
					(position === "GK"
						? player.position?.includes("GK")
						: !player.position?.includes("GK"))),
		);
	type PlayerSummary = (typeof players)[number];
	const columns: Column<PlayerSummary>[] = [
		{
			key: "name",
			title: "Player",
			render: (player) => (
				<CareerLink
					to={`/players/${player.id}`}
					className="player-cell"
				>
					<span className="avatar">
						{player.name
							.split(" ")
							.map((part) => part[0])
							.slice(0, 2)
							.join("")}
					</span>
					<span>
						<strong>{player.name}</strong>
						<small>
							{player.nationality ?? "Nationality not recorded"}
						</small>
					</span>
				</CareerLink>
			),
		},
		{
			key: "position",
			title: "Position",
			render: (player) => (
				<span className="position">{player.position ?? "-"}</span>
			),
		},
		{
			key: "overall",
			title: "Latest OVR",
			numeric: true,
			render: (player) => (
				<strong className="number">{display(player.overall)}</strong>
			),
		},
		{ key: "appearances", title: "Apps", numeric: true },
		{
			key: "goals",
			title: "Goals",
			numeric: true,
			value: (player) => player.goals.value,
			render: (player) => <StatValue {...player.goals} />,
		},
		{
			key: "assists",
			title: "Assists",
			numeric: true,
			value: (player) => player.assists.value,
			render: (player) => <StatValue {...player.assists} />,
		},
		{
			key: "rating",
			title: "Avg rating",
			numeric: true,
			render: (player) => <StatValue value={player.rating} digits={2} />,
		},
	];
	const statisticColumns: Column<PlayerSummary>[] = [
		columns[0],
		columns[1],
		{ key: "appearances", title: "Apps", numeric: true },
		{
			key: "total",
			title: label(statistic),
			numeric: true,
			value: (player) => player.statistic.value,
			render: (player) => <StatValue {...player.statistic} />,
		},
		{
			key: "per_recorded_app",
			title: "Per recorded app",
			numeric: true,
			value: (player) =>
				player.statistic.value === null
					? null
					: player.statistic.value / player.statistic.known,
			render: (player) =>
				display(
					player.statistic.value === null
						? null
						: player.statistic.value / player.statistic.known,
					2,
				),
		},
		{
			key: "coverage",
			title: "Apps recorded",
			numeric: true,
			value: (player) => player.statistic.known / player.statistic.total,
			render: (player) =>
				`${player.statistic.known}/${player.statistic.total}`,
		},
	];
	const known = players.reduce(
		(total, player) => total + player.statistic.known,
		0,
	);
	const total = players.reduce(
		(total, player) => total + player.statistic.total,
		0,
	);
	return (
		<>
			<PageHeading title="Players" eyebrow="Performance & development">
				<label className="checkbox">
					<input
						type="checkbox"
						checked={opposition}
						onChange={(event) =>
							setOpposition(event.target.checked)
						}
					/>
					Include opposition
				</label>
			</PageHeading>
			{statistic !== "summary" && (
				<SectionHeading title={`${label(statistic)}: recorded totals`}>
					<Pill tone={known === total ? "positive" : "warning"}>
						{`${known}/${total} appearances recorded`}
					</Pill>
				</SectionHeading>
			)}
			<DataTable
				key={`${statistic}:${opposition}`}
				rows={players}
				columns={statistic === "summary" ? columns : statisticColumns}
				rowKey={(player) => player.id}
				defaultSort={{
					key: statistic === "summary" ? "goals" : "total",
					desc: true,
				}}
				searchLabel="Search player or nationality"
				searchText={(player) =>
					`${player.name} ${player.nationality} ${player.position}`
				}
				exportName={`player-${statistic}.json`}
				toolbar={
					<>
						<select
							aria-label="Player statistic"
							value={statistic}
							onChange={(event) => {
								const value = event.target.value;
								setParameters(
									(current) => {
										const next = new URLSearchParams(
											current,
										);
										if (value === "summary")
											next.delete("stat");
										else next.set("stat", value);
										return next;
									},
									{ replace: true },
								);
							}}
						>
							<option value="summary">Performance summary</option>
							{Object.entries(seasonStatGroups).map(
								([group, fields]) => (
									<optgroup key={group} label={group}>
										{fields.map((field) => (
											<option key={field} value={field}>
												{label(field)}
											</option>
										))}
									</optgroup>
								),
							)}
						</select>
						<select
							aria-label="Position group"
							value={position}
							onChange={(event) =>
								setPosition(event.target.value)
							}
						>
							<option value="all">All positions</option>
							<option value="outfield">Outfield</option>
							<option value="GK">Goalkeepers</option>
						</select>
					</>
				}
			/>
		</>
	);
}

export function PlayerDetail() {
	const { id } = useParams();
	const { model, matches, filters } = useCareer();
	const [tab, setTab] = useState("appearances");
	const [performance, setPerformance] = useState<Performance | null>(null);
	const [record, setRecord] = useState<Row | null>(null);
	const player = id && model.players.get(id);
	if (!player) return <Empty title="Player not found" />;
	const stats = playerSummary(model, player, matches, null);
	const appearances = [...stats.rows].sort((left, right) =>
		(model.matchById.get(left.match_id)?.played_on ?? "").localeCompare(
			model.matchById.get(right.match_id)?.played_on ?? "",
		),
	);
	const snapshots = model.data.player_snapshots
		.filter(
			(row) =>
				row.player_id === player.id &&
				(filters.season === "all" || row.season_id === filters.season),
		)
		.sort((left, right) =>
			snapshotOrder(left, model).localeCompare(
				snapshotOrder(right, model),
			),
		);
	const totals = model.data.player_competition_snapshots.filter(
		(row) =>
			row.player_id === player.id &&
			(filters.season === "all" || row.season_id === filters.season) &&
			(filters.competition === "all" ||
				(typeof row.competition_season_id === "string" &&
					model.editions.get(row.competition_season_id)
						?.competition_id === filters.competition)),
	);
	const occurrenceColumns: Column<Performance>[] = [
		{
			key: "match_id",
			title: "Match",
			value: (row) => model.matchById.get(row.match_id)?.played_on,
			render: (row) => {
				const match = model.matchById.get(row.match_id)!;
				return (
					<span className="stack">
						<strong>
							{dateLabel(match.played_on, true)} /{" "}
							{match.opponent}
						</strong>
						<small className="muted">
							{match.competition.name}
						</small>
					</span>
				);
			},
		},
		{
			key: "rating",
			title: "Rating",
			numeric: true,
			render: (row) => (
				<strong className="rating">{display(row.rating, 1)}</strong>
			),
		},
		{ key: "overall", title: "OVR", numeric: true },
		{ key: "goals", title: "Goals", numeric: true },
		{ key: "assists", title: "Assists", numeric: true },
		{
			key: "fixture",
			title: "",
			sortable: false,
			render: (row) => (
				<CareerLink
					to={`/matches/${row.match_id}`}
					className="small-link"
				>
					Match <ArrowRight size={14} />
				</CareerLink>
			),
		},
	];
	return (
		<>
			<CareerLink to="/players" className="back-link">
				<ArrowLeft size={15} />
				Players
			</CareerLink>
			<PageHeading
				title={player.name}
				eyebrow={`${player.nationality ?? "Nationality not recorded"} / ${stats.position ?? "Position not recorded"}`}
			>
				<div className="overall-mark">
					<strong>{display(stats.overall)}</strong>
					<span>Latest OVR</span>
				</div>
			</PageHeading>
			<Kpis
				items={[
					{
						label: "Appearances",
						value: stats.appearances,
						detail: "Selected fixtures",
					},
					{
						label: "Goals",
						value: <StatValue {...stats.goals} />,
						detail: `${stats.goals.known}/${stats.goals.total} records available`,
					},
					{
						label: "Assists",
						value: <StatValue {...stats.assists} />,
						detail: `${stats.assists.known}/${stats.assists.total} records available`,
					},
					{
						label: "Average rating",
						value: display(stats.rating, 2),
						detail: "Mean of recorded match ratings",
					},
				]}
			/>
			<div className="tabs" role="tablist" aria-label="Player views">
				{[
					["appearances", "Match log"],
					["development", "Development"],
					["totals", "Season totals"],
					["profile", "Player record"],
				].map(([value, title]) => (
					<button
						role="tab"
						aria-selected={tab === value}
						className={tab === value ? "active" : ""}
						key={value}
						onClick={() => setTab(value)}
					>
						{title}
					</button>
				))}
			</div>
			{tab === "appearances" && (
				<>
					<SectionHeading title="Match ratings" />
					<TrendChart
						rows={appearances.map((row) => ({
							label: dateLabel(
								model.matchById.get(row.match_id)!.played_on,
								true,
							),
							rating: row.rating,
						}))}
						series={[
							{
								key: "rating",
								name: "Match rating",
								color: "#247451",
							},
						]}
						domain={[0, 10]}
						height={205}
					/>
					<DataTable
						rows={appearances}
						columns={occurrenceColumns}
						rowKey={(row) => row.id}
						onSelect={setPerformance}
						defaultSort={{ key: "match_id", desc: true }}
						searchLabel="Search player matches"
						searchText={(row) => {
							const match = model.matchById.get(row.match_id);
							return `${match?.played_on} ${match?.opponent} ${match?.competition.name}`;
						}}
						exportName={`${player.name}-appearances.json`}
					/>
				</>
			)}
			{tab === "development" && (
				<>
					<SectionHeading title="Recorded overall history">
						<span className="tiny muted">
							{snapshots.length} observations
						</span>
					</SectionHeading>
					<TrendChart
						rows={snapshots
							.filter((row) => row.overall !== null)
							.map((row) => ({
								label: row.observed_on
									? dateLabel(row.observed_on, true)
									: `${model.seasons.get(row.season_id)?.label} ${label(row.snapshot_kind)}`,
								overall: row.overall,
							}))}
						series={[
							{ key: "overall", name: "OVR", color: "#247451" },
						]}
						domain={["dataMin - 1", "dataMax + 1"]}
						height={210}
					/>
					<DataTable
						rows={snapshots}
						rowKey={(row) => row.id}
						onSelect={setRecord}
						searchLabel="Search observations"
						exportName={`${player.name}-snapshots.json`}
						columns={[
							{
								key: "observed_on",
								title: "Observation",
								value: (row) => snapshotOrder(row, model),
								render: (row) => (
									<span className="stack">
										{row.observed_on
											? dateLabel(row.observed_on)
											: model.seasons.get(row.season_id)
													?.label}
										<small className="muted">
											{row.date_precision === "season"
												? "Exact date not recorded"
												: label(row.snapshot_kind)}
										</small>
									</span>
								),
							},
							{
								key: "snapshot_kind",
								title: "Type",
								render: (row) => (
									<Pill
										tone={
											row.snapshot_kind ===
												"season_end" ||
											row.snapshot_kind === "season_start"
												? "positive"
												: "neutral"
										}
									>
										{label(row.snapshot_kind)}
									</Pill>
								),
							},
							{ key: "overall", title: "OVR", numeric: true },
							{ key: "age", title: "Age", numeric: true },
							{ key: "displayed_position", title: "Positions" },
						]}
						defaultSort={{ key: "observed_on", desc: true }}
					/>
				</>
			)}
			{tab === "totals" && (
				<>
					<SectionHeading title="Match-derived totals">
						<span className="tiny muted">
							{stats.appearances} appearances
						</span>
					</SectionHeading>
					<div className="detail-groups">
						{Object.entries(seasonStatGroups)
							.filter(
								([group]) =>
									group !== "Goalkeeping" ||
									stats.rows.some(
										(row) =>
											row.displayed_position === "GK",
									),
							)
							.map(([group, fields]) => (
								<section key={group}>
									<h3>{group}</h3>
									<dl className="stats-list">
										{fields.map((field) => {
											const total = performanceMetric(
												stats.rows,
												field,
											);
											return (
												<div key={field}>
													<dt>{label(field)}</dt>
													<dd>
														<StatValue {...total} />
														<span className="tiny muted">
															{" "}
															{total.known}/
															{total.total} apps
														</span>
													</dd>
												</div>
											);
										})}
									</dl>
								</section>
							))}
					</div>
					<SectionHeading title="Captured cumulative statistics">
						<CareerLink to="/audit" className="small-link">
							Reconciliation <ArrowRight size={14} />
						</CareerLink>
					</SectionHeading>
					<DataTable
						rows={totals}
						rowKey={(row) => row.id}
						onSelect={setRecord}
						searchLabel="Search cumulative records"
						searchText={(row) =>
							`${model.seasons.get(String(row.season_id))?.label} ${String(row.scope)} ${model.competitions.get(model.editions.get(String(row.competition_season_id))?.competition_id ?? "")?.name}`
						}
						exportName={`${player.name}-season-totals.json`}
						columns={[
							{
								key: "scope",
								title: "Competition",
								render: (row) => (
									<span className="stack">
										<strong>
											{row.scope === "all_competitions"
												? "All competitions"
												: model.competitions.get(
														model.editions.get(
															String(
																row.competition_season_id,
															),
														)?.competition_id ?? "",
													)?.name}
										</strong>
										<small className="muted">
											{
												model.seasons.get(
													String(row.season_id),
												)?.label
											}{" "}
											/ {label(String(row.snapshot_kind))}
										</small>
									</span>
								),
							},
							...[
								"appearances",
								"goals",
								"assists",
								"clean_sheets",
								"yellow_cards",
								"red_cards",
							].map((key) => ({
								key,
								title:
									(
										{
											appearances: "Apps",
											clean_sheets: "CS",
											yellow_cards: "YC",
											red_cards: "RC",
										} as Record<string, string>
									)[key] ?? label(key),
								numeric: true,
							})),
							{
								key: "average_rating",
								title: "Avg",
								numeric: true,
								render: (row) => display(row.average_rating, 2),
							},
						]}
					/>
				</>
			)}
			{tab === "profile" && <RecordDetails record={player} />}
			{performance && (
				<PerformanceDialog
					performance={performance}
					onClose={() => setPerformance(null)}
				/>
			)}
			{record && (
				<Modal
					title={`${player.name} / observation`}
					onClose={() => setRecord(null)}
				>
					<RecordDetails record={record} />
				</Modal>
			)}
		</>
	);
}

export function Competitions() {
	const { model, matches, filters } = useCareer();
	const competitions = model.data.competitions.filter(
		(competition) =>
			(filters.competition === "all" ||
				competition.id === filters.competition) &&
			(filters.preseason || !competition.is_preseason),
	);
	return (
		<>
			<PageHeading title="Competitions" eyebrow="League & cup records">
				<span className="muted">
					{competitions.length} competitions
				</span>
			</PageHeading>
			<div className="competition-grid">
				{competitions.map((competition) => {
					const fixtures = matches.filter(
							(match) => match.competition.id === competition.id,
						),
						summary = summarize(fixtures);
					return (
						<CareerLink
							key={competition.id}
							to={`/competitions/${competition.id}`}
							className="competition-card"
						>
							<div className="competition-symbol">
								{competition.kind === "league" ? (
									<Shield size={26} />
								) : (
									<Trophy size={26} />
								)}
								<ArrowRight size={17} />
							</div>
							<Pill>
								{competition.is_preseason
									? "Preseason"
									: label(competition.kind)}
							</Pill>
							<h2>{competition.name}</h2>
							<div className="competition-record">
								<strong>
									{summary.played}
									<small>Played</small>
								</strong>
								<span>
									{summary.wins}
									<small>W</small>
								</span>
								<span>
									{summary.draws}
									<small>D</small>
								</span>
								<span>
									{summary.losses}
									<small>L</small>
								</span>
							</div>
							<div className="card-foot">
								<span>
									{display(summary.goalsFor.value)} scored /{" "}
									{display(summary.goalsAgainst.value)}{" "}
									conceded
								</span>
								{competition.kind === "league" && (
									<strong>{summary.leaguePoints} pts</strong>
								)}
							</div>
						</CareerLink>
					);
				})}
			</div>
		</>
	);
}
export function CompetitionDetail() {
	const { id } = useParams(),
		{ model, filters } = useCareer();
	const competition = id && model.competitions.get(id);
	if (!competition) return <Empty title="Competition not found" />;
	const matches = selectMatches(model, {
		...filters,
		competition: competition.id,
		preseason: true,
	});
	const summary = summarize(matches);
	return (
		<>
			<CareerLink to="/competitions" className="back-link">
				<ArrowLeft size={15} />
				Competitions
			</CareerLink>
			<PageHeading
				title={competition.name}
				eyebrow="Notts County competition record"
			>
				<Pill tone={competition.is_preseason ? "accent" : "neutral"}>
					{competition.is_preseason
						? "Preseason tournament"
						: label(competition.kind)}
				</Pill>
			</PageHeading>
			<Kpis
				items={[
					{
						label: "Played",
						value: summary.played,
						detail: `${summary.wins} W / ${summary.draws} D / ${summary.losses} L`,
					},
					{
						label: "Goals for",
						value: display(summary.goalsFor.value),
						detail: `${display(summary.goalsAgainst.value)} against`,
					},
					{ label: "Clean sheets", value: summary.cleanSheets },
					{
						label:
							competition.kind === "league"
								? "Points from results"
								: "Win rate",
						value:
							competition.kind === "league"
								? summary.leaguePoints
								: `${display(summary.winRate, 1)}%`,
						detail: "Before penalty shootouts",
					},
				]}
			/>
			<SectionHeading title="Fixtures" />
			<MatchTable matches={matches} />
		</>
	);
}

export function UnknownPage() {
	return (
		<>
			<PageHeading title="Page not found" />
			<CareerLink to="/" className="button secondary">
				Return to overview <ArrowRight size={16} />
			</CareerLink>
		</>
	);
}
