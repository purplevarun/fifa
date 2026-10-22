import {
	ArrowRight,
	ArrowRightLeft,
	Check,
	Download,
	TriangleAlert,
	Trophy,
} from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { scoringFeats } from "./analytics";
import { useCareer } from "./context";
import type { Comparison, Dataset, MetricComparison, Row } from "./data";
import {
	dateLabel,
	display,
	downloadJson,
	eventDescription,
	label,
	performanceMetric,
	referenceLabel,
	selectPerformances,
} from "./data";
import { HatTrickTable, ScoringCoverage } from "./overviewStats";
import type { Column } from "./ui";
import {
	CareerLink,
	DataTable,
	Empty,
	IconButton,
	Kpis,
	Modal,
	PageHeading,
	Pill,
	RecordDetails,
	SectionHeading,
} from "./ui";

export function CareerRecords() {
	const { model, filters, matches } = useCareer();
	const [parameters, setParameters] = useSearchParams();
	const tab = parameters.get("tab") === "events" ? "events" : "transfers";
	const [selected, setSelected] = useState<Row | null>(null);
	const [eventType, setEventType] = useState("all");
	const events = model.data.competition_events
		.filter((event) => {
			if (event.event_type === "player_of_the_year") return true;
			const edition = model.editions.get(
				String(event.competition_season_id),
			);
			return (
				(filters.season === "all" ||
					edition?.season_id === filters.season) &&
				(filters.competition === "all" ||
					edition?.competition_id === filters.competition) &&
				(filters.preseason ||
					!model.competitions.get(edition?.competition_id ?? "")
						?.is_preseason)
			);
		})
		.sort((left, right) =>
			String(right.period ?? right.announced_on ?? "").localeCompare(
				String(left.period ?? left.announced_on ?? ""),
			),
		);
	const monthly = events.filter(
		(event) => event.event_type === "player_of_the_month",
	);
	const annual = events
		.filter((event) => event.event_type === "player_of_the_year")
		.map((event) => ({
			id: event.id,
			year: String(event.period ?? "Unknown year"),
			player_id: String(event.player_id),
			name:
				model.players.get(String(event.player_id))?.name ??
				"Unknown player",
		}));
	const champions = events
		.filter((event) => event.event_type === "champion")
		.map((event) => {
			const edition = model.editions.get(
				String(event.competition_season_id),
			);
			return {
				id: event.id,
				season:
					model.seasons.get(edition?.season_id ?? "")?.label ??
					"Unknown season",
				competition:
					model.competitions.get(edition?.competition_id ?? "")
						?.name ?? "Unknown competition",
				club:
					model.clubs.get(String(event.club_id))?.name ??
					"Unknown club",
			};
		});
	const awardCounts = new Map<
		string,
		{
			id: string;
			player_id: string;
			name: string;
			season: string;
			awards: number;
		}
	>();
	for (const event of monthly) {
		if (typeof event.player_id !== "string") continue;
		const edition = model.editions.get(String(event.competition_season_id));
		const season =
			model.seasons.get(edition?.season_id ?? "")?.label ??
			"Unknown season";
		const id = `${event.player_id}:${season}`;
		const current = awardCounts.get(id) ?? {
			id,
			player_id: event.player_id,
			name: model.players.get(event.player_id)?.name ?? "Unknown player",
			season,
			awards: 0,
		};
		current.awards += 1;
		awardCounts.set(id, current);
	}
	const feats = scoringFeats(model, matches);
	const seasonScoring = feats.seasonal;
	const careerScoring = feats.career;
	const scoringLeader = (metric: "braces" | "hat_tricks") => {
		const highest = Math.max(0, ...careerScoring.map((row) => row[metric]));
		if (highest === 0) return "None";
		const names = careerScoring
			.filter((row) => row[metric] === highest)
			.map((row) => row.name)
			.sort()
			.join(", ");
		return `${names} (${highest})`;
	};
	const scoringColumns: Column<(typeof seasonScoring)[number]>[] = [
		{
			key: "name",
			title: "Player",
			render: (row) => (
				<CareerLink to={`/players/${row.player_id}`}>
					{row.name}
				</CareerLink>
			),
		},
		{ key: "season", title: "Season" },
		{ key: "braces", title: "Braces", numeric: true },
		{ key: "hat_tricks", title: "Hat-tricks", numeric: true },
	];
	const visibleEvents = events.filter(
		(event) => eventType === "all" || event.event_type === eventType,
	);
	return (
		<>
			<PageHeading title="Career records" eyebrow="Transfers & honours" />
			<div
				className="tabs"
				role="tablist"
				aria-label="Career record types"
			>
				{["transfers", "events"].map((value) => (
					<button
						key={value}
						role="tab"
						aria-selected={tab === value}
						className={tab === value ? "active" : ""}
						onClick={() =>
							setParameters(
								(current) => {
									const next = new URLSearchParams(current);
									next.set("tab", value);
									return next;
								},
								{ replace: true },
							)
						}
					>
						{value === "transfers"
							? `Transfers (${model.data.player_transfers.length})`
							: `Honours & events (${events.length})`}
					</button>
				))}
			</div>
			{tab === "transfers" ? (
				<div className="transfer-list">
					{model.data.player_transfers.map((transfer) => (
						<article className="transfer-record" key={transfer.id}>
							<div className="transfer-icon">
								<ArrowRightLeft size={21} />
							</div>
							<div className="transfer-main">
								<div className="inline">
									<Pill
										tone={
											transfer.transfer_type === "loan"
												? "accent"
												: "neutral"
										}
									>
										{label(String(transfer.transfer_type))}
									</Pill>
									<span className="muted tiny">
										{typeof transfer.effective_on ===
										"string"
											? dateLabel(transfer.effective_on)
											: "Exact transfer date not recorded"}
									</span>
								</div>
								<CareerLink
									to={`/players/${transfer.player_id}`}
								>
									<h2>
										{
											model.players.get(
												String(transfer.player_id),
											)?.name
										}
									</h2>
								</CareerLink>
								<p>
									{transfer.from_club_id
										? model.clubs.get(
												String(transfer.from_club_id),
											)?.name
										: "Origin not recorded"}{" "}
									<ArrowRight size={14} />{" "}
									{transfer.to_club_id
										? model.clubs.get(
												String(transfer.to_club_id),
											)?.name
										: "Destination not recorded"}
								</p>
								<dl className="inline-facts">
									<div>
										<dt>Contract</dt>
										<dd>
											{transfer.contract_months == null
												? "-"
												: `${transfer.contract_months} months`}
										</dd>
									</div>
									<div>
										<dt>Loan term</dt>
										<dd>
											{transfer.loan_months == null
												? "-"
												: `${transfer.loan_months} months`}
										</dd>
									</div>
									<div>
										<dt>Fee</dt>
										<dd>
											{transfer.fee_minor == null
												? "Not recorded"
												: `${transfer.currency ?? ""} ${display(Number(transfer.fee_minor) / 100, 2)}`}
										</dd>
									</div>
								</dl>
							</div>
							<div className="transfer-actions">
								<button
									className="button secondary"
									onClick={() => setSelected(transfer)}
								>
									Full record
								</button>
							</div>
						</article>
					))}
				</div>
			) : (
				<>
					<SectionHeading title="Player of the Year">
						<Pill>{annual.length} awards</Pill>
					</SectionHeading>
					{annual.length === 0 ? (
						<Empty title="No Player of the Year awards recorded" />
					) : (
						<DataTable
							rows={annual}
							rowKey={(row) => row.id}
							searchLabel="Search yearly award winners"
							searchText={(row) => `${row.year} ${row.name}`}
							defaultSort={{ key: "year", desc: true }}
							exportName="player-of-the-year.json"
							columns={[
								{ key: "year", title: "Year" },
								{
									key: "name",
									title: "Winner",
									render: (row) => (
										<CareerLink
											to={`/players/${row.player_id}`}
										>
											{row.name}
										</CareerLink>
									),
								},
							]}
						/>
					)}
					<SectionHeading title="Champions">
						<Pill>{champions.length} titles</Pill>
					</SectionHeading>
					{champions.length === 0 ? (
						<Empty title="No championships in this selection" />
					) : (
						<DataTable
							rows={champions}
							rowKey={(row) => row.id}
							searchLabel="Search champions"
							searchText={(row) =>
								`${row.season} ${row.competition} ${row.club}`
							}
							defaultSort={{ key: "season", desc: true }}
							exportName="champions.json"
							columns={[
								{ key: "season", title: "Season" },
								{ key: "competition", title: "Competition" },
								{ key: "club", title: "Winner" },
							]}
						/>
					)}
					{monthly.length > 0 && (
						<>
							<SectionHeading title="Player of the Month">
								<Pill>{monthly.length} awards</Pill>
							</SectionHeading>
							<DataTable
								rows={[...awardCounts.values()]}
								rowKey={(row) => row.id}
								searchLabel="Search monthly award winners"
								searchText={(row) =>
									`${row.name} ${row.season}`
								}
								defaultSort={{ key: "awards", desc: true }}
								exportName="player-of-the-month.json"
								columns={[
									{
										key: "name",
										title: "Player",
										render: (row) => (
											<CareerLink
												to={`/players/${row.player_id}`}
											>
												{row.name}
											</CareerLink>
										),
									},
									{ key: "season", title: "Season" },
									{
										key: "awards",
										title: "Awards",
										numeric: true,
									},
								]}
							/>
						</>
					)}
					<div id="scoring-feats">
						<SectionHeading title="Scoring feats">
							<Pill>
								{feats.hatTricks.length} hat-tricks / selected
								fixtures
							</Pill>
						</SectionHeading>
						<ScoringCoverage feats={feats} />
					</div>
					<SectionHeading
						title={
							filters.season === "all" &&
							filters.competition === "all" &&
							filters.preseason
								? "Career totals"
								: "Selected totals"
						}
					>
						<Pill>Most braces: {scoringLeader("braces")}</Pill>
						<Pill>
							Most hat-tricks: {scoringLeader("hat_tricks")}
						</Pill>
					</SectionHeading>
					{careerScoring.length === 0 ? (
						<Empty title="No braces or hat-tricks recorded" />
					) : (
						<DataTable
							rows={careerScoring}
							rowKey={(row) => row.id}
							searchLabel="Search career scoring feats"
							searchText={(row) => row.name}
							defaultSort={{ key: "hat_tricks", desc: true }}
							exportName="career-scoring-feats.json"
							columns={scoringColumns.filter(
								(column) => column.key !== "season",
							)}
						/>
					)}
					<SectionHeading title="Season by season" />
					{seasonScoring.length === 0 ? (
						<Empty title="No seasonal braces or hat-tricks recorded" />
					) : (
						<DataTable
							rows={seasonScoring}
							rowKey={(row) => row.id}
							searchLabel="Search seasonal scoring feats"
							searchText={(row) => `${row.name} ${row.season}`}
							defaultSort={{ key: "season", desc: true }}
							exportName="seasonal-scoring-feats.json"
							columns={scoringColumns}
						/>
					)}
					<SectionHeading title="Hat-trick matches" />
					<HatTrickTable rows={feats.hatTricks} />
					<SectionHeading title="Honours & events">
						<select
							aria-label="Honour type"
							value={eventType}
							onChange={(event) =>
								setEventType(event.target.value)
							}
						>
							<option value="all">All honours & events</option>
							{[
								...new Set(
									events.map((event) =>
										String(event.event_type),
									),
								),
							]
								.sort()
								.map((type) => (
									<option key={type} value={type}>
										{label(type)}
									</option>
								))}
						</select>
					</SectionHeading>
					{visibleEvents.length === 0 && (
						<Empty title="No honours in this selection" />
					)}
					<div className="event-list">
						{visibleEvents.map((event) => (
							<article className="event-record" key={event.id}>
								<div className="event-date">
									<span>
										{typeof event.period === "string"
											? /^\d{4}-\d{2}$/.test(event.period)
												? new Date(
														`${event.period}-01T12:00:00`,
													).toLocaleDateString(
														"en-GB",
														{
															month: "long",
															year: "numeric",
														},
													)
												: event.period
											: typeof event.announced_on ===
												  "string"
												? dateLabel(event.announced_on)
												: "Date not recorded"}
									</span>
									{typeof event.announced_on === "string" && (
										<small className="muted">
											Announced{" "}
											{dateLabel(
												event.announced_on,
												true,
											)}
										</small>
									)}
								</div>
								<Trophy size={24} className="event-icon" />
								<div>
									<div className="eyebrow">
										{event.event_type ===
										"player_of_the_year"
											? "Annual award"
											: referenceLabel(
													model,
													"competition_season_id",
													event.competition_season_id,
												)}
									</div>
									<h2>{label(String(event.event_type))}</h2>
									<p>{eventDescription(event)}</p>
									{typeof event.player_id === "string" && (
										<CareerLink
											to={`/players/${event.player_id}`}
											className="small-link"
										>
											{
												model.players.get(
													event.player_id,
												)?.name
											}{" "}
											<ArrowRight size={14} />
										</CareerLink>
									)}
								</div>
								<button
									className="button secondary"
									onClick={() => setSelected(event)}
								>
									Full record
								</button>
							</article>
						))}
					</div>
				</>
			)}
			{selected && (
				<Modal title="Career record" onClose={() => setSelected(null)}>
					<RecordDetails record={selected} />
				</Modal>
			)}
		</>
	);
}

function MetricPair({
	metric,
	digits = 0,
}: {
	metric?: MetricComparison;
	digits?: number;
}) {
	if (!metric) return <span className="muted">-</span>;
	return (
		<span
			className={`metric-pair ${metric.result === "match" ? "positive-text" : metric.result === "mismatch" ? "negative-text" : "muted"}`}
			title={`${label(metric.result)}${metric.assumed_zero_match_values ? `; ${metric.assumed_zero_match_values} goalkeeper goal values assumed zero` : ""}${metric.missing_match_values ? `; ${metric.missing_match_values} missing match values` : ""}${metric.raw_match_average != null ? `; raw mean ${metric.raw_match_average.toFixed(6)}` : ""}`}
		>
			{display(metric.observed, digits)}{" "}
			<span className="divider">/</span> {display(metric.derived, digits)}
			{metric.result === "match" && <Check size={12} />}
		</span>
	);
}
export function Audit() {
	const { model } = useCareer();
	const [parameters, setParameters] = useSearchParams();
	const requestedTab = parameters.get("tab");
	const tab =
		requestedTab === "coverage" || requestedTab === "warnings"
			? requestedTab
			: "reconciliation";
	const [selected, setSelected] = useState<Row | null>(null);
	const [season, setSeason] = useState("all"),
		[scope, setScope] = useState("all");
	const comparisons = model.data.season_reconciliation.comparisons.filter(
		(row) =>
			(season === "all" || row.season === season) &&
			(scope === "all" || row.scope === scope),
	);
	const warnings = model.data.match_coverage.warnings;
	const coverage = model.data.match_coverage.summary;
	const appearances = selectPerformances(model, model.matches);
	const passing = performanceMetric(appearances, "passes_completed");
	const keyPasses = performanceMetric(appearances, "key_passes");
	const interceptions = performanceMetric(appearances, "interceptions");
	const detailedComplete = [passing, keyPasses, interceptions].every(
		(value) => value.known === value.total,
	);
	const columns: Column<Comparison>[] = [
		{
			key: "player",
			title: "Player",
			render: (row) => (
				<span className="stack">
					<strong>{row.player}</strong>
					<small className="muted">{row.season}</small>
				</span>
			),
		},
		{
			key: "competition",
			title: "Competition",
			render: (row) => row.competition ?? "All competitions",
		},
		...["appearances", "goals", "assists", "average_rating"].map((key) => ({
			key,
			title: key === "average_rating" ? "Avg rating" : label(key),
			numeric: true,
			value: (row: Comparison) => row.metrics[key]?.observed,
			render: (row: Comparison) => (
				<MetricPair
					metric={row.metrics[key]}
					digits={key === "average_rating" ? 1 : 0}
				/>
			),
		})),
		{
			key: "result",
			title: "Check",
			render: (row) => (
				<Pill
					tone={
						row.result === "match"
							? "positive"
							: row.result === "mismatch"
								? "negative"
								: "warning"
					}
				>
					{row.result === "match"
						? "Matched"
						: row.result === "mismatch"
							? "Difference"
							: row.result === "unconfirmed_cutoff"
								? "Cutoff unconfirmed"
								: "Partial"}
				</Pill>
			),
		},
	];
	return (
		<>
			<PageHeading
				title="Verification"
				eyebrow="Coverage & reconciliation"
			>
				<IconButton
					label="Download verification reports"
					onClick={() =>
						downloadJson(
							{
								coverage: model.data.match_coverage,
								reconciliation:
									model.data.season_reconciliation,
							},
							"verification.json",
						)
					}
				>
					<Download size={18} />
				</IconButton>
			</PageHeading>
			<Kpis
				items={[
					{
						label: "Fixtures",
						value: String(coverage.matches),
						detail: "Saved match records",
					},
					{
						label: "Team records",
						value: model.data.team_matches.length,
						detail: "Both clubs / all fixtures",
					},
					{
						label: "Season comparisons",
						value: model.data.season_reconciliation.comparisons
							.length,
						detail: `${model.data.season_reconciliation.summary.mismatched_rows} mismatches`,
					},
					{
						label: "Open warnings",
						value: warnings.length,
						detail: "Missing data & consistency",
					},
				]}
			/>
			<div
				className="tabs"
				role="tablist"
				aria-label="Verification views"
			>
				{[
					["reconciliation", "Season reconciliation"],
					["coverage", "Data coverage"],
					["warnings", `Warnings (${warnings.length})`],
				].map(([value, title]) => (
					<button
						role="tab"
						aria-selected={tab === value}
						className={tab === value ? "active" : ""}
						key={value}
						onClick={() =>
							setParameters((current) => {
								const next = new URLSearchParams(current);
								next.set("tab", value);
								return next;
							})
						}
					>
						{title}
					</button>
				))}
			</div>
			{tab === "reconciliation" && (
				<>
					<SectionHeading title="Captured / match-derived">
						<div className="inline">
							<select
								aria-label="Reconciliation season"
								value={season}
								onChange={(event) =>
									setSeason(event.target.value)
								}
							>
								<option value="all">All seasons</option>
								{model.data.seasons.map((season) => (
									<option
										key={season.id}
										value={season.label}
									>
										{season.label}
									</option>
								))}
							</select>
							<select
								aria-label="Reconciliation scope"
								value={scope}
								onChange={(event) =>
									setScope(event.target.value)
								}
							>
								<option value="all">All scopes</option>
								<option value="all_competitions">
									Season totals
								</option>
								<option value="competition">
									By competition
								</option>
							</select>
						</div>
					</SectionHeading>
					<DataTable
						rows={comparisons}
						columns={columns}
						rowKey={(row) => row.snapshot_id}
						onSelect={setSelected}
						searchLabel="Search reconciliation records"
						searchText={(row) =>
							`${row.player} ${row.competition ?? "All competitions"} ${row.season} ${row.result}`
						}
						defaultSort={{ key: "player" }}
						exportName="season-reconciliation.json"
					/>
					<div className="note-strip">
						<span>Rating display: one-decimal truncation.</span>
						<span>
							Goalkeeper goals: missing values assumed zero.
						</span>
						<span>Zero-appearance averages: not applicable.</span>
					</div>
				</>
			)}
			{tab === "coverage" && (
				<div className="coverage-grid">
					<section>
						<SectionHeading title="Record availability" />
						<dl className="stats-list large">
							{Object.entries(model.data.coverage.records).map(
								([name, count]) => (
									<div key={name}>
										<dt>{label(name)}</dt>
										<dd>{display(count)}</dd>
									</div>
								),
							)}
						</dl>
					</section>
					<section>
						<SectionHeading title="Review scope" />
						<div className="notice positive">
							<Check size={18} />
							<div>
								<strong>
									All fixtures, team tables & player cores
								</strong>
								<p>
									{display(coverage.matches)} matches /{" "}
									{display(coverage.preseason_matches)}{" "}
									preseason /{" "}
									{display(coverage.player_records)} Notts
									County appearances
								</p>
							</div>
						</div>
						<div
							className={`notice ${detailedComplete ? "positive" : "warning"}`}
						>
							{detailedComplete ? (
								<Check size={18} />
							) : (
								<TriangleAlert size={18} />
							)}
							<div>
								<strong>Passing and interceptions</strong>
								<p>
									{passing.known}/{passing.total} passing
									records / {keyPasses.known}/
									{keyPasses.total} key-pass records /{" "}
									{interceptions.known}/{interceptions.total}{" "}
									interception records
								</p>
							</div>
						</div>
						<dl className="stats-list large">
							{Object.entries(
								model.data.match_coverage
									.player_field_availability,
							).map(([field, detail]) => (
								<div key={field}>
									<dt>{label(field)}</dt>
									<dd>
										{String((detail as Row).recorded)}{" "}
										recorded /{" "}
										{String((detail as Row).null)} missing
									</dd>
								</div>
							))}
						</dl>
					</section>
				</div>
			)}
			{tab === "warnings" && (
				<div>
					{warnings.length ? (
						warnings.map((warning, index) => {
							const match = model.matchById.get(
								String(warning.match_id ?? ""),
							);
							const playedOn =
								typeof warning.played_on === "string"
									? warning.played_on
									: (match?.played_on ?? null);
							return (
								<section className="warning-record" key={index}>
									<TriangleAlert size={22} />
									<div>
										<div className="eyebrow">
											{dateLabel(playedOn)} /{" "}
											{display(
												warning.competition ??
													match?.competition.name,
											)}
										</div>
										<h2>
											{display(
												warning.home_club ??
													match?.home ??
													"Unknown home club",
											)}{" "}
											/{" "}
											{display(
												warning.away_club ??
													match?.away ??
													"Unknown away club",
											)}
										</h2>
										<p>
											<strong>
												{display(
													warning.title ??
														label(
															String(
																warning.code ??
																	"data_warning",
															),
														),
												)}
											</strong>
										</p>
										{warning.code ===
											"player_goal_difference" && (
											<p>
												Team goals:{" "}
												<strong>
													{display(
														warning.team_goals,
													)}
												</strong>
												. Credited player goals:{" "}
												<strong>
													{display(
														warning.credited_player_goals,
													)}
												</strong>
												.
											</p>
										)}
										<p className="muted">
											{display(
												warning.detail ??
													"Details unavailable for this warning.",
											)}
										</p>
										{typeof warning.match_id ===
											"string" && (
											<CareerLink
												to={`/matches/${warning.match_id}`}
												className="button secondary"
											>
												Open match{" "}
												<ArrowRight size={15} />
											</CareerLink>
										)}
									</div>
								</section>
							);
						})
					) : (
						<Empty title="No reconciliation warnings" />
					)}
				</div>
			)}
			{selected && (
				<Modal
					title={`${selected.player ?? "Record"} / reconciliation`}
					onClose={() => setSelected(null)}
					wide
				>
					<RecordDetails record={selected} />
				</Modal>
			)}
		</>
	);
}

const tableNames = [
	"matches",
	"player_matches",
	"players",
	"team_matches",
	"player_snapshots",
	"player_competition_snapshots",
	"clubs",
	"competitions",
	"competition_seasons",
	"seasons",
	"player_transfers",
	"competition_events",
] as const;
type TableName = (typeof tableNames)[number];
export function Explorer() {
	const { model } = useCareer();
	const [parameters, setParameters] = useSearchParams();
	const parameter = parameters.get("table");
	const table: TableName = tableNames.includes(parameter as TableName)
		? (parameter as TableName)
		: "matches";
	const [selected, setSelected] = useState<Row | null>(null);
	const rows = model.data[table] as unknown as Row[];
	const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
	const columns: Column<Row>[] = keys.map((key, index) => ({
		key,
		title: label(key),
		value: (row) => row[key],
		numeric: rows.some((row) => typeof row[key] === "number"),
		render: (row) => {
			const value = row[key],
				resolved = referenceLabel(model, key, value);
			if (value === null)
				return (
					<span
						className="null-value"
						title="Not recorded or not applicable"
					>
						null
					</span>
				);
			if (typeof value === "object")
				return (
					<span className="muted">
						{Array.isArray(value)
							? `${value.length} items`
							: "Object"}
					</span>
				);
			if (index > 0 && typeof value === "string") {
				if (key === "player_id")
					return (
						<CareerLink to={`/players/${value}`}>
							{resolved}
						</CareerLink>
					);
				if (key === "match_id")
					return (
						<CareerLink to={`/matches/${value}`}>
							{resolved}
						</CareerLink>
					);
			}
			return (
				<span
					className={
						key === "id" ||
						(key.endsWith("_id") && resolved === value) ||
						key === "sha256"
							? "short-id"
							: "raw-cell"
					}
					title={String(value)}
				>
					{key === "id" || key === "sha256"
						? `${String(value).slice(0, 8)}...`
						: resolved}
				</span>
			);
		},
	}));
	return (
		<>
			<PageHeading
				title="Data explorer"
				eyebrow="Complete structured export"
			>
				<IconButton
					label="Download complete dataset"
					onClick={() => downloadJson(model.data, "career.json")}
				>
					<Download size={18} />
				</IconButton>
			</PageHeading>
			<div className="dataset-selector">
				<label>
					Table
					<select
						aria-label="Dataset table"
						value={table}
						onChange={(event) => {
							setParameters({ table: event.target.value });
							setSelected(null);
						}}
					>
						{tableNames.map((table) => (
							<option key={table} value={table}>
								{label(table)} ({model.data[table].length})
							</option>
						))}
					</select>
				</label>
				<span className="muted">
					Schema {model.data.schema_version} / {keys.length} fields /
					UUID identifiers
				</span>
			</div>
			<DataTable
				key={table}
				rows={rows}
				columns={columns}
				rowKey={(row) =>
					typeof row.id === "string"
						? row.id
						: Object.values(row).join(":")
				}
				onSelect={setSelected}
				searchLabel={`Search ${label(table).toLowerCase()}`}
				searchText={(row) =>
					`${JSON.stringify(row)} ${Object.entries(row)
						.map(([key, value]) =>
							referenceLabel(model, key, value),
						)
						.join(" ")}`
				}
				exportName={`${table}.json`}
			/>
			{selected && (
				<Modal
					title={label(table) + " / record"}
					onClose={() => setSelected(null)}
					wide
				>
					<RecordDetails record={selected} />
					<div className="dialog-actions">
						<button
							className="button secondary"
							onClick={() =>
								downloadJson(selected, `${table}-record.json`)
							}
						>
							<Download size={15} />
							Download record
						</button>
					</div>
				</Modal>
			)}
		</>
	);
}

export type AvailableTables = Pick<Dataset, TableName>;
