import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, FilePlus2, Loader2, RefreshCw, Search } from "lucide-react";
import {
  api,
  type ResearchArtifactRevision,
  type ResearchArtifactSaveResult,
  type SaveResearchArtifactRequest,
} from "@/lib/api";

interface ArtifactForm {
  artifact_id?: string;
  subject: string;
  universe: string;
  content: string;
  data_as_of: string;
  verification_status: string;
  completeness: string;
  hypothesis_id: string;
  goal_id: string;
  session_id: string;
  run_id: string;
  newEvidence: string;
  existingEvidence?: ResearchArtifactRevision["evidence"];
}

function blankForm(): ArtifactForm {
  const today = new Date();
  return {
    subject: "",
    universe: "",
    content: "",
    data_as_of: [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"), String(today.getDate()).padStart(2, "0")].join("-"),
    verification_status: "unverified",
    completeness: "complete",
    hypothesis_id: "",
    goal_id: "",
    session_id: "",
    run_id: "",
    newEvidence: "",
  };
}

function revisionForm(revision: ResearchArtifactRevision): ArtifactForm {
  return {
    artifact_id: revision.artifact_id,
    subject: revision.subject,
    universe: revision.universe,
    content: revision.content,
    data_as_of: revision.data_as_of,
    verification_status: revision.verification_status,
    completeness: revision.completeness,
    hypothesis_id: revision.hypothesis_id || "",
    goal_id: revision.goal_id || "",
    session_id: revision.session_id || "",
    run_id: revision.run_id || "",
    newEvidence: "",
    existingEvidence: revision.evidence,
  };
}

function evidenceFromText(text: string): Array<Record<string, unknown>> {
  return text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((source_uri) => ({ source_uri }));
}

export function ResearchArtifacts() {
  const { t } = useTranslation();
  const [artifacts, setArtifacts] = useState<ResearchArtifactRevision[]>([]);
  const [detail, setDetail] = useState<{ artifact: ResearchArtifactRevision; revisions: ResearchArtifactRevision[] } | null>(null);
  const [form, setForm] = useState<ArtifactForm>(blankForm);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadArtifacts(search = "") {
    setLoading(true);
    setError(null);
    try {
      const result = await api.searchResearchArtifacts(search ? { query: search } : {});
      setArtifacts(result.artifacts);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("researchArtifacts.loadError"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadArtifacts();
  }, []);

  async function openArtifact(artifactId: string) {
    setError(null);
    try {
      setDetail(await api.getResearchArtifact(artifactId));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("researchArtifacts.loadError"));
    }
  }

  function update<Key extends keyof ArtifactForm>(key: Key, value: ArtifactForm[Key]) {
    setForm((current) => ({
      ...current, [key]: value,
      ...(current.artifact_id && ["content", "data_as_of", "newEvidence"].includes(key)
        ? { verification_status: "unverified" } : {}),
    }));
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const newEvidence = evidenceFromText(form.newEvidence);
      const body: SaveResearchArtifactRequest = {
        artifact_id: form.artifact_id,
        subject: form.subject,
        universe: form.universe,
        content: form.content,
        data_as_of: form.data_as_of,
        verification_status: form.verification_status,
        completeness: form.completeness,
        hypothesis_id: form.hypothesis_id || undefined,
        goal_id: form.goal_id || undefined,
        session_id: form.session_id || undefined,
        run_id: form.run_id || undefined,
      };
      if (form.existingEvidence || newEvidence.length) {
        body.evidence = [...(form.existingEvidence || []), ...newEvidence];
      }
      const result: ResearchArtifactSaveResult = await api.saveResearchArtifact(body);
      const id = result.revision.revision_id;
      setNotice(t(result.created ? "researchArtifacts.createdNotice" : "researchArtifacts.idempotentNotice", { id }));
      setForm(revisionForm(result.revision));
      await Promise.all([loadArtifacts(query.trim()), openArtifact(result.revision.artifact_id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("researchArtifacts.saveError"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <section className="flex flex-wrap items-end justify-between gap-4 border-b pb-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{t("researchArtifacts.title")}</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">{t("researchArtifacts.subtitle")}</p>
          </div>
          <div className="flex gap-2">
            <button type="button" className="rounded-md border px-3 py-2 text-sm" onClick={() => setForm(blankForm())}>
              <FilePlus2 className="me-2 inline h-4 w-4" />{t("researchArtifacts.newResearch")}
            </button>
            <button type="button" className="rounded-md border px-3 py-2 text-sm" disabled={loading} onClick={() => void loadArtifacts(query.trim())}>
              <RefreshCw className={`me-2 inline h-4 w-4 ${loading ? "animate-spin" : ""}`} />{t("reports.refresh")}
            </button>
          </div>
        </section>

        <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); void loadArtifacts(query.trim()); }}>
          <label className="relative flex-1">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input className="w-full rounded-md border bg-background py-2 ps-9 pe-3 text-sm" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("researchArtifacts.searchPlaceholder")} />
          </label>
          <button type="submit" className="rounded-md border px-4 py-2 text-sm">{t("alphaZoo.search")}</button>
        </form>

        {error && <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
        {notice && <div role="status" className="rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm">{notice}</div>}

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)]">
          <div className="space-y-4">
            {loading && <div className="flex justify-center p-8"><Loader2 className="h-5 w-5 animate-spin" /></div>}
            {!loading && artifacts.length === 0 && (
              <section className="rounded-lg border border-dashed p-8 text-center">
                <h2 className="font-medium">{t("researchArtifacts.emptyTitle")}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{t("researchArtifacts.emptyHint")}</p>
              </section>
            )}
            {artifacts.map((item) => (
              <button key={item.artifact_id} type="button" onClick={() => void openArtifact(item.artifact_id)} className="w-full rounded-lg border p-4 text-start transition hover:bg-muted/50">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="font-medium">{item.subject}</h2>
                  <span className="text-xs text-muted-foreground">r{item.revision_number}</span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {item.universe && <span>{item.universe}</span>}
                  <span>{t("researchArtifacts.dataAsOf")}: {item.data_as_of}</span>
                  <span>{t("researchArtifacts.verification")}: {item.verification_status}</span>
                </div>
                {item.evidence_missing && <div className="mt-2 flex items-center gap-1 text-xs text-amber-600"><AlertTriangle className="h-3.5 w-3.5" />{t("researchArtifacts.evidenceMissing")}</div>}
              </button>
            ))}

            {detail && (
              <section className="rounded-lg border p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="font-medium">{detail.artifact.subject}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">{detail.artifact.artifact_id}</p>
                  </div>
                  <button type="button" className="text-sm text-muted-foreground" onClick={() => setDetail(null)}>{t("researchArtifacts.close")}</button>
                </div>
                <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 font-sans text-sm">{detail.artifact.content}</pre>
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer">{t("researchArtifacts.evidence")}</summary>
                  <pre className="mt-2 overflow-auto whitespace-pre-wrap">{JSON.stringify(detail.artifact.evidence, null, 2)}</pre>
                </details>
                <button type="button" className="mt-3 rounded-md border px-3 py-1.5 text-sm" onClick={() => setForm(revisionForm(detail.artifact))}>{t("researchArtifacts.revise")}</button>
                <h3 className="mt-5 text-sm font-medium">{t("researchArtifacts.history")}</h3>
                <div className="mt-2 space-y-2">
                  {detail.revisions.map((revision) => (
                    <details key={revision.revision_id} className="rounded-md border p-3 text-sm">
                      <summary className="cursor-pointer">r{revision.revision_number} · {revision.data_as_of} · {revision.created_at}</summary>
                      <pre className="mt-3 whitespace-pre-wrap font-sans text-muted-foreground">{revision.content}</pre>
                      <p className="mt-2 text-xs text-muted-foreground">{t("researchArtifacts.verification")}: {revision.verification_status}</p>
                      <pre className="mt-2 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(revision.evidence, null, 2)}</pre>
                    </details>
                  ))}
                </div>
              </section>
            )}
          </div>

          <form className="space-y-3 rounded-lg border p-4" onSubmit={(event) => void save(event)}>
            <h2 className="font-medium">{t(form.artifact_id ? "researchArtifacts.formTitleRevision" : "researchArtifacts.formTitleNew")}</h2>
            <label className="block text-sm">{t("researchArtifacts.subject")}
              <input required className="mt-1 w-full rounded-md border bg-background px-3 py-2" disabled={Boolean(form.artifact_id)} value={form.subject} onChange={(event) => update("subject", event.target.value)} />
            </label>
            <label className="block text-sm">{t("researchArtifacts.universe")}
              <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" disabled={Boolean(form.artifact_id)} value={form.universe} onChange={(event) => update("universe", event.target.value)} />
            </label>
            <label className="block text-sm">{t("researchArtifacts.dataAsOf")}
              <input required className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.data_as_of} onChange={(event) => update("data_as_of", event.target.value)} />
            </label>
            <label className="block text-sm">{t("researchArtifacts.content")}
              <textarea required rows={7} className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.content} onChange={(event) => update("content", event.target.value)} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm">{t("researchArtifacts.verification")}
                <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.verification_status} onChange={(event) => update("verification_status", event.target.value)} />
              </label>
              <label className="block text-sm">{t("researchArtifacts.completeness")}
                <input className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.completeness} onChange={(event) => update("completeness", event.target.value)} />
              </label>
            </div>
            <label className="block text-sm">{t("researchArtifacts.additionalEvidence")}
              <textarea rows={3} className="mt-1 w-full rounded-md border bg-background px-3 py-2" value={form.newEvidence} onChange={(event) => update("newEvidence", event.target.value)} />
            </label>
            <details className="text-sm">
              <summary className="cursor-pointer">{t("researchArtifacts.optionalLinks")}</summary>
              <div className="mt-2 grid grid-cols-2 gap-2">
                {(["hypothesis_id", "goal_id", "session_id", "run_id"] as const).map((key) => (
                  <input key={key} aria-label={t(`researchArtifacts.${key}`)} placeholder={t(`researchArtifacts.${key}`)} className="rounded-md border bg-background px-3 py-2" value={form[key]} onChange={(event) => update(key, event.target.value)} />
                ))}
              </div>
            </details>
            <button type="submit" disabled={saving} className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50">
              {saving ? t("researchArtifacts.saving") : t("researchArtifacts.save")}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
