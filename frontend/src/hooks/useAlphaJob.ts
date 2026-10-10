import { useCallback, useEffect, useRef } from "react";
import i18n from "@/i18n";
import { api, ApiError, type AlphaBenchRequest, type AlphaCompareRequest, type AlphaBenchResult, type AlphaCompareResult, type AlphaProgress } from "@/lib/api";
import { useAnalysisState } from "./useAnalysisState";

export type AlphaJobStatus = "idle" | "submitting" | "streaming" | "done" | "error" | "disconnected";

/** Recover a job by reading its snapshot; reconnecting never submits another job. */
export function useAlphaJob<T extends AlphaBenchResult | AlphaCompareResult>(kind: "bench" | "compare", context = "default") {
  const [state, setState] = useAnalysisState(`alpha-job:${kind}:${context}`, {
    status: "idle" as AlphaJobStatus, jobId: null as string | null,
    request: null as AlphaBenchRequest | AlphaCompareRequest | null,
    pendingRequest: null as AlphaBenchRequest | AlphaCompareRequest | null,
    progress: null as AlphaProgress | null, result: null as T | null, formError: null as string | null,
  });
  const source = useRef<EventSource | null>(null);
  const generation = useRef(0);
  const submitting = useRef(false);
  const connect = useCallback(async (jobId: string) => {
    const gen = ++generation.current;
    source.current?.close();
    setState((s) => ({ ...s, status: "streaming", formError: null }));
    try {
      const snapshot = kind === "bench" ? await api.getAlphaBenchJob(jobId) : await api.getAlphaCompareJob(jobId);
      if (gen !== generation.current) return;
      setState((s) => ({ ...s, progress: snapshot.progress, result: snapshot.result as T | null ?? s.result }));
      if (snapshot.status === "done" || snapshot.status === "error") {
        setState((s) => ({ ...s, status: snapshot.status === "done" ? "done" : "error", formError: snapshot.error }));
        return;
      }
      const url = kind === "bench" ? await api.alphaBenchStreamUrl(jobId) : await api.alphaCompareStreamUrl(jobId);
      if (gen !== generation.current) return;
      const stream = new EventSource(url);
      source.current = stream;
      let terminalError = false;
      let ended = false;
      stream.addEventListener("progress", (event) => {
        if (gen !== generation.current) return;
        try { const progress = JSON.parse((event as MessageEvent).data); setState((s) => ({ ...s, progress })); } catch { /* malformed event */ }
      });
      stream.addEventListener("result", (event) => {
        if (gen !== generation.current) return;
        try { const result = JSON.parse((event as MessageEvent).data) as T; setState((s) => ({ ...s, result })); } catch { /* malformed event */ }
      });
      stream.addEventListener("done", () => {
        ended = true;
        if (gen === generation.current && !terminalError) setState((s) => ({ ...s, status: "done" }));
        stream.close();
      });
      stream.addEventListener("error", (event) => {
        if (gen !== generation.current || ended) return;
        let message = i18n.t("analysis.streamInterrupted");
        try { const data = JSON.parse((event as MessageEvent).data); if (typeof data.message === "string") { message = data.message; terminalError = true; } } catch { /* transport failure */ }
        setState((s) => ({ ...s, status: terminalError ? "error" : "disconnected", formError: message }));
        stream.close();
      });
    } catch (error) {
      if (gen === generation.current) {
        const expired = error instanceof ApiError && error.status === 404;
        setState((s) => ({ ...s, status: expired ? "error" : "disconnected", jobId: expired ? null : s.jobId, formError: expired ? i18n.t("analysis.jobExpired") : error instanceof Error ? error.message : i18n.t("analysis.failed") }));
      }
    }
  }, [kind, setState]);
  useEffect(() => {
    // Repeat an unfinished submission with its original identity; the server
    // returns the existing job if it accepted the first POST.
    if (!state.jobId && state.pendingRequest) {
      const body = state.pendingRequest;
      submitting.current = true;
      const reply = kind === "bench" ? api.createAlphaBench(body as AlphaBenchRequest) : api.createAlphaCompare(body as AlphaCompareRequest);
      void reply.then((response) => setState((s) => s.pendingRequest?.request_id === body.request_id ? ({ ...s, jobId: response.job_id, pendingRequest: null, status: "streaming" }) : s))
         .catch((error) => {
          const refused = error instanceof ApiError && error.status >= 400 && error.status < 500 && error.status !== 429;
          setState((s) => s.pendingRequest?.request_id === body.request_id ? ({ ...s, status: refused ? "error" : "disconnected", pendingRequest: refused ? null : s.pendingRequest, formError: error instanceof Error ? error.message : i18n.t("analysis.failed") }) : s);
        }).finally(() => { submitting.current = false; });
    }
    if (state.jobId && !(state.status === "done" && state.result)) void connect(state.jobId);
    return () => { generation.current += 1; source.current?.close(); };
  }, [connect, state.jobId, state.pendingRequest]);
  const submit = async (body: AlphaBenchRequest | AlphaCompareRequest) => {
    if (submitting.current || ["submitting", "streaming", "disconnected"].includes(state.status)) return;
    submitting.current = true;
    setState((s) => ({ ...s, status: "submitting", jobId: null, request: body, pendingRequest: { ...body, request_id: crypto.randomUUID().replace(/-/g, "") }, formError: null, result: null, progress: null }));
  };
  return { ...state, submit, reconnect: () => state.jobId ? void connect(state.jobId) : setState((s) => ({ ...s, pendingRequest: s.pendingRequest ? { ...s.pendingRequest } : null })), setFormError: (formError: string | null) => setState((s) => ({ ...s, formError })), busy: ["submitting", "streaming", "disconnected"].includes(state.status) };
}
