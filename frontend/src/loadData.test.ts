import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { watchCareerDataset } from "./loadData";

function createHandlers() {
	return {
		onData: vi.fn(),
		onMissing: vi.fn(),
		onError: vi.fn(),
		onSettled: vi.fn(),
	};
}

describe("dashboard JSON loading", () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllEnvs();
	});

	it.each(["/", "./", "/fifa-career-mode/"])(
		"loads dashboard.json relative to the %s base without API requests",
		async (base) => {
			vi.stubEnv("BASE_URL", base);
			const data = { schema_version: 3 };
			const fetcher = vi.fn(async () => Response.json(data));
			const handlers = createHandlers();
			const stop = watchCareerDataset(fetcher, handlers);
			await vi.advanceTimersByTimeAsync(0);

			expect(handlers.onData).toHaveBeenCalledWith(data);
			expect(fetcher).toHaveBeenCalledWith(`${base}data/dashboard.json`, {
				signal: expect.any(AbortSignal),
				cache: "no-store",
				headers: { Accept: "application/json" },
			});
			stop();
		},
	);

	it("reports failed responses without exposing their contents", async () => {
		const fetcher = vi.fn(
			async () => new Response("private details", { status: 503 }),
		);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(0);

		expect(handlers.onError).toHaveBeenCalledWith(
			new Error("Career data request failed (503)."),
		);
		expect(handlers.onData).not.toHaveBeenCalled();
		expect(handlers.onSettled).toHaveBeenCalledTimes(1);
		stop();
	});

	it.each(["not JSON", "<!doctype html><title>Not JSON</title>"])(
		"rejects malformed data and recovers on the next check: %s",
		async (body) => {
			const fetcher = vi
				.fn()
				.mockResolvedValueOnce(new Response(body))
				.mockImplementation(async () =>
					Response.json({ schema_version: 3 }),
				);
			const handlers = createHandlers();
			const stop = watchCareerDataset(fetcher, handlers);
			await vi.advanceTimersByTimeAsync(0);
			expect(handlers.onError).toHaveBeenCalledWith(
				expect.any(SyntaxError),
			);
			expect(handlers.onData).not.toHaveBeenCalled();

			await vi.advanceTimersByTimeAsync(3000);
			expect(handlers.onData).toHaveBeenCalledWith({ schema_version: 3 });
			stop();
		},
	);

	it("uses ETags to avoid unchanged downloads and loads a replaced export", async () => {
		let generation = "original";
		const fetcher = vi.fn(
			async (_url: RequestInfo | URL, init?: RequestInit) => {
				const etag = `"${generation}"`;
				if (new Headers(init?.headers).get("If-None-Match") === etag)
					return new Response(null, { status: 304 });
				return Response.json(
					{ schema_version: 3, generation },
					{ headers: { ETag: etag } },
				);
			},
		);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(0);
		expect(handlers.onData).toHaveBeenLastCalledWith({
			schema_version: 3,
			generation: "original",
		});
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(1);
		expect(fetcher.mock.calls[1][1]?.headers).toEqual({
			Accept: "application/json",
			"If-None-Match": '"original"',
		});

		generation = "fresh";
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenLastCalledWith({
			schema_version: 3,
			generation: "fresh",
		});
		expect(handlers.onError).not.toHaveBeenCalled();
		stop();
		await vi.advanceTimersByTimeAsync(6000);
		expect(fetcher).toHaveBeenCalledTimes(3);
	});

	it("compares contents when the server does not provide ETags", async () => {
		let generation = "original";
		const fetcher = vi.fn(async () =>
			Response.json({ schema_version: 3, generation }),
		);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(1);

		generation = "fresh";
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenLastCalledWith({
			schema_version: 3,
			generation,
		});
		expect(handlers.onData).toHaveBeenCalledTimes(2);
		stop();
	});

	it("waits for a missing export and reloads it even when recreated unchanged", async () => {
		let available = false;
		const fetcher = vi.fn(
			async (_url: RequestInfo | URL, _init?: RequestInit) =>
				available
					? Response.json(
							{ schema_version: 3 },
							{ headers: { ETag: '"same"' } },
						)
					: new Response(null, { status: 404 }),
		);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onMissing).toHaveBeenCalledTimes(1);
		expect(handlers.onData).not.toHaveBeenCalled();

		available = true;
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledWith({ schema_version: 3 });
		available = false;
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onMissing).toHaveBeenCalledTimes(2);
		available = true;
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(2);
		expect(fetcher.mock.lastCall?.[1]?.headers).toEqual({
			Accept: "application/json",
		});
		expect(handlers.onError).not.toHaveBeenCalled();
		stop();
	});

	it("retries errors without requiring another export change", async () => {
		const fetcher = vi
			.fn()
			.mockResolvedValueOnce(
				Response.json(
					{ schema_version: 3 },
					{ headers: { ETag: '"same"' } },
				),
			)
			.mockRejectedValueOnce(new TypeError("Network unavailable"))
			.mockResolvedValueOnce(
				Response.json(
					{ schema_version: 3 },
					{ headers: { ETag: '"same"' } },
				),
			);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(1);
		expect(handlers.onError).toHaveBeenCalledTimes(1);

		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(2);
		expect(fetcher.mock.lastCall?.[1]?.headers).toEqual({
			Accept: "application/json",
		});
		stop();
	});

	it("does not cache an export rejected by model validation", async () => {
		const fetcher = vi.fn(async () =>
			Response.json(
				{ schema_version: 3 },
				{ headers: { ETag: '"new"' } },
			),
		);
		const handlers = createHandlers();
		const failure = new Error("Unsupported schema");
		handlers.onData.mockImplementationOnce(() => {
			throw failure;
		});
		const stop = watchCareerDataset(fetcher, handlers);
		await vi.advanceTimersByTimeAsync(0);
		expect(handlers.onError).toHaveBeenCalledWith(failure);
		await vi.advanceTimersByTimeAsync(3000);
		expect(handlers.onData).toHaveBeenCalledTimes(2);
		expect(fetcher).toHaveBeenLastCalledWith(
			expect.any(String),
			expect.objectContaining({
				headers: { Accept: "application/json" },
			}),
		);
		stop();
	});

	it.each([200, 404, 503])(
		"loads once without polling in production (HTTP %s)",
		async (status) => {
			const fetcher = vi.fn(async () =>
				Response.json({ schema_version: 3 }, { status }),
			);
			const handlers = createHandlers();
			const stop = watchCareerDataset(fetcher, handlers, null);
			await vi.advanceTimersByTimeAsync(9000);
			expect(fetcher).toHaveBeenCalledTimes(1);
			expect(handlers.onSettled).toHaveBeenCalledTimes(1);
			if (status === 200)
				expect(handlers.onData).toHaveBeenCalledTimes(1);
			if (status === 404)
				expect(handlers.onMissing).toHaveBeenCalledTimes(1);
			if (status === 503)
				expect(handlers.onError).toHaveBeenCalledTimes(1);
			stop();
		},
	);

	it("cancels an in-flight check and future polling on cleanup", async () => {
		let resolve: ((response: Response) => void) | undefined;
		const fetcher = vi.fn(
			(_url: RequestInfo | URL, _init?: RequestInit) =>
				new Promise<Response>((done) => {
					resolve = done;
				}),
		);
		const handlers = createHandlers();
		const stop = watchCareerDataset(fetcher, handlers);
		stop();
		resolve?.(Response.json({ schema_version: 3 }));
		await vi.advanceTimersByTimeAsync(6000);
		expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
		expect(fetcher).toHaveBeenCalledTimes(1);
		expect(handlers.onData).not.toHaveBeenCalled();
		expect(handlers.onError).not.toHaveBeenCalled();
		expect(handlers.onSettled).not.toHaveBeenCalled();
	});
});
