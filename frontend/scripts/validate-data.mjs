import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { createServer, preview } from "vite";

// Validate the real generated dataset without requiring a browser automation policy.
const root = fileURLToPath(new URL("../", import.meta.url));
const published = JSON.parse(
	await readFile(
		new URL("../public/data/dashboard.json", import.meta.url),
		"utf8",
	),
);
assert.equal(published.processing?.last_run?.status, "completed");
const options = {
	root,
	logLevel: "error",
	server: { host: "127.0.0.1", port: 0 },
	preview: { host: "127.0.0.1", port: 0 },
};
let development;
let production;
try {
	development = await createServer(options);
	await development.listen();
	const { createModel, defaultFilters, selectMatches } =
		await development.ssrLoadModule("/src/data.ts");
	const { CareerContext } =
		await development.ssrLoadModule("/src/context.ts");
	const { positionRankings, scoringFeats } =
		await development.ssrLoadModule("/src/analytics.ts");
	const { splitJoinedWords } =
		await development.ssrLoadModule("/src/vocabulary.ts");
	const pages = await development.ssrLoadModule("/src/pages.tsx");
	const archive = await development.ssrLoadModule("/src/archive.tsx");
	const model = createModel(published);
	const context = {
		model,
		filters: defaultFilters,
		matches: selectMatches(model, defaultFilters),
	};
	const repairedDescriptions = published.competition_events.filter(
		(event) => {
			const original = event.description ?? "";
			const repaired = splitJoinedWords(original);
			assert.equal(
				repaired.replace(/\s/g, ""),
				original.replace(/\s/g, ""),
			);
			return repaired !== original;
		},
	).length;
	// Test the browser's module path too: the shared JSON is outside frontend/.
	const developmentOrigin = `http://127.0.0.1:${development.httpServer.address().port}`;
	const vocabularyModule = await fetch(
		`${developmentOrigin}/src/vocabulary.ts`,
	);
	assert.equal(vocabularyModule.status, 200);
	const vocabularyImport = (await vocabularyModule.text()).match(
		/from\s*["']([^"']*vocab\.json[^"']*)["']/,
	);
	assert.ok(
		vocabularyImport,
		"The browser module must import the shared vocabulary",
	);
	const vocabularyResponse = await fetch(
		new URL(vocabularyImport[1], developmentOrigin),
	);
	assert.equal(
		vocabularyResponse.status,
		200,
		"The shared vocabulary must be readable in development",
	);
	assert.ok((await vocabularyResponse.text()).includes('"impressive"'));
	const feats = scoringFeats(model, context.matches);
	assert.equal(
		feats.hatTricks.length,
		published.player_matches.filter(
			(row) => row.club_id === model.nottsId && row.goals >= 3,
		).length,
		"Hat-tricks must match individual 3+ goal performances",
	);
	const positionLeaders = positionRankings(model, context.matches).roles;
	for (const group of positionLeaders) {
		for (const candidate of group.candidates) {
			assert.ok(
				Number.isFinite(candidate.score) &&
					candidate.score > 0 &&
					candidate.score <= 100 + 1e-9,
			);
			assert.ok(
				candidate.known <= candidate.total &&
					candidate.known / candidate.total >= 0.8,
			);
		}
	}
	for (const [path, Component] of [
		["/", pages.Overview],
		["/matches", pages.Matches],
		["/players", pages.Players],
		["/competitions", pages.Competitions],
		["/career", archive.CareerRecords],
		["/career?tab=events", archive.CareerRecords],
		["/audit", archive.Audit],
		["/data", archive.Explorer],
	]) {
		const html = renderToStaticMarkup(
			createElement(
				MemoryRouter,
				{ initialEntries: [path] },
				createElement(
					CareerContext,
					{ value: context },
					createElement(Component),
				),
			),
		);
		assert.ok(html.length > 0, `${path} must render`);
		console.log(`Rendered ${path} using the generated dashboard.json.`);
	}

	production = await preview(options);
	for (const [name, server] of [
		["development", development],
		["production preview", production],
	]) {
		const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
		const headers = { Accept: "application/json" };
		const response = await fetch(`${origin}/data/dashboard.json`, {
			headers,
			cache: "no-store",
		});
		assert.equal(response.status, 200);
		assert.deepEqual(
			await response.json(),
			published,
			`${name}: rebuild before validating`,
		);
		const etag = response.headers.get("etag");
		assert.ok(etag);
		const unchanged = await fetch(`${origin}/data/dashboard.json`, {
			headers: { ...headers, "If-None-Match": etag },
			cache: "no-store",
		});
		assert.equal(unchanged.status, 304);
		for (const path of [
			"/api/stats",
			"/api/stats/version",
			"/data/missing-dashboard.json",
		]) {
			assert.equal((await fetch(origin + path, { headers })).status, 404);
		}
		console.log(
			`${name}: JSON matches, conditional refresh works, no database API.`,
		);
	}
	console.log(
		JSON.stringify(
			{
				validated: true,
				processing_run: published.processing.last_run.id,
				matches: model.matches.length,
				players: model.players.size,
				appearances: published.player_matches.length,
				hat_tricks: feats.hatTricks.length,
				vocabulary_repaired_descriptions: repairedDescriptions,
				position_leaders: positionLeaders.map((group) => ({
					role: group.role,
					player: group.candidates[0]?.name ?? null,
					score: group.candidates[0]?.score ?? null,
					complete_appearances: group.candidates[0]?.known ?? 0,
				})),
			},
			null,
			2,
		),
	);
} finally {
	if (production) {
		await new Promise((resolve) => {
			production.httpServer.close(resolve);
			production.httpServer.closeAllConnections();
		});
	}
	if (development) await development.close();
}
