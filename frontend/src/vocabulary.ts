import vocabularyData from "../../vocab.json";

const wordPattern = /^[a-z]+(?:['’-][a-z]+)*$/i;
const tokenPattern = /[\p{L}\p{N}\p{M}_]+(?:['’-][\p{L}\p{N}\p{M}_]+)*/gu;
const maxTokenLength = 160;

export class Vocabulary {
	private readonly words: Set<string>;
	private readonly maxWordLength: number;

	constructor(words: readonly string[]) {
		if (
			!Array.isArray(words) ||
			words.some(
				(word) => typeof word !== "string" || !wordPattern.test(word),
			)
		)
			throw new Error(
				"vocab.json words must be an array of English words",
			);
		this.words = new Set(words.map((word) => word.toLowerCase()));
		this.maxWordLength = words.reduce(
			(longest, word) => Math.max(longest, word.length),
			0,
		);
	}

	private segments(token: string): number[] | null {
		if (!/^[A-Za-z]+$/.test(token) || token.length > maxTokenLength)
			return null;
		const lowered = token.toLowerCase();
		if (this.words.has(lowered)) return [token.length];
		const ways = Array<number>(token.length + 1).fill(0);
		const previous = Array<number>(token.length + 1).fill(0);
		ways[0] = 1;
		for (let end = 1; end <= token.length; end += 1) {
			for (
				let start = Math.max(0, end - this.maxWordLength);
				start < end;
				start += 1
			) {
				if (ways[start] && this.words.has(lowered.slice(start, end))) {
					ways[end] = Math.min(2, ways[end] + ways[start]);
					previous[end] = start;
					if (ways[end] === 2) break;
				}
			}
		}
		if (ways[token.length] !== 1) return null;
		const boundaries: number[] = [];
		for (let end = token.length; end > 0; end = previous[end])
			boundaries.push(end);
		return boundaries.reverse();
	}

	private splitToken(token: string): string {
		if (this.words.has(token.toLowerCase())) return token;
		const possessive = token.match(/^([A-Za-z]+)(['’]s)([A-Za-z]{2,})$/);
		if (
			possessive &&
			this.words.has(possessive[1].toLowerCase()) &&
			this.segments(possessive[3])
		)
			return (
				possessive[1] +
				possessive[2] +
				" " +
				this.splitToken(possessive[3])
			);
		const boundaries = this.segments(token);
		if (!boundaries) return token;
		let start = 0;
		return boundaries
			.map((end) => {
				const part = token.slice(start, end);
				start = end;
				return part;
			})
			.join(" ");
	}

	splitText(text: string): string {
		return text.replace(tokenPattern, (token) => this.splitToken(token));
	}
}

if (vocabularyData.schema_version !== 1)
	throw new Error("Unsupported vocab.json schema_version");
const vocabulary = new Vocabulary(vocabularyData.words);

/** Display-only spacing repair. Original exported text remains available. */
export function splitJoinedWords(text: string): string {
	return vocabulary.splitText(text);
}
