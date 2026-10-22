import { describe, expect, it } from "vitest";
import cases from "../../processing/tests/fixtures/vocab_cases.json";
import { eventDescription } from "./data";
import { splitJoinedWords, Vocabulary } from "./vocabulary";

describe("shared OCR vocabulary", () => {
	it.each(cases)(
		"conservatively repairs $input",
		({ words, input, expected }) => {
			const split = words
				? (text: string) => new Vocabulary(words).splitText(text)
				: splitJoinedWords;
			expect(split(input)).toBe(expected);
			expect(split(expected)).toBe(expected);
			expect(split(input).replace(/\s/g, "")).toBe(
				input.replace(/\s/g, ""),
			);
		},
	);
	it("does not partially split long tokens or consume mixed Unicode identifiers", () => {
		for (const value of [
			"goals".repeat(1000),
			"球Countyearned",
			"e\u0301Countyearned",
			"forNotts_unknown",
		])
			expect(splitJoinedWords(value)).toBe(value);
	});
	it.each([[""], ["two words"], ["FIFA19"], ["typo!"]])(
		"rejects invalid vocabulary entries: %j",
		(word) => {
			expect(() => new Vocabulary([word])).toThrow(
				/array of English words/,
			);
		},
	);
	it("repairs old award descriptions while preserving raw text and sponsor cleanup", () => {
		const event = {
			event_type: "player_of_the_month",
			description:
				"Kubo'simpressiveperformanceforNotts Countyearned himthe EFLChampionship award. PA FIFA19 AFIFA19 EAFIFA19",
		};
		expect(eventDescription(event)).toBe(
			"Kubo's impressive performance for Notts County earned him the EFL Championship award.",
		);
		expect(event.description).toContain("impressiveperformanceforNotts");
		expect(event.description).toContain("AFIFA19");
	});
});
