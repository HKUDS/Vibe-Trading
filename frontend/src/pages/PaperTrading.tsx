import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { FlaskConical, Plus, Trash2 } from "lucide-react";
import {
  paperApi,
  type PaperAccount,
  type PaperOrder,
  type PaperPosition,
  type PaperResult,
} from "@/lib/api";

const field =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm";
const button =
  "rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50";
const panel = "rounded-2xl border border-border bg-card p-5 space-y-4";

export function PaperTrading() {
  const { t } = useTranslation();
  const [accounts, setAccounts] = useState<PaperAccount[]>([]);
  const [selected, setSelected] = useState("");
  const [label, setLabel] = useState("");
  const [market, setMarket] = useState("us");
  const [start, setStart] = useState("today");
  const [cash, setCash] = useState("100000");
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [orders, setOrders] = useState<PaperOrder[]>([]);
  const [mode, setMode] = useState("orders");
  const [strategy, setStrategy] = useState("");
  const [date, setDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [result, setResult] = useState<PaperResult | null>(null);
  const [history, setHistory] = useState<PaperResult[]>([]);
  const account = accounts.find((a) => a.id === selected);
  const currency =
    account?.currency ?? { cn_a: "CNY", hk: "HKD", us: "USD" }[market];

  useEffect(() => {
    let active = true;
    paperApi
      .list()
      .then((items) => {
        if (active) setAccounts(items);
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setHistory([]);
    setResult(null);
    setNotice("");
    setOrders([]);
    setDate("");
    if (selected)
      paperApi
        .history(selected)
        .then((items) => {
          if (active) setHistory(items);
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [selected]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await paperApi.create({
        label,
        market,
        start,
        account_state: { cash: Number(cash), positions },
      });
      setAccounts((items) => [created, ...items]);
      setSelected(created.id);
      setLabel("");
      setPositions([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function advance(event: FormEvent) {
    event.preventDefault();
    if (!account) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const reply = await paperApi.advance(account.id, {
        expected_revision: account.revision,
        to_date: date,
        ...(mode === "strategy" ? { strategy_path: strategy } : { orders }),
      });
      setAccounts((items) =>
        items.map((a) => (a.id === reply.account.id ? reply.account : a)),
      );
      setResult(reply.result);
      setNotice(t(reply.committed ? "paper.saved" : "paper.notSaved"));
      if (reply.committed) setHistory((items) => [...items, reply.result]);
    } catch (e) {
      setError((e as Error).message);
      // A timed-out request may have committed. Reload before any explicit retry.
      try {
        setAccounts(await paperApi.list());
      } catch {
        /* The original error stays visible. */
      }
    } finally {
      setBusy(false);
    }
  }
  const shown = result ?? account?.last_result;
  const number = (value: number) =>
    value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-8">
      <header className="space-y-2">
        <div className="flex items-center gap-3">
          <FlaskConical className="text-primary" />
          <h1 className="text-2xl font-semibold">{t("paper.title")}</h1>
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {t("paper.description")}
        </p>
      </header>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm"
        >
          {error}
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-[minmax(260px,1fr)_2fr]">
        <aside className="space-y-4">
          <section className={panel}>
            <label className="block text-sm font-medium">
              {t("paper.accounts")}
              <select
                className={`${field} mt-2`}
                value={selected}
                disabled={busy}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="">{t("paper.newAccount")}</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.label} · {a.currency}
                  </option>
                ))}
              </select>
            </label>
            {account && (
              <>
                <p className="text-sm text-muted-foreground">
                  {t("paper.eligible", { date: account.start_on })}
                </p>
                <p className="text-2xl font-semibold">
                  {number(account.account_state.cash)}{" "}
                  <span className="text-sm">{currency}</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("paper.cash")} · {account.last_date ?? t("paper.pending")}
                </p>
                {account.account_state.positions.map((p) => (
                  <div
                    key={p.symbol}
                    className="flex justify-between gap-2 text-sm"
                  >
                    <span>{p.symbol}</span>
                    <span>
                      {number(p.qty)} × {number(p.avg_cost)}
                    </span>
                  </div>
                ))}
              </>
            )}
          </section>
        </aside>
        <main className="min-w-0 space-y-5">
          {!account ? (
            <form onSubmit={create} className={panel}>
              <h2 className="text-lg font-semibold">{t("paper.newAccount")}</h2>
              <label className="block text-sm">
                {t("paper.label")}
                <input
                  className={`${field} mt-1`}
                  required
                  maxLength={80}
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">
                  {t("paper.market")}
                  <select
                    className={`${field} mt-1`}
                    value={market}
                    onChange={(e) => setMarket(e.target.value)}
                  >
                    {(["us", "hk", "cn_a"] as const).map((m) => (
                      <option key={m} value={m}>
                        {t(`paper.${m}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-sm">
                  {t("paper.start")}
                  <select
                    className={`${field} mt-1`}
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  >
                    <option value="today">{t("paper.today")}</option>
                    <option value="next_session">
                      {t("paper.nextSession")}
                    </option>
                  </select>
                </label>
              </div>
              <label className="block text-sm">
                {t("paper.cash")} ({currency})
                <input
                  className={`${field} mt-1`}
                  type="number"
                  min="0"
                  step="any"
                  required
                  value={cash}
                  onChange={(e) => setCash(e.target.value)}
                />
              </label>
              <p className="text-sm font-medium">
                {t("paper.initialPositions")}
              </p>
              {positions.map((p, i) => (
                <div
                  className="grid grid-cols-[2fr_1fr_1fr_auto] gap-2"
                  key={i}
                >
                  <input
                    aria-label={t("paper.symbol")}
                    placeholder={t("paper.symbol")}
                    className={field}
                    required
                    value={p.symbol}
                    onChange={(e) =>
                      setPositions((ps) =>
                        ps.map((v, j) =>
                          j === i ? { ...v, symbol: e.target.value } : v,
                        ),
                      )
                    }
                  />
                  <input
                    aria-label={t("paper.quantity")}
                    className={field}
                    type="number"
                    min="0.00000001"
                    step="any"
                    required
                    value={p.qty}
                    onChange={(e) =>
                      setPositions((ps) =>
                        ps.map((v, j) =>
                          j === i ? { ...v, qty: Number(e.target.value) } : v,
                        ),
                      )
                    }
                  />
                  <input
                    aria-label={t("paper.cost")}
                    className={field}
                    type="number"
                    min="0.00000001"
                    step="any"
                    required
                    value={p.avg_cost}
                    onChange={(e) =>
                      setPositions((ps) =>
                        ps.map((v, j) =>
                          j === i
                            ? { ...v, avg_cost: Number(e.target.value) }
                            : v,
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    className={button}
                    aria-label={t("paper.remove")}
                    onClick={() =>
                      setPositions((ps) => ps.filter((_, j) => j !== i))
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
              <button
                type="button"
                className={`${button} flex items-center gap-2`}
                onClick={() =>
                  setPositions((ps) => [
                    ...ps,
                    { symbol: "", qty: 1, avg_cost: 1 },
                  ])
                }
              >
                <Plus size={16} />
                {t("paper.addPosition")}
              </button>
              <button
                disabled={busy}
                className={`${button} bg-primary text-primary-foreground`}
              >
                {t(busy ? "paper.working" : "paper.create")}
              </button>
            </form>
          ) : (
            <form onSubmit={advance} className={panel}>
              <h2 className="text-lg font-semibold">{t("paper.advance")}</h2>
              <p className="text-sm text-muted-foreground">
                {t("paper.executionNote")}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">
                  {t("paper.date")}
                  <input
                    type="date"
                    required
                    className={`${field} mt-1`}
                    min={account.start_on}
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  {t("paper.mode")}
                  <select
                    className={`${field} mt-1`}
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                  >
                    <option value="orders">{t("paper.orders")}</option>
                    <option value="strategy">{t("paper.strategy")}</option>
                  </select>
                </label>
              </div>
              {mode === "strategy" ? (
                <label className="block text-sm">
                  {t("paper.strategyPath")}
                  <input
                    className={`${field} mt-1`}
                    required
                    value={strategy}
                    onChange={(e) => setStrategy(e.target.value)}
                  />
                </label>
              ) : (
                <>
                  {orders.map((o, i) => (
                    <div
                      key={i}
                      className="grid grid-cols-[2fr_1fr_1fr_auto] gap-2"
                    >
                      <input
                        aria-label={t("paper.symbol")}
                        placeholder={t("paper.symbol")}
                        className={field}
                        required
                        value={o.symbol}
                        onChange={(e) =>
                          setOrders((os) =>
                            os.map((v, j) =>
                              j === i ? { ...v, symbol: e.target.value } : v,
                            ),
                          )
                        }
                      />
                      <select
                        aria-label={t("paper.side")}
                        className={field}
                        value={o.side}
                        onChange={(e) =>
                          setOrders((os) =>
                            os.map((v, j) =>
                              j === i
                                ? {
                                    ...v,
                                    side: e.target.value as "buy" | "sell",
                                  }
                                : v,
                            ),
                          )
                        }
                      >
                        <option value="buy">{t("paper.buy")}</option>
                        <option value="sell">{t("paper.sell")}</option>
                      </select>
                      <input
                        aria-label={t("paper.quantity")}
                        type="number"
                        min="0.00000001"
                        step="any"
                        required
                        className={field}
                        value={o.qty}
                        onChange={(e) =>
                          setOrders((os) =>
                            os.map((v, j) =>
                              j === i
                                ? { ...v, qty: Number(e.target.value) }
                                : v,
                            ),
                          )
                        }
                      />
                      <button
                        type="button"
                        className={button}
                        aria-label={t("paper.remove")}
                        onClick={() =>
                          setOrders((os) => os.filter((_, j) => j !== i))
                        }
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    className={button}
                    onClick={() =>
                      setOrders((os) => [
                        ...os,
                        { symbol: "", side: "buy", qty: 1 },
                      ])
                    }
                  >
                    {t("paper.addOrder")}
                  </button>
                  <p className="text-xs text-muted-foreground">
                    {t("paper.emptyOrders")}
                  </p>
                </>
              )}
              <button
                disabled={busy}
                className={`${button} bg-primary text-primary-foreground`}
              >
                {t(busy ? "paper.working" : "paper.advance")}
              </button>
            </form>
          )}
          {notice && (
            <p role="status" className="text-sm">
              {notice}
            </p>
          )}
          {shown && (
            <section className={panel}>
              <h2 className="font-semibold">{t("paper.result")}</h2>
              {shown.code && (
                <p role="alert">
                  {shown.code}: {shown.message}
                </p>
              )}
              {shown.data_provenance && (
                <p className="text-xs text-muted-foreground">
                  {shown.data_provenance.source} ·{" "}
                  {shown.data_provenance.bars_as_of}
                </p>
              )}
              {!!shown.fills?.length && (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr>
                        {(
                          [
                            "date",
                            "symbol",
                            "side",
                            "quantity",
                            "price",
                            "fee",
                          ] as const
                        ).map((key) => (
                          <th key={key} className="p-2">
                            {t(`paper.${key}`)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {shown.fills.map((f, i) => (
                        <tr key={i} className="border-t border-border">
                          <td className="p-2">{f.trade_date}</td>
                          <td>{f.symbol}</td>
                          <td>
                            {t(f.side === "buy" ? "paper.buy" : "paper.sell")}
                          </td>
                          <td>{number(f.qty)}</td>
                          <td>{number(f.price)}</td>
                          <td>{number(f.fee)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {shown.rejected_orders?.map((r, i) => (
                <p key={i} className="text-sm text-destructive">
                  {r.symbol}: {r.reason_code}
                </p>
              ))}
              {shown.warnings?.map((w, i) => (
                <p key={i} className="text-xs text-muted-foreground">
                  {w}
                </p>
              ))}
            </section>
          )}
          {!!history.length && (
            <section className={panel}>
              <h2 className="font-semibold">
                {t("paper.history")} ({currency})
              </h2>
              <div className="max-h-64 overflow-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left">{t("paper.date")}</th>
                      <th className="text-right">{t("paper.nav")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history
                      .flatMap((h) => h.nav_series ?? [])
                      .map((n) => (
                        <tr key={n.date} className="border-t border-border">
                          <td className="py-2">{n.date}</td>
                          <td className="text-right">{number(n.nav)}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
