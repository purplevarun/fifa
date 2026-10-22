import { expect, test } from "@playwright/test";
import { fixture as data } from "./fixture";

test.beforeEach(async ({ page }) => {
	await page.route("**/data/dashboard.json", (route) =>
		route.fulfill({ json: data }),
	);
});
const season = data.seasons.find((season) => season.label === "2018/19")!;
const league = data.competitions.find(
	(competition) => competition.name === "EFL League Two",
)!;
const player = data.players.find((player) => player.name === "Test Forward")!;
const shootout = data.matches.find(
	(match) => match.played_on === "2019-02-14",
)!;
const nottsId = data.clubs.find((club) => club.name === "Notts County")!.id;

test("overview preserves filters, preseason and mobile navigation", async ({
	page,
	isMobile,
}, testInfo) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto("/");
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toBeVisible();
	await expect(
		page.getByText("4 recorded matches", { exact: true }),
	).toBeVisible();
	await expect(page.locator(".overview-ranking")).toHaveCount(6);
	for (const title of [
		"Leading scorers",
		"Most assists",
		"Most appearances",
		"Most passes completed",
		"Most tackles won",
		"Highest rated players",
	]) {
		await expect(
			page.getByRole("heading", { name: title, exact: true }),
		).toBeVisible();
	}
	await expect(
		page.getByRole("heading", {
			name: "Goals across the career",
			exact: true,
		}),
	).toHaveCount(0);
	expect(
		await page
			.locator("[data-ranking-count]")
			.evaluateAll((charts) =>
				charts.every(
					(chart) =>
						Number(chart.getAttribute("data-ranking-count")) <= 5,
				),
			),
	).toBe(true);
	await page.getByRole("checkbox", { name: "Include preseason" }).click();
	await expect(
		page.getByText("3 recorded matches", { exact: true }),
	).toBeVisible();
	await expect(
		page.getByRole("checkbox", { name: "Include preseason" }),
	).not.toBeChecked();
	await page
		.getByRole("combobox", { name: "Competition", exact: true })
		.selectOption(league.id);
	await expect(
		page.getByText("2 recorded matches", { exact: true }),
	).toBeVisible();
	await page.reload();
	await expect(
		page.getByRole("combobox", { name: "Competition", exact: true }),
	).toHaveValue(league.id);
	await page
		.getByRole("button", { name: "Reset filters", exact: true })
		.click();
	if (isMobile)
		await page
			.getByRole("button", { name: "Open navigation", exact: true })
			.click();
	await page
		.getByRole("navigation", { name: "Main navigation" })
		.getByRole("link", { name: "Players", exact: true })
		.click();
	await expect(
		page.getByRole("heading", { name: "Players", exact: true }),
	).toBeVisible();
	await page.goto("/");
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toBeVisible();
	await expect(page.locator(".recharts-surface").first()).toBeVisible();
	await expect(
		page.getByRole("link", { name: "Source images", exact: true }),
	).toHaveCount(0);
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
	await page.screenshot({
		path: testInfo.outputPath("overview.png"),
		fullPage: true,
		animations: "disabled",
	});
	expect(errors).toEqual([]);
});

test("an open dashboard follows replaced and recreated JSON without an API", async ({
	page,
}) => {
	let revision: string | null = "original";
	const apiRequests: string[] = [];
	page.on("request", (request) => {
		if (new URL(request.url()).pathname.startsWith("/api/"))
			apiRequests.push(request.url());
	});
	const fresh = {
		...data,
		players: data.players.map((entry) =>
			entry.id === player.id ? { ...entry, name: "Fresh Player" } : entry,
		),
	};
	await page.route("**/data/dashboard.json", (route) => {
		if (revision === null)
			return route.fulfill({ status: 404, body: "Not found" });
		const etag = `"${revision}"`;
		if (route.request().headers()["if-none-match"] === etag)
			return route.fulfill({ status: 304 });
		return route.fulfill({
			json: revision === "rebuilt" ? fresh : data,
			headers: { ETag: etag },
		});
	});
	await page.goto("/");
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toBeVisible();
	await expect(page.getByLabel("Dataset processing")).toContainText(
		"dashboard.json",
	);

	revision = "rebuilt";
	await expect(
		page.locator('[data-statistic="goals"] [role="img"]'),
	).toHaveAttribute("aria-label", /Fresh Player/, { timeout: 10000 });
	await expect(page.getByRole("alert")).toHaveCount(0);

	revision = null;
	await expect(page.getByRole("alert")).toHaveText(
		"Waiting for dashboard.json. Run ./run process to generate it.",
		{ timeout: 10000 },
	);
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toHaveCount(0);

	revision = "rebuilt";
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toBeVisible({ timeout: 10000 });
	await expect(
		page.locator('[data-statistic="goals"] [role="img"]'),
	).toHaveAttribute("aria-label", /Fresh Player/);
	await expect(page.getByRole("alert")).toHaveCount(0);
	expect(apiRequests).toEqual([]);
});

test("fixture search, score and player records work without screenshots", async ({
	page,
}, testInfo) => {
	await page.goto("/#/matches");
	await page
		.getByRole("textbox", { name: "Search fixtures or opponents" })
		.fill("2019-02-14");
	await expect(page.locator("tbody tr")).toHaveCount(1);
	await page.locator(".fixture-link").click();
	await expect(page.locator(".match-score")).toContainText(
		"4-3 on penalties",
	);
	const count = data.player_matches.filter(
		(row) => row.match_id === shootout.id && row.club_id === nottsId,
	).length;
	await expect(page.locator("tbody tr")).toHaveCount(count);
	await page.locator("tbody .text-link").first().click();
	await expect(page.getByRole("dialog")).toBeVisible();
	await expect(
		page.getByRole("heading", { name: "Passing", exact: true }),
	).toBeVisible();
	await page.getByRole("button", { name: "Close dialog" }).click();
	await expect(
		page.getByRole("button", { name: "View source screenshot" }),
	).toHaveCount(0);
	await page.screenshot({
		path: testInfo.outputPath("match.png"),
		animations: "disabled",
	});
	await page.keyboard.press("Escape");
	await expect(page.getByRole("dialog")).toHaveCount(0);
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
});

test("player totals and development remain distinct from match data", async ({
	page,
}, testInfo) => {
	await page.goto(`/#/players/${player.id}?season=${season.id}`);
	await expect(
		page.getByRole("heading", { name: player.name, exact: true }),
	).toBeVisible();
	await expect(
		page.locator(".kpi").filter({ hasText: "Goals" }).locator("strong"),
	).toContainText("2");
	await page.getByRole("tab", { name: "Season totals" }).click();
	await expect(page.locator("tbody tr")).toHaveCount(3);
	const total = page
		.locator("tbody tr")
		.filter({ hasText: "All competitions" });
	await expect(total).toContainText("3");
	await expect(total).toContainText("2");
	await expect(total).toContainText("1");
	await page.getByRole("tab", { name: "Development" }).click();
	await expect(
		page.getByRole("heading", { name: "Recorded overall history" }),
	).toBeVisible();
	await expect(
		page.locator("tbody").getByText("Season End", { exact: true }),
	).toBeVisible();
	await page.screenshot({
		path: testInfo.outputPath("development.png"),
		fullPage: true,
		animations: "disabled",
	});
	await page.getByRole("tab", { name: "Player record" }).click();
	await expect(page.locator(".record-details")).toContainText(player.id);
});

test("competitions preserve League Two points and preseason editions", async ({
	page,
}) => {
	await page.goto(`/#/competitions/${league.id}`);
	await expect(
		page.getByRole("heading", { name: league.name, exact: true }),
	).toBeVisible();
	await expect(
		page
			.locator(".kpi")
			.filter({ hasText: "Points from results" })
			.locator("strong"),
	).toHaveText("4");
	await page.goto("/#/competitions");
	await expect(page.locator(".competition-card")).toHaveCount(3);
	await expect(
		page.locator(".competition-card").filter({ hasText: "Preseason" }),
	).toHaveCount(1);
});

test("verification exposes partial comparisons and the goal warning", async ({
	page,
}) => {
	await page.goto("/#/audit");
	await expect(
		page.getByRole("heading", { name: "Verification", exact: true }),
	).toBeVisible();
	await page
		.getByRole("textbox", { name: "Search reconciliation records" })
		.fill("Test Goalkeeper");
	await expect(page.locator("tbody tr")).toHaveCount(1);
	await expect(
		page.locator("tbody").getByText("Partial", { exact: true }).first(),
	).toBeVisible();
	await page.locator("tbody .text-link").first().click();
	await expect(page.getByRole("dialog")).toContainText("raw_match_average");
	await page.keyboard.press("Escape");
	await page.getByRole("tab", { name: "Warnings (1)" }).click();
	await expect(page.locator(".warning-record")).toContainText("Portsmouth");
	await expect(page.locator(".warning-record")).toContainText(
		"Player goals exceed team score",
	);
	await expect(page.locator(".warning-record")).not.toContainText(
		"undefined",
	);
	await page.getByRole("link", { name: "Open match" }).click();
	await expect(page.locator(".notice.warning")).toContainText(
		"Credited player goals: 2",
	);
});

test("all exported tables and full UUID records can be inspected", async ({
	page,
}) => {
	await page.goto("/#/data");
	await expect(
		page.getByRole("combobox", { name: "Dataset table" }),
	).toBeVisible();
	await expect(
		page.getByRole("combobox", { name: "Dataset table" }).locator("option"),
	).toHaveCount(12);
	await page
		.getByRole("combobox", { name: "Dataset table" })
		.selectOption("players");
	await page
		.getByRole("textbox", { name: "Search players", exact: true })
		.fill(player.id);
	await expect(page.locator("tbody tr")).toHaveCount(1);
	await page.locator("tbody .text-link").click();
	await expect(page.getByRole("dialog")).toContainText(player.id);
	await page.keyboard.press("Escape");
	await page
		.getByRole("combobox", { name: "Dataset table" })
		.selectOption("player_matches");
	await expect(page.locator(".record-count")).toContainText("5");
	await expect(
		page.getByRole("columnheader", { name: "Goals Conceded Basis" }),
	).not.toBeAttached();
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
});

test("career records are available without an image archive", async ({
	page,
}) => {
	await page.goto("/#/career");
	await expect(page.locator(".transfer-record")).toHaveCount(1);
	await expect(
		page.locator(".transfer-record").filter({ hasText: "Test Forward" }),
	).toContainText("24 months");
	await page.getByRole("tab", { name: "Honours & events (1)" }).click();
	await expect(page.locator(".event-record")).toHaveCount(1);
	await expect(
		page.getByRole("link", { name: "Source images", exact: true }),
	).toHaveCount(0);
});

test("download exports actual data and missing data can recover", async ({
	page,
}) => {
	await page.route("**/data/dashboard.json", (route) =>
		route.fulfill({ status: 503, body: "Unavailable" }),
	);
	await page.goto("/");
	await expect(page.getByRole("alert")).toContainText(
		"Career data request failed (503)",
	);
	await page.unroute("**/data/dashboard.json");
	await page.route("**/data/dashboard.json", (route) =>
		route.fulfill({ json: data }),
	);
	await page.getByRole("button", { name: "Retry" }).click();
	await expect(
		page.getByRole("heading", { name: "Career overview", exact: true }),
	).toBeVisible();
	const pending = page.waitForEvent("download");
	await page
		.getByRole("button", { name: "Download complete data", exact: true })
		.click();
	const download = await pending;
	expect(download.suggestedFilename()).toBe("notts-county-career.json");
	expect(await download.failure()).toBeNull();
});
