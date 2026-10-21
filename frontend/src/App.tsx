import {
	Activity,
	ArrowRightLeft,
	CalendarDays,
	ChartNoAxesCombined,
	Database,
	Download,
	LoaderCircle,
	Menu,
	RefreshCw,
	RotateCcw,
	ShieldCheck,
	Trophy,
	Users,
	X,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
	HashRouter,
	NavLink,
	Route,
	Routes,
	useLocation,
	useSearchParams,
} from "react-router-dom";
import "./App.css";
import { Audit, CareerRecords, Explorer } from "./archive";
import nottsCountyCrest from "./assets/notts-county-crest.png";
import { CareerContext } from "./context";
import type { Filters, Model } from "./data";
import { createModel, dateLabel, downloadJson, selectMatches } from "./data";
import { loadStaticCareerDataset, watchCareerDataset } from "./loadData";
import {
	CompetitionDetail,
	Competitions,
	MatchDetail,
	Matches,
	Overview,
	PlayerDetail,
	Players,
	UnknownPage,
} from "./pages";
import { IconButton } from "./ui";
function Shell({
	model,
	reload,
	refreshing,
}: {
	model: Model;
	reload: () => void;
	refreshing: boolean;
}) {
	const [parameters, setParameters] = useSearchParams();
	const location = useLocation();
	const [mobileMenu, setMobileMenu] = useState(false);
	const filters: Filters = {
		season: model.seasons.has(parameters.get("season") ?? "")
			? parameters.get("season")!
			: "all",
		competition: model.competitions.has(parameters.get("competition") ?? "")
			? parameters.get("competition")!
			: "all",
		preseason: parameters.get("preseason") !== "false",
	};
	const matches = selectMatches(model, filters);
	const archiveWide =
		["/audit", "/data"].includes(location.pathname) ||
		(location.pathname === "/career" && parameters.get("tab") !== "events");
	const navigation = [
		{ path: "/", label: "Overview", icon: ChartNoAxesCombined },
		{ path: "/matches", label: "Matches", icon: CalendarDays },
		{ path: "/players", label: "Players", icon: Users },
		{ path: "/competitions", label: "Competitions", icon: Trophy },
		{ path: "/career", label: "Career records", icon: ArrowRightLeft },
		{ path: "/audit", label: "Verification", icon: ShieldCheck },
		{ path: "/data", label: "Data explorer", icon: Database },
	];
	function changeFilters(next: Partial<Filters>) {
		const updated = { ...filters, ...next },
			query = new URLSearchParams(parameters);
		for (const key of ["season", "competition"] as const) {
			if (updated[key] === "all") query.delete(key);
			else query.set(key, updated[key]);
		}
		if (updated.preseason) query.delete("preseason");
		else query.set("preseason", "false");
		setParameters(query);
	}
	return (
		<CareerContext value={{ model, filters, matches }}>
			<a
				href="#main-content"
				className="skip-link"
				onClick={(event) => {
					event.preventDefault();
					document.getElementById("main-content")?.focus();
				}}
			>
				Skip to content
			</a>
			<div className="app-shell">
				{mobileMenu && (
					<button
						className="nav-backdrop"
						aria-label="Close navigation"
						onClick={() => setMobileMenu(false)}
					/>
				)}
				<aside className={`sidebar ${mobileMenu ? "open" : ""}`}>
					<div className="brand">
						<img
							src={nottsCountyCrest}
							alt="Notts County crest"
							className="club-mark"
							width={32}
							height={43}
							draggable={false}
						/>
						<div>
							<strong>NOTTS COUNTY</strong>
							<span>CAREER ARCHIVE</span>
						</div>
						<button
							className="mobile-nav-close icon-button"
							aria-label="Close navigation"
							onClick={() => setMobileMenu(false)}
						>
							<X size={19} />
						</button>
					</div>
					<div className="sidebar-season">
						<span className="status-dot" />
						FIFA 19
						<span className="muted">
							{model.matches.length
								? `${model.matches[0].played_on.slice(0, 4)} - ${model.matches.at(-1)?.played_on.slice(0, 4)}`
								: "No matches"}
						</span>
					</div>
					<nav aria-label="Main navigation">
						{navigation.map(
							({ path, label, icon: Icon }, index) => (
								<NavLink
									end={path === "/"}
									key={path}
									to={`${path}${location.search}`}
									onClick={() => setMobileMenu(false)}
									className={({ isActive }) =>
										`nav-item ${isActive ? "active" : ""} ${index === 4 ? "nav-divider" : ""}`
									}
								>
									<Icon size={18} strokeWidth={1.7} />
									<span>{label}</span>
									{path === "/audit" &&
										model.data.match_coverage.warnings
											.length > 0 && (
											<span className="nav-count">
												{
													model.data.match_coverage
														.warnings.length
												}
											</span>
										)}
								</NavLink>
							),
						)}
					</nav>
					<div className="sidebar-footer">
						<Activity size={16} />
						<div>
							<strong>Read-only archive</strong>
							<span>
								SQLite export / v{model.data.schema_version}
							</span>
						</div>
					</div>
				</aside>
				<div className="main-shell">
					<header className="topbar">
						<button
							className="mobile-menu icon-button"
							aria-label="Open navigation"
							onClick={() => setMobileMenu(true)}
						>
							<Menu size={20} />
						</button>
						<div className="topbar-title">
							<span className="eyebrow">Notts County</span>
							<span className="muted">Manager career</span>
						</div>
						<div className="topbar-actions">
							<span className="captured-through">
								Captured through{" "}
								<strong>
									{dateLabel(
										model.matches.at(-1)?.played_on ?? null,
										true,
									)}{" "}
									{model.matches
										.at(-1)
										?.played_on.slice(0, 4)}
								</strong>
							</span>
							<IconButton
								label="Reload exported data"
								onClick={reload}
								disabled={refreshing}
							>
								<RefreshCw
									size={17}
									className={refreshing ? "spinning" : ""}
								/>
							</IconButton>
							<IconButton
								label="Download complete data"
								onClick={() =>
									downloadJson(
										model.data,
										"notts-county-career.json",
									)
								}
							>
								<Download size={17} />
							</IconButton>
						</div>
					</header>
					<div className="filterbar">
						{archiveWide ? (
							<div className="archive-scope">
								<Database size={15} />
								<span>Full archive</span>
								<span className="muted">
									{model.matches.length.toLocaleString()}{" "}
									matches
								</span>
							</div>
						) : (
							<>
								<label>
									Season
									<select
										aria-label="Season"
										value={filters.season}
										onChange={(event) =>
											changeFilters({
												season: event.target.value,
											})
										}
									>
										<option value="all">All seasons</option>
										{model.data.seasons.map((season) => (
											<option
												key={season.id}
												value={season.id}
											>
												{season.label}
											</option>
										))}
									</select>
								</label>
								<label>
									Competition
									<select
										aria-label="Competition"
										value={filters.competition}
										onChange={(event) =>
											changeFilters({
												competition: event.target.value,
											})
										}
									>
										<option value="all">
											All competitions
										</option>
										{model.data.competitions.map(
											(competition) => (
												<option
													key={competition.id}
													value={competition.id}
												>
													{competition.name}
												</option>
											),
										)}
									</select>
								</label>
								<label className="checkbox">
									<input
										type="checkbox"
										checked={filters.preseason}
										onChange={(event) =>
											changeFilters({
												preseason: event.target.checked,
											})
										}
									/>
									Include preseason
								</label>
								<div className="grow" />
								<IconButton
									label="Reset filters"
									onClick={() =>
										changeFilters({
											season: "all",
											competition: "all",
											preseason: true,
										})
									}
								>
									<RotateCcw size={16} />
								</IconButton>
							</>
						)}
					</div>
					<main
						id="main-content"
						tabIndex={-1}
						key={location.pathname}
					>
						<Routes>
							<Route path="/" element={<Overview />} />
							<Route path="/matches" element={<Matches />} />
							<Route
								path="/matches/:id"
								element={<MatchDetail />}
							/>
							<Route path="/players" element={<Players />} />
							<Route
								path="/players/:id"
								element={<PlayerDetail />}
							/>
							<Route
								path="/competitions"
								element={<Competitions />}
							/>
							<Route
								path="/competitions/:id"
								element={<CompetitionDetail />}
							/>
							<Route path="/career" element={<CareerRecords />} />
							<Route path="/audit" element={<Audit />} />
							<Route path="/data" element={<Explorer />} />
							<Route path="*" element={<UnknownPage />} />
						</Routes>
					</main>
					<footer className="app-footer">
						<span>NOTTS COUNTY / CAREER DATA</span>
						<span>
							Loaded{" "}
							{new Date(model.data.generated_at).toLocaleString(
								"en-GB",
							)}
						</span>
					</footer>
				</div>
			</div>
		</CareerContext>
	);
}
function App() {
	const [model, setModel] = useState<Model | null>(null),
		[error, setError] = useState<string | null>(null);
	const [reload, setReload] = useState(0),
		[refreshing, setRefreshing] = useState(true);
	function requestReload() {
		setRefreshing(true);
		setReload((value) => value + 1);
	}
	useEffect(() => {
		if (import.meta.env.PROD) {
			const controller = new AbortController();
			void (async () => {
				try {
					const data = await loadStaticCareerDataset(
						fetch,
						"./data/dashboard.json",
						controller.signal,
					);
					if (controller.signal.aborted) return;
					setModel(createModel(data));
					setError(null);
				} catch (reason) {
					if (controller.signal.aborted) return;
					setModel(null);
					setError(
						reason instanceof Error
							? reason.message
							: "Could not load career data.",
					);
				} finally {
					if (!controller.signal.aborted) setRefreshing(false);
				}
			})();
			return () => {
				controller.abort();
			};
		}
		return watchCareerDataset(fetch, {
			onData(data) {
				setModel(createModel(data));
				setError(null);
			},
			onMissing() {
				setModel(null);
				setError("Waiting for processed career data.");
			},
			onError(reason) {
				setModel(null);
				setError(
					reason instanceof Error
						? reason.message
						: "Could not load career data.",
				);
			},
			onSettled() {
				setRefreshing(false);
			},
		});
	}, [reload]);
	if (!model)
		return (
			<div className="load-screen">
				<img
					src={nottsCountyCrest}
					alt="Notts County crest"
					width={64}
					height={85}
					draggable={false}
				/>
				<h1>Notts County</h1>
				{error ? (
					<>
						<p role="alert">{error}</p>
						<button
							className="button primary"
							onClick={requestReload}
						>
							Retry <RefreshCw size={16} />
						</button>
					</>
				) : (
					<>
						<LoaderCircle className="spinning" size={22} />
						<p>Loading career records</p>
					</>
				)}
			</div>
		);
	return (
		<HashRouter>
			{error && (
				<div role="alert" className="reload-error">
					{error}
				</div>
			)}
			<Shell
				model={model}
				reload={requestReload}
				refreshing={refreshing}
			/>
		</HashRouter>
	);
}

export default App;
