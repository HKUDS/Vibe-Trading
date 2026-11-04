import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ShannonPortfolio } from "../ShannonPortfolio";
import { shannon, styleLabels, type ShannonDiagnosis } from "@/lib/shannon";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ i18n: { language: "zh" } }) }));
const diagnosis: ShannonDiagnosis = { status: "completed", requested_date: "2026-10-28", weight_assumption: "custom",
  meta: { actual_factor_date: "2026-10-28", risk_as_of: "2026-10-27", included_holding_count: 2, requested_holding_count: 2 },
  data: { exposures: { portfolio: { SIZE: 1.5, VOLATILITY: -.6, BETA: -.2, VALUE: 0 } },
    holdings: [{ ts_code: "600000.SH", name: "甲公司", normalized_weight: .6, exposures: { BETA: 3.7, VALUE: -3.9, SIZE: 1.5, VOLATILITY: -.6 } },
      { ts_code: "000001.SZ", name: "乙公司", normalized_weight: .4, exposures: { BETA: 2.1, VALUE: -2.4, SIZE: -.002, VOLATILITY: null } }],
    risk_attribution: { total_risk: .23, top_stock_contributions: { "600000.SH": .25, "000001.SZ": -.02 } } } };

beforeEach(() => {
  vi.spyOn(shannon, "status").mockResolvedValue({ configured: true });
  vi.spyOn(shannon, "catalog").mockResolvedValue({ data: { universes: [{ id: "all", ready: true, current_as_of: "2026-10-28" }] } });
  vi.spyOn(shannon, "diagnosis").mockResolvedValue(diagnosis);
});

async function run() {
  render(<ShannonPortfolio />);
  await screen.findByText("数据更新至 2026-10-28");
  fireEvent.change(screen.getByLabelText("你的A股持仓"), { target: { value: "600000.SH 60%\n000001.SZ 40%" } });
  fireEvent.click(screen.getByRole("button", { name: "诊断持仓" }));
  await screen.findByRole("heading", { name: "风险归因：谁在影响组合波动" });
}

it("shows ten portfolio factors and keeps stock styles collapsed with no extra request", async () => {
  await run();
  const style = screen.getByRole("region", { name: "组合风格暴露" });
  expect(within(style).getByLabelText("市值: +1.50")).toBeInTheDocument();
  expect(within(style).getByLabelText("市场贝塔: -0.20")).toBeInTheDocument();
  expect(within(style).getByLabelText("价值: 0.00")).toBeInTheDocument();
  expect(style.querySelector("details")).not.toHaveAttribute("open");
  expect(screen.queryByText("本期主要助力与拖累")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("查看个股风格"));
  await waitFor(() => expect(style.querySelector("details")).toHaveAttribute("open"));
  const table = screen.getByRole("table", { name: "个股风格暴露热力图" });
  expect(within(table).getAllByRole("columnheader").map(el => el.textContent)).toEqual(["股票", ...Object.values(styleLabels).map(names => names[0])]);
  expect(shannon.diagnosis).toHaveBeenCalledTimes(1);
  expect(shannon.diagnosis).toHaveBeenCalledWith({ date: "2026-10-28", holdings: [{ code: "600000.SH", weight: .6 }, { code: "000001.SZ", weight: .4 }] }, expect.any(AbortSignal));
});

it("saturates heatmap colors without clipping values and preserves missing values", async () => {
  await run();
  fireEvent.click(screen.getByText("查看个股风格"));
  const table = screen.getByRole("table", { name: "个股风格暴露热力图" });
  const cells = within(table).getAllByRole("cell");
  const plusHigh = cells.find(cell => cell.title === "3.7")!;
  const plusLow = cells.find(cell => cell.title === "2.1")!;
  expect(plusHigh).toHaveTextContent("+3.7");
  expect(plusHigh.style.backgroundColor).toBe(plusLow.style.backgroundColor);
  expect(cells.find(cell => cell.title === "-3.9")!.style.backgroundColor).toBe(cells.find(cell => cell.title === "-2.4")!.style.backgroundColor);
  expect(cells.find(cell => cell.title === "-0.002")).toHaveTextContent("0.0");
  expect(cells.filter(cell => cell.title === "数据缺失").every(cell => cell.textContent === "—")).toBe(true);
  expect(table.textContent).not.toContain("-0.0");
  expect(screen.getByText(/不是该股风险贡献的分解/)).toBeInTheDocument();
});

it("retains signed risk shares separately from allocation", async () => {
  await run();
  expect(screen.getByRole("row", { name: /甲公司 60.00%/ })).toHaveTextContent("+108.70%");
  expect(screen.getByRole("row", { name: /乙公司 40.00%/ })).toHaveTextContent("-8.70%");
  expect(screen.getByText("分散波动")).toBeInTheDocument();
  expect(screen.getByRole("columnheader", { name: "组合波动贡献占比" })).toBeInTheDocument();
  expect(screen.getByText(/不是亏损概率，也不等于减仓后的风险降幅/)).toBeInTheDocument();
  expect(screen.getByText(/优先复核相关仓位/)).toBeInTheDocument();
});

it("does not fill missing or incomplete portfolio exposures with zero", async () => {
  vi.mocked(shannon.diagnosis).mockResolvedValue({ ...diagnosis, meta: { ...diagnosis.meta, factor_coverage: { SIZE: { ratio: .5 } } } });
  await run();
  const style = screen.getByRole("region", { name: "组合风格暴露" });
  expect(within(style).getByLabelText("市值: —")).toBeInTheDocument();
  expect(within(style).getByLabelText("质量: —")).toBeInTheDocument();
  expect(within(style).getByLabelText("价值: 0.00")).toBeInTheDocument();
});

it("keeps coverage exclusions and original entered weights visible", async () => {
  vi.mocked(shannon.diagnosis).mockResolvedValue({ ...diagnosis, meta: { ...diagnosis.meta, included_holding_count: 1 }, data: { ...diagnosis.data, holdings: [diagnosis.data.holdings![0]], missing: [{ ts_code: "000001.SZ" }] } });
  await run();
  expect(screen.getByText(/已覆盖输入权重.*60.00%/)).toBeInTheDocument();
  expect(screen.getByRole("row", { name: /000001.SZ 40.00%/ })).toBeInTheDocument();
});

it("does not invent shares when total risk is unavailable", async () => {
  vi.mocked(shannon.diagnosis).mockResolvedValue({ ...diagnosis, data: { ...diagnosis.data, risk_attribution: { top_stock_contributions: { "600000.SH": .25 } } } });
  await run();
  expect(screen.getByRole("row", { name: /甲公司 60.00%/ }).querySelectorAll("td")[3]).toHaveTextContent("—");
});

it("defaults to the published date and clears old results on date changes", async () => {
  await run();
  const date = screen.getByLabelText("分析截至日期（可选）");
  expect(date).toHaveValue("2026-10-28");
  fireEvent.change(date, { target: { value: "2026-10-23" } });
  expect(screen.queryByRole("region", { name: "组合风格暴露" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "使用最新数据" }));
  expect(date).toHaveValue("2026-10-28");
});

it("discards a late diagnosis after holdings change", async () => {
  let resolve: (value: ShannonDiagnosis) => void = () => {};
  vi.mocked(shannon.diagnosis).mockReturnValue(new Promise(r => { resolve = r; }));
  render(<ShannonPortfolio />);
  await screen.findByText("数据更新至 2026-10-28");
  fireEvent.change(screen.getByLabelText("你的A股持仓"), { target: { value: "600000.SH" } });
  fireEvent.click(screen.getByRole("button", { name: "诊断持仓" }));
  fireEvent.change(screen.getByLabelText("你的A股持仓"), { target: { value: "000001.SZ" } });
  await act(async () => resolve(diagnosis));
  expect(screen.queryByRole("region", { name: "组合风格暴露" })).not.toBeInTheDocument();
});

it("keeps the source optional and skips catalog without a token", async () => {
  vi.mocked(shannon.status).mockResolvedValue({ configured: false });
  render(<ShannonPortfolio />);
  await screen.findByText(/配置聚源 Token 后可使用/);
  expect(shannon.catalog).not.toHaveBeenCalled();
  expect(shannon.diagnosis).not.toHaveBeenCalled();
});
