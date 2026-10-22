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
	const pages = await development.ssrLoadModule("/src/pages.tsx");
	const archive = await development.ssrLoadModule("/src/archive.tsx");
	const model = createModel(published);
	const context = {
		model,
		filters: defaultFilters,
		matches: selectMatches(model, defaultFilters),
	};
	for (const [path, Component] of [
		["/", pages.Overview],
		["/matches", pages.Matches],
		["/players", pages.Players],
		["/competitions", pages.Competitions],
		["/career", archive.CareerRecords],
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
