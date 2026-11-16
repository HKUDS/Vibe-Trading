import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useTranslation } from "react-i18next";
import { Download, FlaskConical, Loader2 } from "lucide-react";
import { api, type LabCatalog, type LabJob, type LabResult, type LabAction } from "@/lib/api";

const field = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
const percent = (value: unknown) => typeof value === "number" ? `${(value * 100).toFixed(2)}%` : "—";
const number = (value: unknown) => typeof value === "number" ? value.toFixed(3) : "—";

function choices(text: string, emptyMessage: string): Array<string | number | boolean | null> {
  return text.split(",").map((item) => {
    const token = item.trim();
    if (!token) throw new Error(emptyMessage);
    try { return JSON.parse(token) as string | number | boolean | null; }
    catch { return token; }
  });
}

export function ResearchLab() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<LabCatalog>({ runs: [], cases: [] });
  const [action, setAction] = useState<LabAction>("cost_sensitivity");
  const [source, setSource] = useState("");
  const [fees, setFees] = useState("1, 2, 3");
  const [slippage, setSlippage] = useState("0, 5");
  const [trainBars, setTrainBars] = useState(60);
  const [testBars, setTestBars] = useState(20);
  const [holdoutBars, setHoldoutBars] = useState(20);
  const [folds, setFolds] = useState(3);
  const [objective, setObjective] = useState("sharpe");
  const [training, setTraining] = useState("rolling");
  const [params, setParams] = useState<Record<string, string>>({});
  const [alphaIds, setAlphaIds] = useState("");
  const [caseId, setCaseId] = useState("");
  const [job, setJob] = useState<LabJob | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const sourceRun = catalog.runs.find((run) => run.id === source);
  const busy = submitting || job?.status === "pending" || job?.status === "running";

  useEffect(() => {
    let active = true;
    api.getResearchLabCatalog().then((data) => {
      if (!active) return;
      setCatalog(data);
      setSource(data.runs.find((run) => run.has_prices)?.id ?? "");
      setCaseId(data.cases[0]?.id ?? "");
      const saved = new URLSearchParams(location.search).get("job");
      if (saved) api.getResearchLabJob(saved).then((value) => { if (active) restoreJob(value); }).catch((err: Error) => { if (active) setError(err.message); });
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; generation.current += 1; };
  }, []);

  function restoreJob(value: LabJob) {
    setJob(value); setAction(value.action);
    const saved = value.request;
    if (!saved) return;
    if (typeof saved.run_dir === "string") setSource(saved.run_dir);
    if (Array.isArray(saved.case_ids) && typeof saved.case_ids[0] === "string") setCaseId(saved.case_ids[0]);
    if (Array.isArray(saved.alpha_ids)) setAlphaIds(saved.alpha_ids.join(", "));
    for (const [key, setter] of [["train_bars", setTrainBars], ["test_bars", setTestBars], ["holdout_bars", setHoldoutBars], ["max_folds", setFolds]] as const) {
      if (typeof saved[key] === "number") setter(saved[key]);
    }
    if (saved.objective === "sharpe" || saved.objective === "total_return") setObjective(saved.objective);
    if (saved.training === "rolling" || saved.training === "expanding") setTraining(saved.training);
    if (Array.isArray(saved.scenarios)) {
      setFees([...new Set(saved.scenarios.map((row: { fee_multiplier: number }) => row.fee_multiplier))].join(", "));
      setSlippage([...new Set(saved.scenarios.map((row: { extra_slippage_bps: number }) => row.extra_slippage_bps))].join(", "));
    }
  }

  useEffect(() => {
    const values = Object.fromEntries(Object.entries(sourceRun?.parameters ?? {}).map(([name, value]) => [name, JSON.stringify(value)]));
    const saved = job?.request;
    if (saved?.run_dir === sourceRun?.id && Array.isArray(saved?.candidates)) {
      const candidates = saved.candidates as Array<{ parameters: Record<string, unknown> }>;
      for (const key of new Set(candidates.flatMap((candidate) => Object.keys(candidate.parameters)))) {
        values[key] = [...new Set(candidates.map((candidate) => JSON.stringify(candidate.parameters[key] ?? sourceRun?.parameters[key])))].join(", ");
      }
    }
    setParams(values);
  }, [sourceRun, job?.id]);

  useEffect(() => {
    if (!job || !["pending", "running"].includes(job.status)) return;
    let active = true;
    const timer = window.setInterval(() => {
      api.getResearchLabJob(job.id).then((next) => { if (active) { setJob(next); setError(null); } })
        .catch((err: Error) => { if (active) setError(err.message); });
    }, 1000);
    return () => { active = false; clearInterval(timer); };
  }, [job?.id, job?.status]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const current = ++generation.current;
    setSubmitting(true); setError(null); setJob(null);
    try {
      let request: Record<string, unknown>;
      if (action === "cost_sensitivity") {
        const multipliers = choices(fees, t("researchLab.invalidChoices")), bps = choices(slippage, t("researchLab.invalidChoices"));
        if (![...multipliers, ...bps].every((value) => typeof value === "number" && Number.isFinite(value))) throw new Error(t("researchLab.invalidValues"));
        request = { run_dir: source, scenarios: multipliers.flatMap((fee) => bps.map((bp) => ({
          name: `${fee}× / ${bp} bp`, fee_multiplier: fee, extra_slippage_bps: bp,
        }))) };
      } else if (action === "walk_forward") {
        let grid: Array<Record<string, unknown>> = [{}];
        for (const [name, text] of Object.entries(params)) {
          grid = grid.flatMap((base) => choices(text, t("researchLab.invalidChoices")).map((value) => ({ ...base, [name]: value })));
          if (grid.length > 12) throw new Error(t("researchLab.tooManyCandidates"));
        }
        request = { run_dir: source, candidates: grid.map((parameters, i) => ({ name: `candidate-${i + 1}`, parameters })),
          train_bars: trainBars, test_bars: testBars, holdout_bars: holdoutBars, max_folds: folds, objective, training };
      } else if (action === "factor_audit") {
        request = { alpha_ids: alphaIds.trim() ? alphaIds.split(/[,\s]+/).filter(Boolean) : null };
      } else request = { run_dir: source, case_ids: caseId ? [caseId] : null };
      const next = await api.startResearchLabJob(action, request);
      if (generation.current !== current) return;
      setJob(next);
      history.replaceState(null, "", `?job=${encodeURIComponent(next.id)}`);
    } catch (err) { if (generation.current === current) setError(err instanceof Error ? err.message : t("researchLab.failed")); }
    finally { if (generation.current === current) setSubmitting(false); }
  }

  function download() {
    if (!job?.result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(job.result, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `research-${job.id}.json`;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className="mx-auto max-w-7xl space-y-6 p-6 lg:p-8">
    <header className="border-b pb-6"><h1 className="flex items-center gap-3 text-2xl font-semibold"><FlaskConical className="h-6 w-6 text-primary" />{t("researchLab.title")}</h1><p className="mt-2 max-w-3xl text-sm text-muted-foreground">{t("researchLab.subtitle")}</p></header>
    <div role="tablist" aria-label={t("researchLab.title")} className="flex flex-wrap gap-2">{(["cost_sensitivity", "walk_forward", "factor_audit", "replay"] as const).map((name) =>
      <button key={name} role="tab" aria-selected={action === name} disabled={busy} onClick={() => { generation.current += 1; setAction(name); history.replaceState(null, "", location.pathname); if ((name === "replay" && !sourceRun?.has_trace) || (name !== "replay" && !sourceRun?.has_prices)) setSource(catalog.runs.find((run) => name === "replay" ? run.has_trace : run.has_prices)?.id ?? ""); setJob(null); setError(null); }} className={`rounded-full border px-4 py-2 text-sm ${action === name ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground"}`}>{t(`researchLab.${name}`)}</button>)}</div>
    <form onSubmit={(event) => void submit(event)} className="space-y-4 rounded-xl border bg-card p-5">
      <fieldset disabled={busy} className="space-y-4 disabled:opacity-70">
        {action !== "factor_audit" && <label className="block text-sm">{t("researchLab.sourceRun")}<select required className={`${field} mt-1`} value={source} onChange={(event) => setSource(event.target.value)}><option value="">{t("researchLab.chooseRun")}</option>{catalog.runs.filter((run) => action === "replay" ? run.has_trace : run.has_prices).map((run) => <option key={run.id} value={run.id}>{run.codes.length ? `${run.codes.join(", ")} · ${run.start_date} – ${run.end_date} · ` : ""}{run.id}</option>)}</select></label>}
        {action !== "factor_audit" && catalog.runs.length === 0 && <p className="text-sm text-muted-foreground">{t("researchLab.noRuns")} <Link className="text-primary underline" to="/">{t("layout.agent")}</Link></p>}
        {action === "cost_sensitivity" && <><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">{t("researchLab.feeLevels")}<input required className={`${field} mt-1`} value={fees} onChange={(event) => setFees(event.target.value)} /></label><label className="text-sm">{t("researchLab.slippageLevels")}<input required className={`${field} mt-1`} value={slippage} onChange={(event) => setSlippage(event.target.value)} /></label></div><p className="text-xs leading-relaxed text-muted-foreground">{t("researchLab.costHint")}</p></>}
        {action === "walk_forward" && <><div className="grid gap-4 sm:grid-cols-4">{([["trainBars", trainBars, setTrainBars, 5], ["testBars", testBars, setTestBars, 2], ["holdoutBars", holdoutBars, setHoldoutBars, 0], ["folds", folds, setFolds, 1]] as const).map(([label, value, setter, min]) => <label key={label} className="text-sm">{t(`researchLab.${label}`)}<input type="number" required min={min} className={`${field} mt-1`} value={value} onChange={(event) => setter(Number(event.target.value))} /></label>)}</div><div className="grid gap-4 sm:grid-cols-2"><label className="text-sm">{t("researchLab.objective")}<select className={`${field} mt-1`} value={objective} onChange={(event) => setObjective(event.target.value)}><option value="sharpe">{t("researchLab.sharpeObjective")}</option><option value="total_return">{t("researchLab.returnObjective")}</option></select></label><label className="text-sm">{t("researchLab.training")}<select className={`${field} mt-1`} value={training} onChange={(event) => setTraining(event.target.value)}><option value="rolling">{t("researchLab.rolling")}</option><option value="expanding">{t("researchLab.expanding")}</option></select></label></div><div className="grid gap-4 sm:grid-cols-2">{Object.entries(params).map(([name, text]) => <label key={name} className="text-sm">{name} · {t("researchLab.parameterChoices")}<input className={`${field} mt-1`} required value={text} onChange={(event) => setParams((current) => ({ ...current, [name]: event.target.value }))} /></label>)}</div><p className="text-xs leading-relaxed text-muted-foreground">{t("researchLab.oosHint")} {Object.keys(params).length === 0 && t("researchLab.noParameters")}</p></>}
        {action === "factor_audit" && <><label className="block text-sm">{t("researchLab.alphaIds")}<input className={`${field} mt-1`} value={alphaIds} onChange={(event) => setAlphaIds(event.target.value)} placeholder="gtja191_149, alpha101_001" /></label><p className="text-xs text-muted-foreground">{t("researchLab.auditHint")}</p></>}
        {action === "replay" && <><label className="block text-sm">{t("researchLab.task")}<select className={`${field} mt-1`} value={caseId} onChange={(event) => setCaseId(event.target.value)}>{catalog.cases.map((entry) => <option key={entry.id} value={entry.id}>{entry.id}</option>)}</select></label><p className="rounded-lg bg-muted/40 p-3 text-sm leading-relaxed">{catalog.cases.find((entry) => entry.id === caseId)?.prompt}</p><p className="text-xs text-muted-foreground">{t("researchLab.replayHint")}</p></>}
        <button type="submit" className="inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground" disabled={busy || (action !== "factor_audit" && !source)}>{busy && <Loader2 className="h-4 w-4 animate-spin" />}{t(busy ? "researchLab.running" : "researchLab.start")}</button>
      </fieldset>
    </form>
    {(error || job?.error) && <p role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm text-destructive">{error || job?.error}</p>}
    {busy && <p role="status" className="text-sm text-muted-foreground">{t("researchLab.running")} {job?.progress && `${job.progress.completed} / ${job.progress.total}`}</p>}
    {job?.result && <section className="space-y-4 rounded-xl border bg-card p-5"><div className="flex items-center justify-between"><h2 className="font-semibold">{t("researchLab.report")}</h2><button onClick={download} className="inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"><Download className="h-4 w-4" />{t("researchLab.download")}</button></div>{typeof job.request?.run_dir === "string" && <p className="text-xs text-muted-foreground">{t("researchLab.sourceRun")}: {job.request.run_dir}</p>}<LabReport result={job.result} /></section>}
  </div>;
}

function LabReport({ result }: { result: LabResult }) {
  const { t } = useTranslation();
  if (result.kind === "cost_sensitivity") return <><div className="overflow-x-auto"><table className="w-full text-start text-sm"><thead><tr>{(["scenario", "feeLevels", "slippageLevels", "return", "drawdown", "sharpe"] as const).map((key) => <th key={key} className="border-b p-2 text-start font-medium">{t(`researchLab.${key}`)}</th>)}</tr></thead><tbody>{result.rows.map((row) => <tr key={row.name}><td className="p-2">{row.name}</td><td className="p-2">{row.fee_multiplier}×</td><td className="p-2">{row.extra_slippage_bps}</td><td className="p-2">{percent(row.total_return)}</td><td className="p-2">{percent(row.max_drawdown)}</td><td className="p-2">{number(row.sharpe)}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground">{t("researchLab.breakEvenHint")} {result.break_even_brackets.length ? result.break_even_brackets.map((row) => `${row.fee_multiplier_interval.join("–")}× / ${row.extra_slippage_bps} bp`).join("; ") : t("researchLab.notBracketed")}</p></>;
  if (result.kind === "walk_forward") return <><p className="text-lg font-semibold">{t("researchLab.oosReturn")}: {percent(result.oos_total_return)}</p>{result.holdout && <p>{t("researchLab.holdoutReturn")}: {percent(result.holdout.total_return)}</p>}<div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr>{(["folds", "selected", "testPeriod", "return", "drawdown"] as const).map((key) => <th key={key} className="border-b p-2 text-start">{t(`researchLab.${key}`)}</th>)}</tr></thead><tbody>{result.folds.map((fold) => <tr key={fold.fold}><td className="p-2">{fold.fold}</td><td className="p-2">{JSON.stringify(fold.parameters)}</td><td className="p-2">{fold.test_start.slice(0, 10)} – {fold.test_end.slice(0, 10)}</td><td className="p-2">{percent(fold.test.metrics.total_return)}</td><td className="p-2">{percent(fold.test.metrics.max_drawdown)}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground">{t("researchLab.oosHint")}</p></>;
  if (result.kind === "factor_audit") return <><p>{t("researchLab.checked")}: {result.count} · {t("researchLab.findings")}: {result.finding_count}</p><div className="max-h-[36rem] overflow-auto"><table className="w-full text-sm"><thead><tr>{(["factor", "minimumBars", "policy", "status"] as const).map((key) => <th key={key} className="border-b p-2 text-start">{t(`researchLab.${key}`)}</th>)}</tr></thead><tbody>{result.rows.map((row) => <tr key={row.id}><td className="p-2"><Link className="text-primary underline" to={`/alpha-zoo/${row.id}`}>{row.id}</Link></td><td className="p-2">{row.minimum_bars}</td><td className="p-2">{t(`researchLab.policy_${row.policy}`)}</td><td className="p-2">{t(row.valid ? "researchLab.passed" : "researchLab.failed")}{row.findings?.length ? <p className="mt-1 max-w-md text-xs text-muted-foreground">{row.findings.join("; ")}</p> : null}</td></tr>)}</tbody></table></div><p className="text-xs text-muted-foreground">{t("researchLab.auditHint")}</p></>;
  return <><p className="font-semibold">{t(`researchLab.${result.evaluation_status}`)}</p><p>{t("researchLab.coverage")}: {percent(result.summary.evaluation_coverage)}</p>{result.reports.map((report) => <details key={report.case_id} className="rounded-lg border p-3"><summary className="cursor-pointer text-sm">{report.case_id}</summary><ul className="mt-3 space-y-2 text-xs">{report.verdicts.map((verdict, index) => <li key={index} className="border-t pt-2"><span className="font-medium">{verdict.status}</span> · {verdict.code}{verdict.detail && <p className="mt-1 text-muted-foreground">{verdict.detail}</p>}</li>)}</ul></details>)}</>;
}
