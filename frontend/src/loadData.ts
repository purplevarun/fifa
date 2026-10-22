import type { Dataset } from "./data";

export type DatasetFetcher = (
	input: RequestInfo | URL,
	init?: RequestInit,
) => Promise<Response>;

export function watchCareerDataset(
	fetcher: DatasetFetcher,
	handlers: {
		onData: (data: Dataset) => void;
		onMissing: () => void;
		onError: (error: unknown) => void;
		onSettled: () => void;
	},
	intervalMs: number | null = 3000,
) {
	const controller = new AbortController();
	const url = `${import.meta.env.BASE_URL}data/dashboard.json`;
	let contents: string | null | undefined;
	let etag: string | null = null;
	let timer: ReturnType<typeof setTimeout> | undefined;
	async function check() {
		try {
			const headers: Record<string, string> = {
				Accept: "application/json",
			};
			if (etag) headers["If-None-Match"] = etag;
			const response = await fetcher(url, {
				signal: controller.signal,
				cache: "no-store",
				headers,
			});
			if (controller.signal.aborted) return;
			if (response.status === 404) {
				if (contents !== null) handlers.onMissing();
				contents = null;
				etag = null;
				return;
			}
			if (
				response.status === 304 &&
				contents !== undefined &&
				contents !== null
			) {
				return;
			}
			if (!response.ok)
				throw new Error(
					`Career data request failed (${response.status}).`,
				);
			const text = await response.text();
			if (controller.signal.aborted) return;
			if (text !== contents) {
				handlers.onData(JSON.parse(text) as Dataset);
				contents = text;
			}
			etag = response.headers.get("ETag");
		} catch (error) {
			if (!controller.signal.aborted) {
				contents = undefined;
				etag = null;
				handlers.onError(error);
			}
		} finally {
			if (!controller.signal.aborted) {
				handlers.onSettled();
				if (intervalMs !== null) timer = setTimeout(check, intervalMs);
			}
		}
	}
	void check();
	return () => {
		controller.abort();
		if (timer !== undefined) clearTimeout(timer);
	};
}
