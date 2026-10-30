import { parseHoldings, percent } from "../shannon";

it("preserves explicit percent allocations and permits equal weights only when all omitted", () => {
  expect(parseHoldings("600000.SH 60%\n000001.SZ 40")).toEqual([{ code: "600000.SH", weight: .6 }, { code: "000001.SZ", weight: .4 }]);
  expect(parseHoldings("600000.sh\n000001.sz")).toEqual([{ code: "600000.SH" }, { code: "000001.SZ" }]);
});

it.each(["", "600000.SH 60%\n000001.SZ", "600000.SH 40%\n000001.SZ 40%", "600000.SH\n600000.SH", "00700.HK", "000300.SH", "399001.SZ", "600000.SH -10%", "600000.SH 0%", "600000.SH 100% more"])("rejects unsupported or ambiguous allocations: %s", value => {
  expect(parseHoldings(value)).toBeNull();
});

it("distinguishes missing percentages from zero", () => {
  expect(percent(null)).toBe("—"); expect(percent(0)).toBe("0.00%");
});
