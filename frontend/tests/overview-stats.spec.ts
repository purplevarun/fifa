import { expect, test } from "@playwright/test";
import { fixture } from "./fixture";

const players = [
	fixture.players[0],
	fixture.players[1],
	{
		id: "00000000-0000-4000-8000-000000000091",
		name: "Test Midfielder",
		nationality: null,
	},
	{
		id: "00000000-0000-4000-8000-000000000092",
		name: "Test Defender",
		nationality: null,
	},
];
const goals = [3, 1, 0, 4];
const data = {
	...fixture,
	players,
	matches: fixture.matches.map((match, index) => ({
		...match,
		...(match.home_club_id === fixture.clubs[0].id
			? { home_goals: goals[index] }
			: { away_goals: goals[index] }),
	})),
	player_matches: players.flatMap((player, playerIndex) =>
		fixture.matches.map((match, index) => ({
			...fixture.player_matches[0],
			id: `00000000-0000-4000-8000-${String(100 + playerIndex * 10 + index).padStart(12, "0")}`,
			player_id: player.id,
			match_id: match.id,
			displayed_position: ["ST", "GK", "CM", "CB"][playerIndex],
			goals: playerIndex === 0 ? goals[index] : 0,
			assists: playerIndex === 2 ? 1 : 0,
			passes_completed_short: 10,
			passes_completed_medium: 5,
			passes_completed_long: 2,
			key_passes: 2,
			tackles_won: 3,
			interceptions: 2,
			blocks: 1,
			clearances: 1,
			shots_caught: 4,
			shots_parried: 1,
			goals_conceded: playerIndex === 1 ? 0 : null,
		})),
	),
	competition_events: [
		{
			...fixture.competition_events[0],
			event_type: "player_of_the_month",
			player_id: players[0].id,
			period: "2018-08",
			description:
				"Test Forward earns the EFLLeagueTwo award. PA FIFA19 AFIFA19 EAFIFA19 EFL AFIFA19",
		},
	],
};

test.beforeEach(async ({ page }) => {
	await page.route("**/data/dashboard.json", (route) =>
		route.fulfill({ json: data }),
	);
});

test("position leaders and hat-trick evidence work with filters on desktop and mobile", async ({
	page,
	isMobile,
}, testInfo) => {
	const errors: string[] = [];
	page.on("pageerror", (error) => errors.push(error.message));
	await page.goto("/");
	for (const [title, name] of [
		["Best forward", "Test Forward"],
		["Best midfielder", "Test Defender"],
		["Best defender", "Test Defender"],
		["Best goalkeeper", "Test Goalkeeper"],
		["Best playmaker", "Test Forward"],
	]) {
		const card = page.getByRole("article", { name: title, exact: true });
		await expect(card).toContainText(
			"4/4 appearances with complete scoring data",
		);
		await expect(card).toContainText("All positions");
		await expect(card.getByLabel(`${title} score breakdown`)).toContainText(
			"Games played",
		);
		await expect(
			card.getByRole("link", { name, exact: true }),
		).toBeVisible();
		await expect(card).toContainText("Provisional");
	}
	expect(
		await page
			.locator(".position-grid")
			.evaluate(
				(grid) =>
					getComputedStyle(grid).gridTemplateColumns.split(" ")
						.length,
			),
	).toBe(isMobile ? 1 : 5);
	await page.locator(".stats-methodology > summary").click();
	await expect(page.locator(".stats-methodology")).toContainText(
		"not per-90",
	);
	const feats = page.getByRole("region", {
		name: "Recorded hat-tricks",
		exact: true,
	});
	await expect(feats.locator(".hat-trick-total strong")).toHaveText("2");
	await feats.locator("summary").click();
	await expect(feats.locator("tbody tr")).toHaveCount(2);
	await expect(feats.locator("tbody")).toContainText("4");
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= innerWidth,
		),
	).toBe(true);
	await page.screenshot({
		path: testInfo.outputPath("position-leaders.png"),
		fullPage: true,
		animations: "disabled",
	});

	const preseason = page.getByRole("checkbox", { name: "Include preseason" });
	await preseason.click();
	await expect(preseason).not.toBeChecked();
	await expect(feats.locator(".hat-trick-total strong")).toHaveText("1");
	await page
		.getByRole("combobox", { name: "Competition", exact: true })
		.selectOption(fixture.competitions[0].id);
	await expect(
		page.getByRole("article", { name: "Best forward", exact: true }),
	).toContainText("2/2 appearances with complete scoring data");
	await feats.getByRole("link", { name: "All scoring feats" }).click();
	await expect(
		page.getByRole("heading", { name: "Career records", exact: true }),
	).toBeVisible();
	await expect(page.locator("#scoring-feats")).toContainText(
		"1 hat-tricks / selected fixtures",
	);
	await expect(
		page.getByRole("heading", { name: "Selected totals", exact: true }),
	).toBeVisible();
	const table = page.getByRole("region", {
		name: "hat-trick matches table",
		exact: true,
	});
	await expect(table.locator("tbody tr")).toHaveCount(1);
	await table.getByRole("link", { name: /Notts County/ }).click();
	await expect(page.locator(".match-score")).toBeVisible();
	await expect(
		page.getByRole("combobox", { name: "Competition", exact: true }),
	).toHaveValue(fixture.competitions[0].id);
	expect(errors).toEqual([]);
});

test("award cards omit sponsor noise but full records retain original evidence", async ({
	page,
}) => {
	await page.goto("/#/career?tab=events");
	const event = page.locator(".event-record");
	await expect(event).toContainText(
		"Test Forward earns the EFL League Two award.",
	);
	await expect(event).not.toContainText("AFIFA19");
	await event.getByRole("button", { name: "Full record" }).click();
	await expect(page.getByRole("dialog")).toContainText("AFIFA19");
	await expect(page.getByRole("dialog")).toContainText("EFLLeagueTwo");
});
