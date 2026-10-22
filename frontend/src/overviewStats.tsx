import { ArrowRight, Trophy } from "lucide-react";
import type { CSSProperties } from "react";
import { positionRankings, scoringFeats } from "./analytics";
import { useCareer } from "./context";
import { dateLabel, display } from "./data";
import { CareerLink, DataTable, Empty, Pill, SectionHeading } from "./ui";

export function PositionLeaders() {
	const { model, matches } = useCareer();
	const rankings = positionRankings(model, matches);
	return (
		<section
			className="position-leaders"
			aria-label="Best players by position"
		>
			<SectionHeading title="Best players by position">
				<Pill>Stats-based / selected fixtures</Pill>
			</SectionHeading>
			<p className="muted position-intro">
				Weighted performance per appearance, not FIFA overall ratings.
			</p>
			<div className="position-grid">
				{rankings.roles.map((group) => {
					const winner = group.candidates[0];
					const isPlaymaker = group.role === "playmaker";
					return (
						<article
							key={group.role}
							className="position-card"
							aria-label={group.title}
							style={
								{
									"--position-accent": group.color,
								} as CSSProperties
							}
						>
							<div className="position-card-heading">
								<h3>{group.title}</h3>
								<Trophy size={16} aria-hidden="true" />
							</div>
							<div className="tiny muted">
								{isPlaymaker
									? "All outfield positions"
									: group.positions.join(" / ")}
							</div>
							{winner ? (
								<>
									<CareerLink
										to={`/players/${winner.id}`}
										className="position-winner"
									>
										{winner.name}
									</CareerLink>
									<div className="position-score">
										<strong>
											{display(winner.score, 1)}
										</strong>
										<span>/ 100 role score</span>
									</div>
									<meter
										min={0}
										max={100}
										value={winner.score}
										aria-label={`${group.title} score`}
									/>
									<p className="position-coverage">
										{winner.known}/{winner.total}{" "}
										{isPlaymaker
											? "complete outfield appearances"
											: "complete appearances in this role"}
									</p>
									{winner.known < 5 && (
										<Pill tone="warning">
											Provisional · fewer than 5
											appearances
										</Pill>
									)}
									{winner.known < winner.total && (
										<Pill tone="warning">
											Partial data · incomplete
											appearances excluded
										</Pill>
									)}
									<dl className="position-metrics">
										{winner.metrics.map((component) => (
											<div key={component.field}>
												<dt>
													{component.label}
													<small>
														{component.weight}%
														weight
													</small>
												</dt>
												<dd
													title={`${display(component.total)} across ${winner.known} complete appearances; ${display(component.points, 1)} score points`}
												>
													{display(
														component.perAppearance,
														2,
													)}
													<small>
														per appearance
													</small>
												</dd>
											</div>
										))}
									</dl>
									{group.candidates.length > 1 && (
										<ol
											className="position-runners"
											start={2}
											aria-label={`${group.title} runners-up`}
										>
											{group.candidates
												.slice(1, 3)
												.map((player) => (
													<li key={player.id}>
														<CareerLink
															to={`/players/${player.id}`}
														>
															{player.name}
														</CareerLink>
														<span>
															{display(
																player.score,
																1,
															)}
														</span>
													</li>
												))}
										</ol>
									)}
								</>
							) : (
								<div className="position-no-winner">
									<strong>No eligible player</strong>
									<p>
										Needs {rankings.minimumAppearances}{" "}
										complete appearances, at least 80% stat
										coverage and a positive score.
									</p>
								</div>
							)}
							{group.excludedPlayers > 0 && (
								<p className="tiny muted">
									{group.excludedPlayers} players below the
									eligibility requirements
								</p>
							)}
						</article>
					);
				})}
			</div>
			<details className="stats-methodology">
				<summary>How the position scores work</summary>
				<p>
					Only Notts County appearances in the selected season,
					competition and preseason scope count. The recorded match
					position takes priority; otherwise the first displayed
					position is used. Players who change roles are scored
					separately in each role.
				</p>
				<p>
					Playmaker is an additional 50% goals / 50% assists ranking
					across all recognised outfield appearances. Players remain
					eligible for their usual position category too; goalkeeper
					appearances and unknown positions do not count towards
					playmaker scores.
				</p>
				<p>
					Each component is averaged over the same complete
					appearances and divided by the best eligible player's
					average in that role, then multiplied by its weight. A
					component that is zero for everyone contributes zero. For
					goals conceded, the factor is (1 + lowest average) / (1 +
					player average). Scores are relative within a role, not
					comparable across roles or filter selections.
				</p>
				<ul>
					{rankings.roles.map((group) => (
						<li key={group.role}>
							<strong>{group.title}: </strong>
							{group.metrics
								.map(
									(component) =>
										`${component.weight}% ${component.label.toLowerCase()}`,
								)
								.join(" + ")}
						</li>
					))}
				</ul>
				<p>
					Eligibility: {rankings.minimumAppearances} complete
					appearances in the role (5, or the number of selected
					fixtures if fewer) and at least 80% complete records.
					Unknown stats are excluded, not replaced with zeros. Ties
					use more complete appearances, then player name. Under 5
					appearances is provisional. Minutes are not consistently
					recorded, so these are per-appearance, not per-90 scores.
				</p>
				<p>
					Defensive actions mean interceptions + blocks + clearances.
					Saves mean shots caught + parried. Goalkeeper clean sheets
					require a recorded zero goals-conceded value; this is an
					appearance measure, not a 90-minute clean-sheet award.
				</p>
				{rankings.unclassifiedAppearances > 0 && (
					<p>
						{rankings.unclassifiedAppearances} appearances have no
						recognised position and are excluded.
					</p>
				)}
			</details>
		</section>
	);
}

export function ScoringCoverage({
	feats,
}: {
	feats: ReturnType<typeof scoringFeats>;
}) {
	return (
		<div className="scoring-coverage muted">
			<p>
				One hat-trick means 3 or more goals by the same player in one
				match, including extra time; shootouts and cumulative season
				snapshots are excluded. Braces mean exactly 2 goals.
			</p>
			<p>
				{display(feats.known)}/{display(feats.total)} recorded
				appearances have goal values
				{feats.assumedZero > 0 &&
					` (${display(feats.assumedZero)} goalkeeper zeros assumed)`}
				. Counts cover captured matches only, not an independently
				verified full career.
			</p>
			{feats.known < feats.total && (
				<p className="negative-text">
					Partial goal data: {feats.total - feats.known} appearances
					are unknown; totals may be understated.
				</p>
			)}
			{feats.missingLineups > 0 && (
				<p className="negative-text">
					Incomplete lineups: {feats.missingLineups} fixtures have
					fewer than 11 player records; more scoring feats may be
					missing.
				</p>
			)}
		</div>
	);
}

export function HatTrickTable({
	rows,
}: {
	rows: ReturnType<typeof scoringFeats>["hatTricks"];
}) {
	if (!rows.length)
		return <Empty title="No hat-tricks recorded in this selection" />;
	return (
		<DataTable
			rows={rows}
			rowKey={(row) => row.id}
			searchLabel="Search hat-trick matches"
			searchText={(row) =>
				`${row.name} ${row.match.played_on} ${row.match.opponent} ${row.match.competition.name} ${row.match.season.label}`
			}
			defaultSort={{ key: "played_on", desc: true }}
			exportName="hat-trick-matches.json"
			columns={[
				{
					key: "played_on",
					title: "Date",
					value: (row) => row.match.played_on,
					render: (row) => dateLabel(row.match.played_on),
				},
				{
					key: "name",
					title: "Player",
					render: (row) => (
						<CareerLink to={`/players/${row.player_id}`}>
							{row.name}
						</CareerLink>
					),
				},
				{ key: "goals", title: "Goals", numeric: true },
				{
					key: "fixture",
					title: "Fixture",
					value: (row) => row.match.opponent,
					render: (row) => (
						<CareerLink to={`/matches/${row.match.id}`}>
							{row.match.home} {display(row.match.home_goals)}–
							{display(row.match.away_goals)} {row.match.away}
						</CareerLink>
					),
				},
				{
					key: "competition",
					title: "Competition",
					value: (row) => row.match.competition.name,
				},
				{
					key: "season",
					title: "Season",
					value: (row) => row.match.season.label,
				},
			]}
		/>
	);
}

export function OverviewHatTricks() {
	const { model, matches } = useCareer();
	const feats = scoringFeats(model, matches);
	const players = feats.career
		.filter((row) => row.hat_tricks > 0)
		.sort(
			(left, right) =>
				right.hat_tricks - left.hat_tricks ||
				left.name.localeCompare(right.name),
		);
	return (
		<section
			className="overview-hat-tricks"
			aria-label="Recorded hat-tricks"
		>
			<SectionHeading title="Recorded hat-tricks">
				<CareerLink
					to="/career?tab=events#scoring-feats"
					className="small-link"
				>
					All scoring feats <ArrowRight size={14} />
				</CareerLink>
			</SectionHeading>
			<div className="hat-trick-total">
				<strong>{feats.hatTricks.length}</strong>
				<span>hat-trick performances in this selection</span>
			</div>
			<div className="hat-trick-players">
				{players.map((player) => (
					<CareerLink
						key={player.id}
						to={`/players/${player.player_id}`}
					>
						<Pill>
							{player.name} · {player.hat_tricks}
						</Pill>
					</CareerLink>
				))}
			</div>
			<ScoringCoverage feats={feats} />
			<details className="hat-trick-details">
				<summary>
					Match-by-match breakdown ({feats.hatTricks.length})
				</summary>
				<HatTrickTable rows={feats.hatTricks} />
			</details>
		</section>
	);
}
