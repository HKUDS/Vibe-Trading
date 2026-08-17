import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  Bot,
  CalendarClock,
  ChevronRight,
  CircleDashed,
  FileText,
  Gauge,
  Layers3,
  Lightbulb,
  Loader2,
  Network,
  Package,
  PieChart,
  RefreshCw,
  Search,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useSearchParams } from "react-router";
import {
  api,
  type ResearchAnalysisJob,
  type ResearchIndustry,
  type ResearchReport,
  type HotIndustry,
} from "@/lib/api";

const INSUFFICIENT = "当前数据不足，无法形成可靠判断。";

const HUMANOID_CONTEXT: Record<string, Record<string, string>> = {
  harmonic: {
    position: "关节旋转传动的核心部件，将电机的高速低扭矩转换为低速高扭矩，直接影响精度、回差、寿命和整机动态表现。",
    overseas: "海外厂商在高端精密传动市场积累深，优势集中在标准化产品、长期可靠性、客户认证和全球交付体系。",
    domestic: "国内处于进口替代与扩产并行阶段，中端应用渗透加快；高端环节仍需在寿命一致性、批量良率和整机验证上持续爬坡。",
    technology: "柔轮、刚轮、波发生器的齿形设计，材料与热处理，轴承匹配、回差控制，以及长期疲劳和精度保持能力。",
    capacity: "精密加工、热处理、装配和检测链条较长，真正壁垒在良率、批量一致性、产能爬坡和稳定交付，而不只是设备数量。",
  },
  planetary: {
    position: "面向高负载、高刚性线性运动的执行部件，负责把旋转运动转换为精密直线运动，适合腿部及其他高负载关节。",
    overseas: "海外供应商在高精度滚动部件、寿命数据库、工艺装备和工业客户认证方面积累深，长期服务机床、自动化和机器人市场。",
    domestic: "国内从样件开发走向整机验证和规模供货，产业链响应速度与成本有优势；高精度、长寿命产品仍处于验证和产能建设期。",
    technology: "滚道与滚柱几何、导程精度、预紧控制、疲劳寿命、热变形和低噪声设计，决定重复定位精度和长期可靠性。",
    capacity: "磨削、滚轧、热处理、精密测量和装配工序复杂，产能壁垒体现为设备稳定、良率、检测能力和批量一致性。",
  },
  "frameless-torque": {
    position: "直接集成到机器人关节内部的动力单元，减少中间传动环节，核心价值是高扭矩密度、低齿槽转矩和紧凑化。",
    overseas: "海外在高性能电机、电磁设计、驱动控制和可靠性认证上较成熟，产品与控制器、减速器和整机平台协同程度高。",
    domestic: "国内电机、磁材、绕组和驱动供应链较完整，定制响应快；短板主要在高扭矩密度、热管理、长期可靠性和整机平台验证。",
    technology: "电磁方案、磁路与绕组、低齿槽转矩、位置反馈、热管理和驱动匹配，决定动态响应、效率与关节寿命。",
    capacity: "磁材、冲片、绕组、灌封、动平衡和测试环节需要协同，小批定制容易，难点在标准化平台、良率和大批量一致性。",
  },
  "six-axis-force": {
    position: "机器人与环境发生接触时的力/力矩反馈部件，用于装配、抓取、碰撞保护和精细操作，是闭环控制的重要感知入口。",
    overseas: "海外高端市场以成熟传感器、标定体系和软件生态形成壁垒，工业客户验证周期长，对可靠性和漂移控制要求高。",
    domestic: "国内已具备结构、应变、算法和标定能力，正在从实验室及工业应用向机器人末端渗透；长期稳定性和规模交付仍需验证。",
    technology: "六轴解耦、应变结构、温漂与零漂补偿、信号噪声、动态响应和标定算法，决定力反馈准确性与可用性。",
    capacity: "精密结构加工、应变元件贴装、标定台和全检体系缺一不可；产能壁垒体现为标定效率、批量一致性和可靠性数据积累。",
  },
  "dexterous-hand": {
    position: "人形机器人的末端操作单元，承担抓取、旋拧、分拣等精细任务，价值由自由度、微型执行器、触觉和控制能力共同决定。",
    overseas: "海外更强调自由度、触觉融合和具身智能协同，依托长期研发与场景平台积累，处于技术路线和生态探索前沿。",
    domestic: "国内优势在场景迭代快、工程化和成本控制能力强，当前仍以样机、示范场景和早期量产验证为主，产品路线尚未完全收敛。",
    technology: "微型执行器、谐波/齿轮传动、触觉与位置感知、轻量化、柔顺控制和多指协同，是从能动到好用的关键。",
    capacity: "微型零部件装配、可靠性测试、柔性供应链和规模化校准难度高，产能壁垒来自复杂装配良率、测试时间和稳定交付能力。",
  },
  "ball-screw": {
    position: "成熟的精密直线传动部件，可用于腿部、臂部和其他线性执行机构，关注高速、高负载、低噪声与长寿命的平衡。",
    overseas: "海外在机床、自动化和工业机器人领域形成成熟标准、渠道和应用数据库，高端产品在一致性、寿命和服务体系上占优。",
    domestic: "国内基础制造和机床应用带来较完整供应链，国产替代基础较好；人形机器人所需的高动态、低噪声和轻量化产品仍在导入期。",
    technology: "滚道精度、滚珠循环、预紧、导程误差、摩擦与噪声控制，以及高速往复下的疲劳寿命和热稳定性。",
    capacity: "精密磨削、滚珠筛选、装配预紧和全寿命测试决定交付质量，规模化产能的核心是良率、检测节拍和多规格切换能力。",
  },
};

const SCORE_DIMENSIONS = ["不可替代性", "估值", "业务", "客户", "管理层"];

type Analysis = Record<string, any>;

function text(value: unknown, fallback = INSUFFICIENT): string {
  if (typeof value === "string" && value.trim()) return value;
  if (Array.isArray(value) && value.length) return value.join("、");
  return fallback;
}

function sourceLabel(source: string | string[]): string {
  if (Array.isArray(source)) return source.join(" + ");
  if (source.includes("report-search")) return "a-stock-data + report-search";
  return source || "a-stock-data";
}

export function HumanoidRobot() {
  const [params, setParams] = useSearchParams();
  const [industries, setIndustries] = useState<ResearchIndustry[]>([]);
  const [industry, setIndustry] = useState<ResearchIndustry | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [job, setJob] = useState<ResearchAnalysisJob | null>(null);
  const [activeId, setActiveId] = useState("overview");
  const [industrySearch, setIndustrySearch] = useState("");
  const [industrySearchOpen, setIndustrySearchOpen] = useState(false);
  const [semanticIndustries, setSemanticIndustries] = useState<ResearchIndustry[]>([]);
  const [semanticSearchLoading, setSemanticSearchLoading] = useState(false);
  const industryId = params.get("industry") || "humanoid-robot";

  useEffect(() => {
    const controller = new AbortController();
    api.listResearchIndustries("", controller.signal)
      .then((response) => setIndustries(response.items ?? []))
      .catch(() => setIndustries([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setIndustry(null);
    setAnalysis(null);
    setJob(null);
    setActiveId("overview");
    api.getResearchIndustry(industryId, controller.signal)
      .then((response) => {
        setIndustry(response.industry);
        setAnalysis(response.analysis);
        if (response.analysis_status !== "ready") {
          return api.startResearchAnalysis(industryId, false, controller.signal).then(setJob);
        }
        return undefined;
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setIndustry(null);
          setJob({ status: "failed", error: "行业数据暂时不可用" });
        }
      });
    return () => controller.abort();
  }, [industryId]);

  useEffect(() => {
    if (industry?.name) setIndustrySearch(industry.name);
  }, [industry]);

  useEffect(() => {
    if (!job?.job_id || ["ready", "failed"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      api.getResearchAnalysisJob(job.job_id!).then((next) => {
        setJob(next);
        if (next.status === "ready" && next.analysis) setAnalysis(next.analysis);
      }).catch(() => undefined);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [job?.job_id, job?.status]);

  const localIndustryMatches = useMemo(() => {
    const query = industrySearch.trim().toLowerCase();
    if (!query) return industries.slice(0, 12);
    return industries.filter((item) => item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query)).slice(0, 12);
  }, [industries, industrySearch]);

  useEffect(() => {
    const query = industrySearch.trim();
    if (!query || localIndustryMatches.length > 0) {
      setSemanticIndustries([]);
      setSemanticSearchLoading(false);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSemanticSearchLoading(true);
      api.listResearchIndustries(query, controller.signal, 50)
        .then((response) => setSemanticIndustries(response.items ?? []))
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) setSemanticIndustries([]);
        })
        .finally(() => setSemanticSearchLoading(false));
    }, 280);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [industrySearch, localIndustryMatches.length]);

  const sections = useMemo(() => {
    const base = industry?.sections ?? [];
    return base.length ? base : [{ id: "overview", label: "总览" }, { id: "reports", label: "研报库" }];
  }, [industry]);
  const activeSection = sections.find((section) => section.id === activeId) ?? sections[0];
  const pending = job && !["ready", "failed"].includes(job.status);
  const filteredIndustries = localIndustryMatches.length ? localIndustryMatches : semanticIndustries;

  const selectIndustry = (item: ResearchIndustry) => {
    setIndustrySearch(item.name);
    setIndustrySearchOpen(false);
    setParams({ industry: item.id });
  };

  return (
    <div className="min-h-full p-6 lg:p-8">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-primary">
              <Bot className="h-3.5 w-3.5" aria-hidden="true" />
              研报
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">{industry?.name || "行业研报中心"}</h1>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              {industry?.description || "按行业查看产业链、研报和基于财报证据的行业研判。"}
            </p>
          </div>
          <div className="relative w-full max-w-xs text-sm">
            <label className="mb-1 block text-xs text-muted-foreground">搜索行业</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <input
                value={industrySearch}
                placeholder="输入行业名称或代码"
                onChange={(event) => { setIndustrySearch(event.target.value); setIndustrySearchOpen(true); }}
                onFocus={() => setIndustrySearchOpen(true)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && filteredIndustries[0]) selectIndustry(filteredIndustries[0]);
                  if (event.key === "Escape") setIndustrySearchOpen(false);
                }}
                className="w-full rounded-lg border border-border/70 bg-card py-2 pl-9 pr-3 text-foreground outline-none focus:border-primary"
              />
            </div>
            {industrySearchOpen && <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-border/70 bg-card p-1 shadow-lg">
              {semanticSearchLoading ? <p className="flex items-center gap-2 px-3 py-3 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />正在进行语义行业搜索</p> : filteredIndustries.length ? filteredIndustries.map((item) => <button key={item.id} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => selectIndustry(item)} className={`w-full rounded-md px-3 py-2 text-left hover:bg-primary/10 ${item.id === industryId ? "bg-primary/10 text-primary" : "text-foreground"}`}><span className="block text-sm">{item.name}</span><span className="mt-0.5 block text-xs text-muted-foreground">{item.description || item.id}</span></button>) : <p className="px-3 py-3 text-xs text-muted-foreground">没有匹配的行业。可配置 IWENCAI_API_KEY 启用问财语义搜索。</p>}
            </div>}
          </div>
        </header>

        {pending && (
          <div className="flex items-center gap-2 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
            正在生成行业财报研判：{job?.current_step || "准备中"}（{job?.progress ?? 0}%）
          </div>
        )}
        {job?.status === "failed" && (
          <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/5 px-4 py-3 text-sm text-muted-foreground">
            <AlertCircle className="h-4 w-4 text-warning" aria-hidden="true" />
            {job.error || job.error_message || "分析任务暂时失败，基础行业信息仍可查看。"}
          </div>
        )}

        <nav aria-label="行业研报板块" role="tablist" className="flex gap-1 overflow-x-auto rounded-xl border border-border/60 bg-card/40 p-1">
          {sections.map((section) => {
            const active = section.id === activeSection?.id;
            return (
              <button key={section.id} type="button" role="tab" aria-selected={active} onClick={() => setActiveId(section.id)}
                className={`shrink-0 rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-muted/70 hover:text-foreground"}`}>
                {section.label}
              </button>
            );
          })}
        </nav>

        <main role="tabpanel" className="rounded-2xl border border-border/60 bg-card/40 p-5 shadow-sm lg:p-7">
          <div className="flex items-start justify-between gap-4 border-b border-border/60 pb-5">
            <div>
              <div className="flex items-center gap-2 text-xs font-medium text-primary"><ChevronRight className="h-3.5 w-3.5" />当前板块</div>
              <h2 className="mt-2 text-xl font-semibold">{activeSection?.label || "总览"}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{activeSection?.description || "基于结构化数据和研报证据的行业分析。"}</p>
            </div>
            <span className="rounded-full bg-muted/60 px-2.5 py-1 text-xs text-muted-foreground">{pending ? "分析中" : "已加载"}</span>
          </div>
          {activeId === "overview" ? <ResearchOverview industry={industry} analysis={analysis} onSelect={setActiveId} /> : null}
          {activeId === "reports" ? <ResearchReports industryId={industryId} /> : null}
          {activeId !== "overview" && activeId !== "reports" ? <ResearchSection sectionId={activeId} analysis={analysis} industryId={industryId} /> : null}
        </main>
      </div>
    </div>
  );
}

function ResearchOverview({ industry, analysis, onSelect }: { industry: ResearchIndustry | null; analysis: Analysis | null; onSelect: (id: string) => void }) {
  const sections = (industry?.sections ?? []).filter((section) => !["overview", "reports"].includes(section.id));
  const overview = analysis?.overview ?? {};
  const upstream = text(overview.upstream_materials?.summary, industry?.segments?.length ? industry.segments.join("、") : INSUFFICIENT);
  return (
    <div className="mt-6 space-y-5">
      <HotIndustriesPanel />
      <section className="rounded-xl border border-border/60 bg-background/30 px-5 py-4 text-center lg:px-8">
        <p className="text-xs text-muted-foreground">行业定位</p>
        <p className="mt-1 text-base font-semibold">{text(overview.positioning?.summary, industry?.description)}</p>
        <span className="mt-2 inline-flex rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">{analysis ? "已生成研判" : "基础数据"}</span>
      </section>
      <div className="flex flex-col items-center"><ArrowDown className="h-5 w-5 text-muted-foreground/60" /><p className="mt-2 text-xs font-medium text-muted-foreground">核心环节（点击进入分板块）</p></div>
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map((section) => {
          const item = analysis?.sections?.find((entry: any) => entry.section_id === section.id);
          return <button key={section.id} type="button" onClick={() => onSelect(section.id)} className="rounded-xl border border-border/60 bg-card/40 p-4 text-left transition-colors hover:border-primary/40 hover:bg-primary/5">
            <div className="flex items-center justify-between gap-3"><div className="flex min-w-0 items-center gap-2"><CircleDashed className="h-4 w-4 shrink-0 text-primary" /><span className="truncate text-sm font-medium">{section.label}</span></div><ChevronRight className="h-4 w-4 text-muted-foreground" /></div>
            <div className="mt-6 flex items-center justify-between text-xs"><span className="text-muted-foreground">板块结论</span><span className="max-w-[65%] truncate text-muted-foreground">{text(item?.conclusion?.summary)}</span></div>
          </button>;
        })}
      </section>
      <div className="flex flex-col items-center"><ArrowDown className="h-5 w-5 text-muted-foreground/60" /></div>
      <ResearchCard title="需求终端与上下游" icon={Network} content={`${text(overview.demand_endpoint?.summary)}；上游：${upstream}`} />
      <div className="grid gap-5 lg:grid-cols-2">
        <ResearchCard title="板块评分总览" icon={Gauge} content={text(overview.score_summary?.summary)} />
        <ResearchCard title="核心公司比较" icon={Package} content={text(overview.core_companies?.summary)} />
        <ResearchCard title="整机成本结构" icon={PieChart} content={text(overview.cost_structure?.summary)} />
        <ResearchCard title="量产时间线" icon={CalendarClock} content={text(overview.production_timeline?.summary)} />
        <ResearchCard title="板块结论" icon={Lightbulb} content={text(overview.conclusion?.summary)} className="lg:col-span-2" />
      </div>
    </div>
  );
}

function HotIndustriesPanel() {
  const [items, setItems] = useState<HotIndustry[]>([]);
  const [updatedAt, setUpdatedAt] = useState("");
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let disposed = false;
    const refresh = () => api.getHotResearchIndustries(10)
      .then((response) => {
        if (disposed) return;
        setItems(response.items ?? []);
        setUpdatedAt(response.updated_at ?? "");
        setStatus(response.status ?? "unavailable");
      })
      .catch(() => {
        if (!disposed) setStatus("unavailable");
      });
    refresh();
    const timer = window.setInterval(refresh, 5 * 60 * 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, []);

  const money = (value: number | null) => value == null ? INSUFFICIENT : `${(value / 100000000).toFixed(2)}亿`;
  return <section className="rounded-xl border border-border/60 bg-background/30 p-4 lg:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-primary" /><h3 className="text-sm font-medium">今日市场热度 TOP 10</h3></div><p className="mt-1 text-xs text-muted-foreground">按主力净流入、行业涨跌幅和上涨家数占比综合排序，页面每 5 分钟刷新。</p></div>
      <span className="text-xs text-muted-foreground">{updatedAt ? `更新于 ${updatedAt.replace("T", " ").slice(0, 19)}` : "正在获取"}</span>
    </div>
    {status === "loading" ? <div className="mt-4 flex min-h-24 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在获取当日板块热度</div> : items.length === 0 ? <div className="mt-4 flex min-h-24 items-center justify-center rounded-lg border border-dashed border-border/70 text-sm text-muted-foreground">{INSUFFICIENT}</div> : <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">{items.map((item) => <div key={item.board_code} className="rounded-lg border border-border/60 bg-card/40 p-3"><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold text-primary">#{item.rank}</span><span className="text-xs text-muted-foreground">热度 {item.heat_score.toFixed(2)}</span></div><p className="mt-2 truncate text-sm font-medium" title={item.name}>{item.name || INSUFFICIENT}</p><div className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted-foreground"><span>涨跌 {item.change_pct == null ? INSUFFICIENT : `${item.change_pct.toFixed(2)}%`}</span><span>主力 {money(item.main_net)}</span><span>上涨 {item.up_count ?? INSUFFICIENT}</span><span>领涨 {item.leader || INSUFFICIENT}</span></div></div>)}</div>}
    {status === "unavailable" && <p className="mt-3 text-xs text-warning">行业热度数据暂时不可用，无法形成可靠判断。</p>}
  </section>;
}

function ResearchReports({ industryId }: { industryId: string }) {
  const [reports, setReports] = useState<ResearchReport[]>([]);
  const [sources, setSources] = useState<{ a_stock_data?: string; report_search?: string }>({});
  const [loading, setLoading] = useState(true);
  const [refreshToken, setRefreshToken] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    api.getResearchIndustryReports(industryId, 90, 200, undefined, controller.signal)
      .then((response) => { setReports(response.items ?? []); setSources(response.sources ?? {}); })
      .catch(() => { setReports([]); setSources({}); })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [industryId, refreshToken]);
  return <section className="mt-6 rounded-xl border border-border/60 bg-card/40 p-4 lg:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><FileText className="h-4 w-4 text-primary" /><div><h3 className="text-sm font-medium">研报库</h3><p className="mt-1 text-xs text-muted-foreground">结构化研报 + 问财增强搜索，最近 90 天</p></div></div><button type="button" onClick={() => setRefreshToken((value) => value + 1)} disabled={loading} className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 px-3 py-2 text-xs text-muted-foreground hover:bg-muted/60 disabled:opacity-60"><RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />刷新</button></div>
    <div className="mt-4 flex flex-wrap gap-2 text-xs"><SourceBadge name="a-stock-data" status={sources.a_stock_data} /><SourceBadge name="report-search" status={sources.report_search} /></div>
    {sources.report_search === "unavailable" && <p className="mt-3 text-xs text-warning">report-search 不可用；配置 IWENCAI_API_KEY 后可获取更丰富的摘要、评级、目标价和原文链接。</p>}
    {loading ? <div className="mt-5 flex min-h-32 items-center justify-center text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在加载研报</div> : reports.length === 0 ? <div className="mt-5 flex min-h-32 items-center justify-center rounded-lg border border-dashed border-border/70 text-sm text-muted-foreground">{INSUFFICIENT}</div> : <div className="mt-5 overflow-x-auto rounded-lg border border-border/60"><table className="w-full min-w-[980px] text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr><th className="px-4 py-3">日期</th><th className="px-4 py-3">机构</th><th className="px-4 py-3">标题</th><th className="px-4 py-3">评级/目标价</th><th className="px-4 py-3">来源</th></tr></thead><tbody className="divide-y divide-border/60">{reports.map((report) => <tr key={report.report_id} className="hover:bg-muted/20"><td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{report.publish_time ? report.publish_time.slice(0, 10) : INSUFFICIENT}</td><td className="whitespace-nowrap px-4 py-3">{report.institution || INSUFFICIENT}</td><td className="min-w-[360px] px-4 py-3 font-medium">{report.source_url ? <a href={report.source_url} target="_blank" rel="noreferrer" className="hover:text-primary hover:underline">{report.title}</a> : report.title}</td><td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{[report.rating, report.target_price == null ? null : `${report.target_price}`].filter(Boolean).join(" / ") || INSUFFICIENT}</td><td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{sourceLabel(report.sources?.length ? report.sources : report.source)}</td></tr>)}</tbody></table></div>}
  </section>;
}

function SourceBadge({ name, status }: { name: string; status?: string }) {
  return <span className={`rounded-full px-2.5 py-1 ${status === "ok" ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>{name}: {status === "ok" ? "ok" : "unavailable"}</span>;
}

function ResearchSection({ sectionId, analysis, industryId }: { sectionId: string; analysis: Analysis | null; industryId: string }) {
  const section = analysis?.sections?.find((item: any) => item.section_id === sectionId);
  const context = industryId === "humanoid-robot" ? HUMANOID_CONTEXT[sectionId] : undefined;
  const field = (key: string, title: string, icon: LucideIcon) => {
    const fallback = context?.[key] || INSUFFICIENT;
    const value = section?.[key];
    return <ResearchCard title={title} icon={icon} content={value?.status === "insufficient_data" ? fallback : text(value?.summary, fallback)} />;
  };
  const dimensions = section?.score?.dimensions ?? [];
  const companies = section?.company_comparison ?? [];
  return <div className="mt-6 space-y-5">
    <div className="grid gap-5 lg:grid-cols-2">{field("position", "环节定位", Network)}{field("overseas_competition", "海外竞争格局", Layers3)}{field("domestic_competition", "国内竞争格局", Layers3)}</div>
    <section className="rounded-xl border border-border/60 bg-card/40 p-4"><div className="flex items-center gap-2"><Package className="h-4 w-4 text-primary" /><h3 className="text-sm font-medium">壁垒类型</h3></div><div className="mt-4 grid gap-4 sm:grid-cols-2">{field("technology_barrier", "技术壁垒", Gauge)}{field("capacity_barrier", "产能壁垒", Package)}</div></section>
    <ResearchCard title="财报研判" icon={PieChart} content={text(section?.financial_judgment?.summary)} />
    <section className="rounded-xl border border-border/60 bg-card/40 p-4"><div className="flex items-center gap-2"><Gauge className="h-4 w-4 text-primary" /><h3 className="text-sm font-medium">板块评分体系</h3></div><div className="mt-4 grid gap-3 md:grid-cols-5">{SCORE_DIMENSIONS.map((dimension, index) => { const item = dimensions[index]; const score = Number(item?.score ?? item?.value ?? 0); return <div key={dimension} className="rounded-lg border border-border/60 bg-background/40 p-3"><div className="flex items-center justify-between gap-2 text-xs"><span className="font-medium">{dimension}</span><span className="text-muted-foreground">{score > 0 ? `${score}/5` : "数据不足"}</span></div><p className="mt-2 min-h-12 text-xs leading-5 text-muted-foreground">{text(item?.reason)}</p><div className="mt-3 flex gap-1">{[1, 2, 3, 4, 5].map((level) => <span key={level} className={`h-2 flex-1 rounded-full border border-border/70 ${score >= level ? "bg-primary" : "bg-muted/30"}`} />)}</div></div>; })}</div></section>
    <section className="rounded-xl border border-border/60 bg-card/40 p-4"><div className="flex items-center gap-2"><Package className="h-4 w-4 text-primary" /><h3 className="text-sm font-medium">核心公司比较</h3></div><div className="mt-4 overflow-x-auto rounded-lg border border-border/60"><table className="w-full min-w-[720px] text-left text-sm"><thead className="bg-muted/40 text-xs text-muted-foreground"><tr><th className="px-4 py-3">公司</th><th className="px-4 py-3">代表性</th><th className="px-4 py-3">财报研判</th><th className="px-4 py-3">证据</th></tr></thead><tbody className="divide-y divide-border/60">{(companies.length ? companies : [{ company: INSUFFICIENT, summary: INSUFFICIENT }]).map((company: any, index: number) => <tr key={`${company.company || company.name}-${index}`}><td className="px-4 py-4 text-muted-foreground">{text(company.company || company.name)}</td><td className="px-4 py-4 text-muted-foreground">{text(company.role || company.relevance)}</td><td className="px-4 py-4 text-muted-foreground">{text(company.summary || company.financial_judgment)}</td><td className="px-4 py-4 text-muted-foreground">{text(company.citations?.join(", "))}</td></tr>)}</tbody></table></div></section>
    <ResearchCard title="板块结论" icon={Lightbulb} content={text(section?.conclusion?.summary)} />
  </div>;
}

function ResearchCard({ title, icon: Icon, content, className }: { title: string; icon: LucideIcon; content: string; className?: string }) {
  return <section className={`rounded-xl border border-border/60 bg-card/40 p-4 ${className ?? ""}`}><div className="flex items-center gap-2"><Icon className="h-4 w-4 text-primary" /><h3 className="text-sm font-medium">{title}</h3></div><p className="mt-4 text-sm leading-7 text-muted-foreground">{content}</p></section>;
}

export function Research() {
  return <HumanoidRobot />;
}
