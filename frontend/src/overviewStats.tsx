import { ArrowRight, Trophy } from "lucide-react";
import type { CSSProperties } from "react";
import { awardScoring, positionRankings, scoringFeats } from "./analytics";
import { useCareer } from "./context";
import { dateLabel, display } from "./data";
import { CareerLink, DataTable, Empty, Pill, SectionHeading } from "./ui";

export function PositionLeaders() {
	const { model, matches } = useCareer();
	const rankings = positionRankings(model, matches);
	return (
		<section className="position-leaders" aria-label="Performance awards">
			<SectionHeading title="Performance awards">
				<Pill>Stats-based / selected fixtures</Pill>
			</SectionHeading>
			<p className="muted position-intro">
				Every player is considered for every award, regardless of
				position. {awardScoring.contribution}% contribution /{" "}
				{awardScoring.perGame}% per-game performance /{" "}
				{awardScoring.games}% games played.
			</p>
			<div className="position-grid">
				{rankings.roles.map((group) => {
					const winner = group.candidates[0];
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
								All positions · {group.consideredPlayers}{" "}
								players considered
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
										appearances with complete scoring data
									</p>
									{winner.known <
										awardScoring.provisionalAppearances && (
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
									<dl
										className="award-breakdown"
										aria-label={`${group.title} score breakdown`}
									>
										<div>
											<dt>Total contribution</dt>
											<dd>
												{display(
													winner.breakdown
														.contribution,
													1,
												)}{" "}
												/ {awardScoring.contribution}
											</dd>
										</div>
										<div>
											<dt>Per-game performance</dt>
											<dd>
												{display(
													winner.breakdown.perGame,
													1,
												)}{" "}
												/ {awardScoring.perGame}
											</dd>
										</div>
										<div>
											<dt>Games played</dt>
											<dd>
												{display(
													winner.breakdown.games,
													1,
												)}{" "}
												/ {awardScoring.games}
											</dd>
										</div>
									</dl>
									<dl className="position-metrics">
										{winner.metrics.map((component) => (
											<div key={component.field}>
												<dt>
													{component.label}
													<small>
														{component.weight}% of
														stat components
													</small>
												</dt>
												<dd
													title={`${display(component.total)} across ${winner.known} complete appearances; ${display(component.points, 1)} score points`}
												>
													{display(component.total)}{" "}
													total
													<small>
														{display(
															component.perAppearance,
															2,
														)}{" "}
														per game
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
									<strong>
										No player with enough scoring data
									</strong>
									<p>
										Needs recorded category stats in at
										least{" "}
										{awardScoring.minimumCoverage * 100}% of
										appearances and a measured contribution.
										Games alone cannot earn an award.
									</p>
								</div>
							)}
							{group.insufficientDataPlayers > 0 && (
								<p className="tiny muted">
									{group.insufficientDataPlayers} players lack
									enough recorded stats for this award; no
									position restriction.
								</p>
							)}
							{group.noContributionPlayers > 0 && (
								<p className="tiny muted">
									{group.noContributionPlayers} players have
									no measured contribution in these stats.
								</p>
							)}
						</article>
					);
				})}
			</div>
			<details className="stats-methodology">
				<summary>How the award scores work</summary>
				<p>
					Only Notts County appearances in the selected season,
					competition and preseason scope count. Every player can rank
					for every award, including players with unknown positions.
					Position changes never split their records. These are
					statistical awards, not FIFA overall ratings.
				</p>
				<p>
					{awardScoring.contribution}% rewards accumulated
					contribution, {awardScoring.perGame}% rewards per-game
					performance, and {awardScoring.games}% rewards games played.
					The stat weights below apply inside both performance
					components. Each total and per-game rate is divided by the
					best recorded value for that metric among scored candidates;
					games points are {awardScoring.games} × complete appearances
					/ most complete appearances in that candidate pool.
				</p>
				<p>
					For example, comparing only a 3-goal debut with 100 goals in
					100 games (both with no assists), the forward scores are
					21.6 and 69.7 respectively. Sustained production outweighs a
					one-game spike. A metric that is zero for everyone earns
					zero, and games alone cannot turn zero contribution into a
					winner. Scores are relative within each award and filter
					selection, not comparable across awards.
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
					At least one complete appearance and{" "}
					{awardScoring.minimumCoverage * 100}% coverage of all
					selected appearances are required. All components use the
					same complete records, including games points, so missing
					stats do not inflate experience. Unknown values are never
					replaced with zeros. Players lacking goalkeeper statistics,
					for example, cannot receive a meaningful goalkeeper
					score—not because of their position. Under{" "}
					{awardScoring.provisionalAppearances} complete appearances
					is provisional, not excluded. Ties use more complete
					appearances, then name. Minutes are not consistently
					recorded, so these are not per-90 scores.
				</p>
				<p>
					Defensive actions mean interceptions + blocks + clearances.
					Saves mean shots caught + parried. Goalkeeper clean sheets
					require a recorded zero goals-conceded value; this is an
					appearance measure, not a 90-minute clean-sheet award. For
					goals conceded, quality is 1 / (1 + goals conceded per
					game); accumulated contribution is that quality × complete
					appearances. This rewards sustained prevention, never
					conceding more goals.
				</p>
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
