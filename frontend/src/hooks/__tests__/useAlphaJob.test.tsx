import { act, renderHook, waitFor } from "@testing-library/react";
import { api, ApiError, type AlphaBenchResult } from "@/lib/api";
import { clearAnalysisState } from "../useAnalysisState";
import { useAlphaJob } from "../useAlphaJob";

vi.mock("@/lib/api", async (original) => ({ ...(await original<object>()), api: {
  createAlphaBench: vi.fn(), getAlphaBenchJob: vi.fn(), alphaBenchStreamUrl: vi.fn(),
} }));
class Stream extends EventTarget {
  static instances: Stream[] = [];
  readyState = 2;
  close = vi.fn();
  constructor(_url: string) { super(); Stream.instances.push(this); }
}
const resultData: AlphaBenchResult = { alive: 1, dead: 0, reversed: 0, top5_by_ir: [], dead_examples: [], by_theme: {} };
const body = { zoo: "alpha101", universe: "sp500", period: "2024-2025", alpha_id: "alpha101_001" };
const key = "alpha-job:bench:test";
beforeEach(() => {
  clearAnalysisState(key); vi.clearAllMocks(); Stream.instances = [];
  vi.stubGlobal("EventSource", Stream);
  vi.mocked(api.getAlphaBenchJob).mockResolvedValue({ job_id: "job", status: "running", progress: { n_done: 0, n_total: 1 }, result: null, error: null });
  vi.mocked(api.alphaBenchStreamUrl).mockResolvedValue("/stream");
  vi.mocked(api.createAlphaBench).mockResolvedValue({ status: "ok", job_id: "job" });
});
afterEach(() => vi.unstubAllGlobals());
const hook = () => useAlphaJob<AlphaBenchResult>("bench", "test");

it("recovers a completed job from its snapshot without submitting again", async () => {
  const first = renderHook(hook);
  await act(async () => { await first.result.current.submit(body); });
  await waitFor(() => expect(Stream.instances).toHaveLength(1));
  first.unmount();
  vi.mocked(api.getAlphaBenchJob).mockResolvedValue({ job_id: "job", status: "done", progress: { n_done: 1, n_total: 1 }, result: resultData, error: null });
  const recovered = renderHook(hook);
  await waitFor(() => expect(recovered.result.current.status).toBe("done"));
  expect(recovered.result.current.result).toEqual(resultData);
  expect(api.createAlphaBench).toHaveBeenCalledTimes(1);
  expect(Stream.instances).toHaveLength(1);
});
it("marks a closed transport as disconnected and reconnects using the same job", async () => {
  const { result } = renderHook(hook);
  await act(async () => { await result.current.submit(body); });
  await waitFor(() => expect(Stream.instances).toHaveLength(1));
  act(() => Stream.instances[0].dispatchEvent(new Event("error")));
  expect(result.current.status).toBe("disconnected");
  act(() => result.current.reconnect());
  await waitFor(() => expect(Stream.instances).toHaveLength(2));
  expect(api.createAlphaBench).toHaveBeenCalledTimes(1);
  act(() => Stream.instances[1].dispatchEvent(new Event("done")));
  act(() => Stream.instances[1].dispatchEvent(new Event("error")));
  expect(result.current.status).toBe("done");
});
it("replays an unfinished POST with the same identity after leaving the page", async () => {
  let resolve!: (r: {status: string; job_id: string}) => void;
  vi.mocked(api.createAlphaBench).mockReturnValue(new Promise((r) => { resolve = r; }));
  const first = renderHook(hook);
  await act(async () => { await first.result.current.submit(body); });
  const requestId = vi.mocked(api.createAlphaBench).mock.calls[0][0].request_id;
  first.unmount();
  const recovered = renderHook(hook);
  expect(api.createAlphaBench).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.createAlphaBench).mock.calls[1][0].request_id).toBe(requestId);
  await act(async () => resolve({ status: "ok", job_id: "job" }));
  await waitFor(() => expect(recovered.result.current.status).toBe("streaming"));
  expect(Stream.instances).toHaveLength(1);
});
it("allows a new evaluation after a task expired", async () => {
  const first = renderHook(hook);
  await act(async () => { await first.result.current.submit(body); });
  await waitFor(() => expect(Stream.instances).toHaveLength(1)); first.unmount();
  vi.mocked(api.getAlphaBenchJob).mockRejectedValue(new ApiError("expired", 404));
  const recovered = renderHook(hook);
  await waitFor(() => expect(recovered.result.current.status).toBe("error"));
  expect(recovered.result.current.busy).toBe(false);
  expect(recovered.result.current.jobId).toBeNull();
});
it("allows corrected parameters after the server rejects a submission", async () => {
  vi.mocked(api.createAlphaBench).mockRejectedValueOnce(new ApiError("bad period", 400));
  const { result } = renderHook(hook);
  await act(async () => { await result.current.submit(body); });
  await waitFor(() => expect(result.current.status).toBe("error"));
  expect(result.current.busy).toBe(false);
  await act(async () => { await result.current.submit({ ...body, period: "2023-2025" }); });
  await waitFor(() => expect(Stream.instances).toHaveLength(1));
  expect(api.createAlphaBench).toHaveBeenCalledTimes(2);
});
it("refuses two simultaneous submissions before React renders the busy state", async () => {
  const { result } = renderHook(hook);
  await act(async () => { await Promise.all([result.current.submit(body), result.current.submit(body)]); });
  await waitFor(() => expect(Stream.instances).toHaveLength(1));
  expect(api.createAlphaBench).toHaveBeenCalledTimes(1);
});
