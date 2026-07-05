# agent/src/trading/hybrid_bot/dashboard.py
import logging
import threading
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
import ccxt
from agent.src.trading.hybrid_bot.config import get_basket
from agent.src.trading.hybrid_bot.basket_manager import update_active_basket
from agent.src.trading.hybrid_bot.runner import (
    get_positions,
    get_wallet,
    get_history,
    get_settings,
    update_settings,
    scan_markets,
    close_position,
    log_file,
)

app = FastAPI(title="Vibe-Trading Hybrid Bot Dashboard")

logger = logging.getLogger("hybrid_bot_dashboard")

# Initialize CCXT exchange client for live ticker pricing
exchange = ccxt.binance({
    'timeout': 15000,
    'enableRateLimit': True
})

@app.on_event("startup")
def startup_event():
    from agent.src.trading.hybrid_bot.runner import run_daemon
    thread = threading.Thread(target=run_daemon, daemon=True)
    thread.start()
    logger.info("Background daemon thread started for market scanning and position tracking.")

def get_last_logs(limit: int = 50) -> list[str]:
    """Tails the last 16 KB of the log file — constant cost as the log grows."""
    if not log_file.exists():
        return ["No logs available yet."]
    try:
        with open(log_file, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16384))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        return [line.strip() for line in lines[-limit:]]
    except Exception as e:
        return [f"Failed to read logs: {e}"]

def build_equity_curve(initial_balance: float, history: list) -> list:
    """Cumulative realized balance after each completed trade."""
    balance = initial_balance
    points = [{"time": "start", "balance": round(balance, 2)}]
    for trade in history:
        balance += trade.get("net_pnl_usd", 0.0)
        points.append({"time": trade.get("exit_time", ""), "balance": round(balance, 2)})
    return points

@app.get("/api/status")
def api_status():
    positions = get_positions()
    basket = get_basket()
    settings = get_settings()

    # Fetch prices for the basket AND any open position no longer in the basket,
    # so de-basketed positions keep live pricing.
    symbols = list(dict.fromkeys(basket + list(positions.keys())))
    prices = {}
    tickers_data = {}
    try:
        tickers = exchange.fetch_tickers(symbols)
        for symbol in symbols:
            ticker = tickers.get(symbol)
            if ticker and ticker.get("last") is not None:
                prices[symbol] = float(ticker["last"])
                if symbol in basket:
                    tickers_data[symbol] = {
                        "price": float(ticker["last"]),
                        "change": float(ticker["percentage"]) if ticker.get("percentage") is not None else 0.0
                    }
    except Exception as e:
        logger.error(f"Failed to fetch tickers in dashboard API: {e}")

    # Real-time unrealized P&L for open positions
    for symbol, pos in list(positions.items()):
        current_price = prices.get(symbol)
        if current_price is not None:
            entry_price = pos["entry_price"]
            side = pos["side"]
            pos_size = pos.get("position_size", 1000.0)
            leverage = pos.get("leverage", 2.0)

            if side == "LONG":
                perf = (current_price - entry_price) / entry_price
            else:
                perf = (entry_price - current_price) / entry_price

            # Mirror execute_position_exit: leveraged notional minus entry+exit fees (0.05% each)
            position_value = pos_size * leverage
            fees = position_value * 0.001
            pos["current_price"] = current_price
            pos["pnl_pct"] = round(perf * 100, 2)
            pos["pnl_usd"] = round(perf * position_value - fees, 2)
        else:
            pos["current_price"] = pos["entry_price"]
            pos["pnl_pct"] = 0.0
            pos["pnl_usd"] = 0.0

    wallet = get_wallet()
    history = get_history()

    return {
        "status": "active",
        "paused": bool(settings.get("paused", False)),
        "settings": {k: v for k, v in settings.items() if k != "paused"},
        "basket": tickers_data,
        "positions": positions,
        "logs": get_last_logs(),
        "wallet": wallet,
        "history": history,
        "equity_curve": build_equity_curve(wallet.get("initial_balance", 10000.0), history)
    }

@app.post("/api/scan")
def api_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(scan_markets)
    return {"status": "ok", "message": "Market scan triggered in the background."}

@app.post("/api/basket/refresh")
def api_basket_refresh(background_tasks: BackgroundTasks):
    background_tasks.add_task(update_active_basket)
    return {"status": "ok", "message": "Basket refresh triggered in the background."}

@app.post("/api/bot/toggle")
def api_bot_toggle():
    paused = not get_settings().get("paused", False)
    update_settings({"paused": paused})
    return {"status": "ok", "paused": paused}

@app.post("/api/close")
def api_close_position(body: dict):
    symbol = body.get("symbol")
    if not symbol:
        raise HTTPException(status_code=422, detail="Missing 'symbol'")
    try:
        pos = close_position(exchange, symbol)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Close failed: {e}")
    if pos is None:
        raise HTTPException(status_code=404, detail=f"No open position for {symbol}")
    return {"status": "ok", "message": f"Closed {pos['side']} {symbol}"}

@app.get("/api/report")
def api_report():
    from agent.src.trading.hybrid_bot.report import build_report
    return build_report()

@app.get("/api/settings")
def api_get_settings():
    return get_settings()

@app.post("/api/settings")
def api_update_settings(updates: dict):
    try:
        return update_settings(updates)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.get("/", response_class=HTMLResponse)
def index_page():
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vibe-Trading Hybrid Bot Control Panel</title>
    <style>
        :root {
            --bg: #090D16;
            --card: rgba(17, 25, 40, 0.6);
            --border: rgba(255, 255, 255, 0.08);
            --text: #E2E8F0;
            --muted: #64748B;
            --green: #10B981;
            --green-soft: rgba(16, 185, 129, 0.12);
            --red: #F43F5E;
            --red-soft: rgba(244, 63, 94, 0.12);
            --cyan: #22D3EE;
            --amber: #F59E0B;
            --amber-soft: rgba(245, 158, 11, 0.12);
            --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background: var(--bg);
            color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 24px;
            overflow-x: hidden;
        }
        .wrap { max-width: 1240px; margin: 0 auto; display: flex; flex-direction: column; gap: 24px; }
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 16px;
            backdrop-filter: blur(16px) saturate(180%);
        }
        header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 16px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
        h1 {
            font-size: 26px; font-weight: 800; letter-spacing: -0.5px;
            background: linear-gradient(90deg, #34D399, #2DD4BF, #22D3EE);
            -webkit-background-clip: text; background-clip: text; color: transparent;
            display: inline-block;
        }
        .sub { color: var(--muted); font-size: 13px; margin-top: 4px; }
        h2 { font-size: 17px; font-weight: 700; }
        .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .chip {
            font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px;
            border: 1px solid; display: inline-flex; align-items: center; gap: 6px;
        }
        .chip.active { color: var(--green); background: var(--green-soft); border-color: rgba(16,185,129,0.25); }
        .chip.paused { color: var(--amber); background: var(--amber-soft); border-color: rgba(245,158,11,0.3); }
        .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
        .dot.pulse { animation: pulse 2.5s infinite ease-in-out; }
        #conn-dot { background: var(--muted); }
        #conn-dot.ok { background: var(--green); }
        #conn-dot.err { background: var(--red); }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
        button {
            font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
            border-radius: 10px; padding: 9px 16px; border: 1px solid var(--border);
            background: rgba(255,255,255,0.05); color: var(--text);
            transition: background 0.15s, transform 0.1s;
        }
        button:hover { background: rgba(255,255,255,0.1); }
        button:active { transform: translateY(1px); }
        button:disabled { opacity: 0.5; cursor: default; }
        .btn-primary { background: linear-gradient(90deg, #10B981, #0D9488); border: none; color: #fff; }
        .btn-primary:hover { filter: brightness(1.15); background: linear-gradient(90deg, #10B981, #0D9488); }
        .btn-danger { color: var(--red); border-color: rgba(244,63,94,0.3); background: var(--red-soft); padding: 5px 12px; font-size: 12px; }
        .btn-danger:hover { background: rgba(244,63,94,0.22); }
        .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; }
        .kpi { padding: 20px; display: flex; flex-direction: column; gap: 6px; min-height: 110px; }
        .kpi .label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted); }
        .kpi .value { font-size: 28px; font-weight: 800; }
        .kpi .note { font-size: 12px; color: var(--muted); }
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
        @media (max-width: 960px) { .grid2 { grid-template-columns: 1fr; } }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th {
            text-align: left; padding: 12px 14px; font-size: 11px; text-transform: uppercase;
            letter-spacing: 0.7px; color: var(--muted); background: rgba(255,255,255,0.04);
            border-bottom: 1px solid var(--border);
        }
        td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); }
        tr:hover td { background: rgba(255,255,255,0.02); }
        .empty { text-align: center; color: var(--muted); padding: 28px !important; }
        .mono { font-family: var(--mono); }
        .up { color: var(--green); }
        .down { color: var(--red); }
        .side-badge { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 7px; border: 1px solid; }
        .side-badge.LONG { color: var(--green); background: var(--green-soft); border-color: rgba(16,185,129,0.25); }
        .side-badge.SHORT { color: var(--red); background: var(--red-soft); border-color: rgba(244,63,94,0.25); }
        .tag { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 6px; border: 1px solid var(--border); color: var(--muted); }
        .tag.locked { color: var(--cyan); border-color: rgba(34,211,238,0.3); background: rgba(34,211,238,0.08); }
        .scroll { overflow: auto; }
        .scroll::-webkit-scrollbar { width: 8px; height: 8px; }
        .scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 4px; }
        #logs {
            height: 300px; overflow-y: auto; font-family: var(--mono); font-size: 11.5px;
            color: rgba(52, 211, 153, 0.9); background: rgba(0,0,0,0.4); padding: 14px;
            border-radius: 12px; white-space: pre-wrap; word-break: break-all; line-height: 1.6;
        }
        .basket-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; max-height: 320px; overflow-y: auto; padding: 2px; }
        .coin {
            display: flex; justify-content: space-between; align-items: center; padding: 12px;
            background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.05);
            border-radius: 12px; transition: border-color 0.15s;
        }
        .coin:hover { border-color: rgba(255,255,255,0.15); }
        .coin .name { font-weight: 700; font-size: 13px; }
        .coin .pair { font-size: 10px; color: var(--muted); font-family: var(--mono); }
        .coin .px { font-size: 12px; font-family: var(--mono); font-weight: 600; text-align: right; }
        .coin .chg { font-size: 10.5px; font-family: var(--mono); font-weight: 700; text-align: right; }
        @keyframes flashUp { 0% { background: rgba(16,185,129,0.25); } 100% { background: rgba(255,255,255,0.04); } }
        @keyframes flashDown { 0% { background: rgba(244,63,94,0.25); } 100% { background: rgba(255,255,255,0.04); } }
        .flash-up { animation: flashUp 0.9s ease-out; }
        .flash-down { animation: flashDown 0.9s ease-out; }
        #settings-panel { display: none; padding: 20px; }
        #settings-panel.open { display: block; }
        .settings-row { display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; }
        .field { display: flex; flex-direction: column; gap: 5px; }
        .field label { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; }
        .field input {
            font: inherit; font-family: var(--mono); font-size: 13px; width: 130px;
            background: rgba(0,0,0,0.35); color: var(--text); border: 1px solid var(--border);
            border-radius: 8px; padding: 8px 10px;
        }
        .field input:focus { outline: none; border-color: rgba(16,185,129,0.5); }
        #settings-msg { font-size: 12px; margin-left: 8px; }
        .section-head { display: flex; justify-content: space-between; align-items: center; }
        .hint { font-size: 11.5px; color: var(--muted); }
        svg text { font-family: var(--mono); }
    </style>
</head>
<body>
    <div class="wrap">

        <header>
            <div>
                <div class="row">
                    <h1>VIBE-TRADING</h1>
                    <span class="chip active" id="bot-chip"><span class="dot pulse" style="background: var(--green)"></span><span id="bot-chip-text">HYBRID BOT ACTIVE</span></span>
                    <span class="dot" id="conn-dot" title="Connection status"></span>
                </div>
                <p class="sub">Multi-asset dynamic basket scanning with real-time LLM risk validation.</p>
            </div>
            <div class="row">
                <button class="btn-primary" id="scan-btn" onclick="triggerScan()">Scan Markets Now</button>
                <button onclick="refreshBasket()" id="basket-btn">Refresh Basket</button>
                <button onclick="toggleBot()" id="pause-btn">Pause Bot</button>
                <button onclick="toggleSettings()">Settings</button>
            </div>
        </header>

        <div class="card" id="settings-panel">
            <div class="settings-row">
                <div class="field"><label>Max Positions (1-10)</label><input id="set-max_positions" type="number" min="1" max="10" step="1"></div>
                <div class="field"><label>ATR Multiplier (0.5-10)</label><input id="set-atr_multiplier" type="number" min="0.5" max="10" step="0.1"></div>
                <div class="field"><label>Min Stop % (0.1-10)</label><input id="set-min_stop_pct" type="number" min="0.1" max="10" step="0.1"></div>
                <div class="field"><label>Position Size % (1-100)</label><input id="set-position_pct" type="number" min="1" max="100" step="1"></div>
                <div class="field"><label>Basket Refresh (1-24h)</label><input id="set-basket_refresh_hours" type="number" min="1" max="24" step="1"></div>
                <div class="field"><label>Stale Exit (min, 0=off)</label><input id="set-stale_exit_minutes" type="number" min="0" max="360" step="15"></div>
                <div class="field"><label>Time-Stop (min, 0=off)</label><input id="set-time_stop_minutes" type="number" min="0" max="360" step="15"></div>
                <div class="field"><label>Time-Stop MFE % (0.1-2)</label><input id="set-time_stop_min_mfe_pct" type="number" min="0.1" max="2" step="0.1"></div>
                <div class="field"><label>Flip Cooldown (h, 0=off)</label><input id="set-flip_cooldown_hours" type="number" min="0" max="48" step="1"></div>
                <div class="field"><label>Short Range Max % (100=off)</label><input id="set-short_range_max_pct" type="number" min="10" max="100" step="5"></div>
                <div class="field"><label>Marginal Size Factor (1=off)</label><input id="set-marginal_size_factor" type="number" min="0.1" max="1" step="0.1"></div>
                <div class="field"><label>Basket Mover Slots (0-15)</label><input id="set-basket_movers_slots" type="number" min="0" max="15" step="1"></div>
                <div class="field"><label>Regime Filter</label><label style="display:flex;align-items:center;gap:8px;font-size:13px;padding:9px 0;cursor:pointer"><input type="checkbox" id="set-regime_filter_enabled"> half-size counter-regime trades</label></div>
                <div class="field"><label>Profit Ladder</label><label style="display:flex;align-items:center;gap:8px;font-size:13px;padding:9px 0;cursor:pointer"><input type="checkbox" id="set-ladder_enabled"> tighten trail as profit grows</label></div>
                <button class="btn-primary" onclick="saveSettings()">Save</button>
                <span id="settings-msg"></span>
            </div>
        </div>

        <div class="kpis">
            <div class="card kpi">
                <span class="label">Active Basket</span>
                <div class="value" id="basket-count">0 Pairs</div>
                <p class="note" id="basket-list" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">-</p>
            </div>
            <div class="card kpi" style="border-color: rgba(16,185,129,0.25)">
                <span class="label" style="color: var(--green)">Open Positions</span>
                <div class="value" id="positions-count">0</div>
                <p class="note" id="positions-unrealized-pnl">Unrealized P&L: $0.00 (0.00%)</p>
            </div>
            <div class="card kpi" style="border-color: rgba(34,211,238,0.25)">
                <span class="label">Virtual Wallet (Paper Trading)</span>
                <div class="value mono" style="color: var(--cyan)" id="wallet-balance">$ 10,000.00</div>
                <p class="note" id="wallet-pnl">Total P&L: +$0.00 (0.00%)</p>
            </div>
        </div>

        <div>
            <div class="section-head" style="margin-bottom: 12px">
                <h2>Equity Curve (Realized)</h2>
                <span class="hint" id="equity-hint">Waiting for completed trades...</span>
            </div>
            <div class="card" style="padding: 18px">
                <div id="equity-chart"></div>
            </div>
        </div>

        <div class="grid2">
            <div>
                <h2 style="margin-bottom: 12px">Open Trades Status</h2>
                <div class="card scroll">
                    <table>
                        <thead><tr>
                            <th>Symbol</th><th>Side</th><th>Entry / Current</th><th>Stop Loss</th>
                            <th>Unrealized P&L</th><th>Trend</th><th>Status</th><th></th>
                        </tr></thead>
                        <tbody id="positions-body">
                            <tr><td colspan="8" class="empty">No open positions. Running scanner to find opportunities...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <div>
                <div class="section-head" style="margin-bottom: 12px">
                    <h2>Live Execution Logs</h2>
                    <span class="hint" id="log-timestamp">Last updated: just now</span>
                </div>
                <div class="card" style="padding: 14px">
                    <div id="logs" class="scroll">Loading bot execution logs...</div>
                </div>
            </div>
        </div>

        <div>
            <div class="section-head" style="margin-bottom: 12px">
                <h2>Dynamic Basket Monitor</h2>
                <span class="hint">Real-time quotes fetched directly from Binance</span>
            </div>
            <div class="card" style="padding: 18px">
                <div class="basket-grid scroll" id="basket-monitor-grid">
                    <div class="empty" style="grid-column: 1/-1">Fetching real-time market data...</div>
                </div>
            </div>
        </div>

        <div>
            <h2 style="margin-bottom: 12px">Simulated Trade History</h2>
            <div class="card scroll">
                <table>
                    <thead><tr>
                        <th>Symbol</th><th>Side</th><th>Entry Price</th><th>Exit Price</th>
                        <th>Fees</th><th>Net P&L (USD)</th><th>Performance</th><th>Exit Time</th>
                    </tr></thead>
                    <tbody id="history-body">
                        <tr><td colspan="8" class="empty">No completed trades yet. Simulation is running...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

    </div>

    <script>
        const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        const fmt = (n, d=2) => Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
        // Adaptive price precision: 4 significant digits for sub-$1 coins (0.0004012, not 0.0004)
        const fmtPrice = p => p >= 1
            ? p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
            : Number(p.toPrecision(4)).toString();

        // Client-side price ring buffers for position sparklines (page lifetime only)
        const priceBuf = {};
        const prevPrices = {};
        const BUF_MAX = 100;

        function pushPrice(symbol, price) {
            if (!priceBuf[symbol]) priceBuf[symbol] = [];
            priceBuf[symbol].push(price);
            if (priceBuf[symbol].length > BUF_MAX) priceBuf[symbol].shift();
        }

        function sparkline(symbol, positive) {
            const buf = priceBuf[symbol] || [];
            if (buf.length < 2) return '<span class="hint">--</span>';
            const w = 90, h = 26, min = Math.min(...buf), max = Math.max(...buf);
            const span = (max - min) || 1;
            const pts = buf.map((p, i) =>
                `${(i / (buf.length - 1) * w).toFixed(1)},${(h - 2 - (p - min) / span * (h - 4)).toFixed(1)}`
            ).join(' ');
            const color = positive ? 'var(--green)' : 'var(--red)';
            return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
        }

        function renderEquity(points) {
            const el = document.getElementById('equity-chart');
            const hint = document.getElementById('equity-hint');
            if (!points || points.length < 2) {
                el.innerHTML = '<div class="empty">Equity curve appears after the first completed trade.</div>';
                return;
            }
            const balances = points.map(p => p.balance);
            const min = Math.min(...balances), max = Math.max(...balances);
            const pad = (max - min) * 0.15 || max * 0.005 || 1;
            const lo = min - pad, hi = max + pad, span = hi - lo;
            const W = 1160, H = 180, L = 70, R = 12, T = 10, B = 24;
            const iw = W - L - R, ih = H - T - B;
            const x = i => L + i / (points.length - 1) * iw;
            const y = b => T + ih - (b - lo) / span * ih;
            const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.balance).toFixed(1)}`).join(' ');
            const area = `${path} L${x(points.length-1).toFixed(1)},${T+ih} L${L},${T+ih} Z`;
            const last = points[points.length - 1], first = points[0];
            const up = last.balance >= first.balance;
            const color = up ? 'var(--green)' : 'var(--red)';
            const gridLines = [0, 0.5, 1].map(f => {
                const gy = T + ih * f, val = hi - span * f;
                return `<line x1="${L}" y1="${gy}" x2="${W-R}" y2="${gy}" stroke="rgba(255,255,255,0.06)"/>` +
                       `<text x="${L-8}" y="${gy+4}" text-anchor="end" font-size="10" fill="var(--muted)">$${fmt(val, 0)}</text>`;
            }).join('');
            el.innerHTML =
                `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">
                    ${gridLines}
                    <path d="${area}" fill="${up ? 'rgba(16,185,129,0.08)' : 'rgba(244,63,94,0.08)'}"/>
                    <path d="${path}" fill="none" stroke="${color}" stroke-width="2"/>
                    <circle cx="${x(points.length-1)}" cy="${y(last.balance)}" r="3.5" fill="${color}"/>
                    <text x="${L}" y="${H-6}" font-size="10" fill="var(--muted)">${esc(points[1].time)}</text>
                    <text x="${W-R}" y="${H-6}" text-anchor="end" font-size="10" fill="var(--muted)">${esc(last.time)}</text>
                </svg>`;
            hint.textContent = `${points.length - 1} trades | $${fmt(first.balance)} → $${fmt(last.balance)}`;
        }

        function renderBasket(basket) {
            const keys = Object.keys(basket);
            document.getElementById('basket-count').innerText = `${keys.length} Pairs`;
            document.getElementById('basket-list').innerText = keys.join(', ');
            if (!keys.length) return;
            document.getElementById('basket-monitor-grid').innerHTML = keys.map(symbol => {
                const coin = basket[symbol];
                const chgCls = coin.change >= 0 ? 'up' : 'down';
                const sign = coin.change >= 0 ? '+' : '';
                const prev = prevPrices[symbol];
                let flash = '';
                if (prev !== undefined && coin.price !== prev) flash = coin.price > prev ? ' flash-up' : ' flash-down';
                prevPrices[symbol] = coin.price;
                return `<div class="coin${flash}">
                    <div><div class="name">${esc(symbol.split('/')[0])}</div><div class="pair">${esc(symbol)}</div></div>
                    <div><div class="px">$ ${fmtPrice(coin.price)}</div><div class="chg ${chgCls}">${sign}${coin.change.toFixed(2)}%</div></div>
                </div>`;
            }).join('');
        }

        function renderPositions(positions) {
            const keys = Object.keys(positions);
            document.getElementById('positions-count').innerText = keys.length;
            const body = document.getElementById('positions-body');
            const pnlEl = document.getElementById('positions-unrealized-pnl');
            if (!keys.length) {
                body.innerHTML = '<tr><td colspan="8" class="empty">No open positions. Running scanner to find opportunities...</td></tr>';
                pnlEl.textContent = 'Unrealized P&L: $0.00 (0.00%)';
                pnlEl.className = 'note';
                return;
            }
            let totalUsd = 0, totalAlloc = 0;
            body.innerHTML = keys.map(symbol => {
                const pos = positions[symbol];
                pushPrice(symbol, pos.current_price);
                totalUsd += pos.pnl_usd || 0;
                totalAlloc += (pos.position_size || 1000) * (pos.leverage || 2);
                const pnl = pos.pnl_usd || 0, pct = pos.pnl_pct || 0;
                const cls = pnl >= 0 ? 'up' : 'down';
                const sign = pnl >= 0 ? '+' : '';
                const lock = pos.breakeven_locked
                    ? '<span class="tag locked">🔒 BE Locked</span>'
                    : '<span class="tag">Trailing</span>';
                return `<tr>
                    <td style="font-weight:700">${esc(symbol)}</td>
                    <td><span class="side-badge ${pos.side === 'LONG' ? 'LONG' : 'SHORT'}">${esc(pos.side)}</span></td>
                    <td class="mono"><div>$ ${fmtPrice(pos.entry_price)}</div><div class="hint">Cur: $ ${fmtPrice(pos.current_price)}</div></td>
                    <td class="mono">$ ${fmtPrice(pos.stop_loss)}</td>
                    <td class="mono ${cls}" style="font-weight:600"><div>${sign}$ ${fmt(pnl)}</div><div style="font-size:11px">${sign}${pct.toFixed(2)}%</div></td>
                    <td>${sparkline(symbol, pnl >= 0)}</td>
                    <td>${lock}</td>
                    <td><button class="btn-danger" onclick="closePos('${esc(symbol)}')">Close</button></td>
                </tr>`;
            }).join('');
            const totalPct = totalAlloc > 0 ? totalUsd / totalAlloc * 100 : 0;
            const sign = totalUsd >= 0 ? '+' : '';
            pnlEl.className = `note ${totalUsd >= 0 ? 'up' : 'down'}`;
            pnlEl.textContent = `Unrealized P&L: ${sign}$${fmt(totalUsd)} (${sign}${totalPct.toFixed(2)}%)`;
        }

        function renderHistory(history) {
            const body = document.getElementById('history-body');
            if (!history || !history.length) {
                body.innerHTML = '<tr><td colspan="8" class="empty">No completed trades yet. Simulation is running...</td></tr>';
                return;
            }
            body.innerHTML = [...history].reverse().map(t => {
                const cls = t.net_pnl_usd >= 0 ? 'up' : 'down';
                const sign = t.net_pnl_usd >= 0 ? '+' : '';
                return `<tr>
                    <td style="font-weight:700">${esc(t.symbol)}</td>
                    <td><span class="side-badge ${t.side === 'LONG' ? 'LONG' : 'SHORT'}">${esc(t.side)}</span></td>
                    <td class="mono">$ ${fmtPrice(t.entry_price)}</td>
                    <td class="mono">$ ${fmtPrice(t.exit_price)}</td>
                    <td class="mono hint">$ ${fmt(t.fees_usd)}</td>
                    <td class="mono ${cls}" style="font-weight:600">${sign}$ ${fmt(t.net_pnl_usd)}</td>
                    <td class="mono ${cls}">${sign}${t.performance_pct.toFixed(2)}%</td>
                    <td class="hint">${esc(t.exit_time)}</td>
                </tr>`;
            }).join('');
        }

        function renderHeader(data) {
            const chip = document.getElementById('bot-chip');
            const chipText = document.getElementById('bot-chip-text');
            const pauseBtn = document.getElementById('pause-btn');
            if (data.paused) {
                chip.className = 'chip paused';
                chip.querySelector('.dot').style.background = 'var(--amber)';
                chipText.textContent = 'HYBRID BOT PAUSED';
                pauseBtn.textContent = 'Resume Bot';
            } else {
                chip.className = 'chip active';
                chip.querySelector('.dot').style.background = 'var(--green)';
                chipText.textContent = 'HYBRID BOT ACTIVE';
                pauseBtn.textContent = 'Pause Bot';
            }
        }

        let settingsLoaded = false;
        function fillSettings(settings) {
            if (settingsLoaded) return; // don't clobber while user edits
            for (const key of ['max_positions', 'atr_multiplier', 'min_stop_pct', 'position_pct', 'basket_refresh_hours', 'stale_exit_minutes', 'time_stop_minutes', 'time_stop_min_mfe_pct', 'flip_cooldown_hours', 'short_range_max_pct', 'marginal_size_factor', 'basket_movers_slots']) {
                const input = document.getElementById('set-' + key);
                if (input && settings[key] !== undefined) input.value = settings[key];
            }
            for (const key of ['ladder_enabled', 'regime_filter_enabled']) {
                const box = document.getElementById('set-' + key);
                if (box) box.checked = !!settings[key];
            }
            settingsLoaded = true;
        }

        async function fetchStatus() {
            const dot = document.getElementById('conn-dot');
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                dot.className = 'ok';
                renderHeader(data);
                fillSettings(data.settings || {});
                renderBasket(data.basket || {});
                renderPositions(data.positions || {});
                renderHistory(data.history || []);
                renderEquity(data.equity_curve || []);

                const wallet = data.wallet || {};
                const bal = wallet.balance || 0, init = wallet.initial_balance || bal;
                const pnl = bal - init, pct = init ? pnl / init * 100 : 0;
                document.getElementById('wallet-balance').innerText = `$ ${fmt(bal)}`;
                const wEl = document.getElementById('wallet-pnl');
                const sign = pnl >= 0 ? '+' : '';
                wEl.className = `note ${pnl >= 0 ? 'up' : 'down'}`;
                wEl.textContent = `Total P&L: ${sign}$${fmt(pnl)} (${sign}${pct.toFixed(2)}%)`;

                const logs = document.getElementById('logs');
                logs.textContent = (data.logs || []).join('\\n');
                logs.scrollTop = logs.scrollHeight;
                document.getElementById('log-timestamp').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
            } catch (err) {
                dot.className = 'err';
                console.error('Failed to fetch dashboard status: ', err);
            }
        }

        async function post(url, body) {
            const opts = { method: 'POST' };
            if (body) {
                opts.headers = { 'Content-Type': 'application/json' };
                opts.body = JSON.stringify(body);
            }
            const response = await fetch(url, opts);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(data.detail || response.statusText);
            return data;
        }

        async function triggerScan() {
            const btn = document.getElementById('scan-btn');
            btn.disabled = true; btn.textContent = 'Scanning...';
            try { await post('/api/scan'); } catch (e) { console.error(e); }
            setTimeout(() => { btn.disabled = false; btn.textContent = 'Scan Markets Now'; fetchStatus(); }, 2000);
        }

        async function refreshBasket() {
            const btn = document.getElementById('basket-btn');
            btn.disabled = true; btn.textContent = 'Refreshing...';
            try { await post('/api/basket/refresh'); } catch (e) { console.error(e); }
            setTimeout(() => { btn.disabled = false; btn.textContent = 'Refresh Basket'; fetchStatus(); }, 3000);
        }

        async function toggleBot() {
            try { await post('/api/bot/toggle'); fetchStatus(); } catch (e) { alert('Toggle failed: ' + e.message); }
        }

        async function closePos(symbol) {
            if (!confirm(`Close position ${symbol} at market price?`)) return;
            try { await post('/api/close', { symbol }); fetchStatus(); }
            catch (e) { alert('Close failed: ' + e.message); }
        }

        function toggleSettings() {
            document.getElementById('settings-panel').classList.toggle('open');
        }

        async function saveSettings() {
            const msg = document.getElementById('settings-msg');
            const updates = {};
            for (const key of ['max_positions', 'atr_multiplier', 'min_stop_pct', 'position_pct', 'basket_refresh_hours', 'stale_exit_minutes', 'time_stop_minutes', 'time_stop_min_mfe_pct', 'flip_cooldown_hours', 'short_range_max_pct', 'marginal_size_factor', 'basket_movers_slots']) {
                const v = document.getElementById('set-' + key).value;
                if (v !== '') updates[key] = Number(v);
            }
            updates.ladder_enabled = document.getElementById('set-ladder_enabled').checked;
            updates.regime_filter_enabled = document.getElementById('set-regime_filter_enabled').checked;
            try {
                await post('/api/settings', updates);
                msg.textContent = 'Saved.'; msg.className = 'up';
                setTimeout(() => { msg.textContent = ''; }, 2500);
            } catch (e) {
                msg.textContent = e.message; msg.className = 'down';
            }
        }

        setInterval(fetchStatus, 3000);
        window.onload = fetchStatus;
    </script>
</body>
</html>
    """
    return html_content
