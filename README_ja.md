<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: あなたのパーソナルトレーディングエージェント</h1>

<p align="center">
  <b>たった1コマンドで、包括的なトレーディング機能を備えたエージェントを起動</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <img src="https://img.shields.io/badge/Skills-69-orange" alt="Skills">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="Swarm">
  <img src="https://img.shields.io/badge/Tools-21-0F766E" alt="Tools">
  <img src="https://img.shields.io/badge/Data_Sources-5-2563EB" alt="Data Sources">
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-主な機能">機能</a> &nbsp;&middot;&nbsp;
  <a href="#-デモ">デモ</a> &nbsp;&middot;&nbsp;
  <a href="#-vibe-tradingとは">概要</a> &nbsp;&middot;&nbsp;
  <a href="#-クイックスタート">始め方</a> &nbsp;&middot;&nbsp;
  <a href="#-cli-リファレンス">CLI</a> &nbsp;&middot;&nbsp;
  <a href="#-api-サーバー">API</a> &nbsp;&middot;&nbsp;
  <a href="#-mcp-プラグイン">MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-プロジェクト構成">構成</a> &nbsp;&middot;&nbsp;
  <a href="#-ロードマップ">ロードマップ</a> &nbsp;&middot;&nbsp;
  <a href="#貢献">貢献</a> &nbsp;&middot;&nbsp;
  <a href="#コントリビューター">コントリビューター</a>
</p>

<p align="center">
  <a href="#-クイックスタート"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 ニュース

- **2026-04-13** 🌐 **クロスマーケット複合バックテスト**: 新しい`CompositeEngine`により、異なる市場の銘柄（例：A株＋暗号資産）を**共有資金プール**で同時にバックテスト可能。T+1、ファンディング手数料、スワップなどの市場ルールは銘柄ごとに適用、シグナルは各銘柄の取引カレンダーで整列。`source: "auto"`と`["000001.SZ", "BTC-USDT"]`のような混合コードで利用可能。
- **2026-04-12** 🌍 **マルチプラットフォームインジケーター出力**: `/pine`コマンドで**TradingView (Pine Script v6)**、**通達信/同花順/東方財富 (TDX数式)**、**MetaTrader 5 (MQL5)** の3プラットフォームに一括エクスポート — 国際株式、中国A株、グローバルFX/CFD市場をカバー。
- **2026-04-11** 🛡️ **信頼性とDX向上**：`vibe-trading init` 対話式 .env ブートストラップ（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)）、起動時にLLM・データソースのプリフライトチェック、プライマリソースが空の場合のランタイムフォールバック、バックテストエンジンのデータ検証とエラー分離を強化、エージェントとSwarmプロンプトに現在日時を注入。コミュニティPR [#21](https://github.com/HKUDS/Vibe-Trading/pull/21) で多言語README（zh/ja/ko）を追加。
- **2026-04-10** 📦 **v0.1.4**: Dockerビルドを修正（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)）、`web_search` MCPツールを追加（合計17）、依存関係とMCPに`akshare`/`ccxt`を追加。11のLLMプロバイダー（DeepSeek, Groq, Gemini, Ollama など）、すべての調整パラメータを`.env`で設定可能。`ml-strategy`スキルを強化。PyPIとClawHubに公開。
- **2026-04-09** 📊 **Backtest Wave 2 — マルチアセットエンジン**: ChinaFutures（CFFEX/SHFE/DCE/ZCE、50+銘柄）、GlobalFutures（CME/ICE/Eurex、30+銘柄）、Forex（24通貨ペア、スプレッド＋スワップ）、Options v2（アメリカン行使、IVスマイル）を追加。統計的検証: モンテカルロ置換検定、ブートストラップSharpe信頼区間、ウォークフォワード分析。
- **2026-04-08** 🔧 **マルチマーケットバックテスト**（市場別ルール対応）と**TradingView向けPine Script v6エクスポート**。**データソース拡張**: 自動フォールバック付き5ソース、`web_search`ツール、スキル分類（7カテゴリ）。
- **2026-04-01** 🚀 **v0.1.0** — 初期リリース: ReActエージェント、64スキル、29スウォームプリセット、クロスマーケットバックテスト、CLI + Web UI + MCPサーバー。

---

## 💡 Vibe-Tradingとは？

Vibe-Tradingは、自然言語リクエストをグローバル市場向けの実行可能なトレーディング戦略、リサーチ洞察、ポートフォリオ分析へと変換する、AI駆動のマルチエージェント金融ワークスペースです。

### 主な能力:
• **Strategy Generation** — アイデアから自動でトレーディングコードを生成<br>
• **Smart Data Access** — 自動フォールバック付き5つのデータソース、全市場ゼロ設定<br>
• **Performance Testing** — 歴史的市場データで戦略を検証<br>
• **Multi-Platform Export** — ワンクリックでTradingView、通達信/同花順/東方財富、MT5にエクスポート<br>
• **Expert Teams** — 複雑なリサーチタスクに特化したAIエージェントチームを展開<br>
• **Live Updates** — 分析プロセス全体をリアルタイムで観察

---

## ✨ 主な機能

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="Research"/><br>
      <h3>🔍 トレーディング向けDeepResearch</h3>
      <img src="https://img.shields.io/badge/69_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="Skills" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 市場横断のマルチドメイン分析<br>
        • 自動ストラテジー／シグナル生成<br>
        • マクロ経済リサーチとインサイト<br>
        • チャットによる自然言語タスクルーティング
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="Swarm"/><br>
      <h3>🐝 スウォームインテリジェンス</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="Swarm" /><br><br>
      <div align="left">
        • 即戦力の29種トレーディングチームプリセット<br>
        • DAGベースのマルチエージェントオーケストレーション<br>
        • リアルタイム意思決定ストリーミングダッシュボード<br>
        • YAMLによるカスタムチーム構築
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-backtest.png" height="150" alt="Backtest"/><br>
      <h3>📊 クロスマーケットバックテスト</h3>
      <img src="https://img.shields.io/badge/5_Data_Sources-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="Backtest" /><br><br>
      <div align="left">
        • A株、HK/US株式、暗号資産、先物、FXに対応<br>
        • 7つの市場エンジン + クロスマーケット複合エンジン（共有資金プール）<br>
        • 統計的検証: モンテカルロ、ブートストラップCI、ウォークフォワード<br>
        • 15以上のパフォーマンス指標と4種類のオプティマイザー
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-quant.png" height="150" alt="Quant"/><br>
      <h3>🧮 クオンツ分析ツールキット</h3>
      <img src="https://img.shields.io/badge/Quant_Tools-C77DFF?style=for-the-badge&logo=wolfram&logoColor=white" alt="Quant" /><br><br>
      <div align="left">
        • ファクターIC/IR分析と分位バックテスト<br>
        • ブラック–ショールズ価格と完全なギリシャ計算<br>
        • テクニカルパターンの認識と検出<br>
        • MVO/リスクパリティ/BLによるポートフォリオ最適化
      </div>
    </td>
  </tr>
</table>

## 7カテゴリにわたる69スキル

- 📊 69の金融特化スキルを7カテゴリに整理
- 🌐 伝統的市場から暗号・DeFiまで完全カバー
- 🔬 データ取得からクオンツリサーチまでの包括的能力

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 15 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 8 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader` |

## 29種のエージェントスウォームチームプリセット

- 🏢 即利用できる29種のエージェントチーム
- ⚡ 事前構成された金融ワークフロー
- 🎯 投資・トレーディング・リスク管理のプリセット

| Preset | Workflow |
|--------|----------|
| `investment_committee` | 強気/弱気ディベート → リスクレビュー → PM最終判断 |
| `global_equities_desk` | A株 + HK/US + 暗号研究者 → グローバルストラテジスト |
| `crypto_trading_desk` | ファンディング/ベーシス + 清算 + フロー → リスクマネージャー |
| `earnings_research_desk` | ファンダメンタル + リビジョン + オプション → 決算ストラテジスト |
| `macro_rates_fx_desk` | 金利 + FX + コモディティ → マクロPM |
| `quant_strategy_desk` | スクリーニング + ファクターリサーチ → バックテスト → リスク監査 |
| `technical_analysis_panel` | クラシックTA + 一目均衡表 + ハーモニック + エリオット + SMC → コンセンサス |
| `risk_committee` | ドローダウン + テイルリスク + レジームレビュー → サインオフ |
| `global_allocation_committee` | A株 + 暗号 + HK/US → クロスマーケット配分 |

<sub>さらに20以上の専門プリセット — `vibe-trading --swarm-presets`で全プリセットを確認できます。</sub>

### 🎬 デモ

<div align="center">
<table>
<tr>
<td width="50%">

https://github.com/user-attachments/assets/4e4dcb80-7358-4b9a-92f0-1e29612e6e86

</td>
<td width="50%">

https://github.com/user-attachments/assets/3754a414-c3ee-464f-b1e8-78e1a74fbd30

</td>
</tr>
<tr>
<td colspan="2" align="center"><sub>☝️ 自然言語バックテスト＆マルチエージェントスウォームディベート — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 クイックスタート

### ワンラインインストール（PyPI）

```bash
pip install vibe-trading-ai
```

> **パッケージ名とコマンド:** PyPIパッケージは`vibe-trading-ai`。インストール後に3つのコマンドが使えます:
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | 対話型CLI / TUI |
> | `vibe-trading serve` | FastAPIウェブサーバー起動 |
> | `vibe-trading-mcp` | MCPサーバー起動（Claude Desktop, OpenClaw, Cursorなど） |

```bash
vibe-trading init              # 対話的な.envセットアップ
vibe-trading                   # CLI起動
vibe-trading serve --port 8899 # Web UI起動
vibe-trading-mcp               # MCPサーバー（stdio）起動
```

### 使い方を選ぶ

| Path | Best for | Time |
|------|----------|------|
| **A. Docker** | 今すぐ試す、ローカル設定ゼロ | 2分 |
| **B. Local install** | 開発、フルCLIアクセス | 5分 |
| **C. MCP plugin** | 既存エージェントへ組み込み | 3分 |
| **D. ClawHub** | クローン不要のワンコマンド | 1分 |

### 前提条件

- サポートされる任意のプロバイダーの**LLM APIキー** — もしくは**Ollama**でローカル実行（キー不要）
- Path Bでは**Python 3.11+**
- Path Aでは**Docker**

> **サポートされるLLMプロバイダー:** OpenRouter, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama（ローカル）。設定は`.env.example`を参照。

> **Tip:** すべての市場でAPIキーなしでも動作（自動フォールバック）。yfinance（HK/US）、OKX（暗号）、AKShare（A株・US・HK・先物・FX）は無料。Tushareトークンは任意 — A株はAKShareで無料フォールバック。

### Path A: Docker（セットアップ不要）

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# agent/.envを編集 — 利用するLLMプロバイダーのキーを設定
docker compose up --build
```

`http://localhost:8899`を開きます。バックエンドとフロントエンドを1コンテナで提供。

### Path B: ローカルインストール

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # 編集 — LLMプロバイダーのAPIキーを設定
vibe-trading                       # 対話型TUIを起動
```

<details>
<summary><b>Web UIを起動（任意）</b></summary>

```bash
# Terminal 1: APIサーバー
vibe-trading serve --port 8899

# Terminal 2: フロントエンド開発サーバー
cd frontend && npm install && npm run dev
```

`http://localhost:5899`を開きます。フロントエンドは`localhost:8899`へAPIプロキシします。

**本番モード（単一サーバー）:**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPIがdist/を静的配信
```

</details>

### Path C: MCP プラグイン

下記の[MCP プラグイン](#-mcp-プラグイン)セクションを参照。

### Path D: ClawHub（ワンコマンド）

```bash
npx clawhub@latest install vibe-trading --force
```

スキル＋MCP設定がエージェントのskillsディレクトリにダウンロードされます。詳細は[MCP プラグイン](#-mcp-プラグイン)を参照。

---

## 🧠 環境変数

`agent/.env.example`を`agent/.env`へコピーし、使いたいプロバイダーのブロックをアンコメント。各プロバイダーは3〜4変数を使用:

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | プロバイダー名（`openrouter`, `deepseek`, `groq`, `ollama` など） |
| `<PROVIDER>_API_KEY` | Yes* | APIキー（`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` など） |
| `<PROVIDER>_BASE_URL` | Yes | APIエンドポイントURL |
| `LANGCHAIN_MODEL_NAME` | Yes | モデル名（例: `deepseek/deepseek-v3.2`） |
| `TUSHARE_TOKEN` | No | A株データ用Tushare Proトークン（AKShareにフォールバック） |
| `TIMEOUT_SECONDS` | No | LLM呼び出しタイムアウト（既定120s） |

<sub>* OllamaはAPIキー不要。</sub>

**無料データ（キー不要）:** AKShare経由のA株、yfinance経由のHK/US株式、OKX経由の暗号、CCXT経由の100+暗号取引所。市場ごとに最適なソースを自動選択。

---

## 🖥 CLI リファレンス

```bash
vibe-trading               # 対話型TUI
vibe-trading run -p "..."  # シングル実行
vibe-trading serve         # APIサーバー
```

<details>
<summary><b>TUI内スラッシュコマンド</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | すべてのコマンドを表示 |
| `/skills` | 68の金融スキルを一覧表示 |
| `/swarm` | 29のスウォームチームプリセットを一覧表示 |
| `/swarm run <preset> [vars_json]` | スウォームチームをライブストリーミングで実行 |
| `/swarm list` | スウォーム実行履歴 |
| `/swarm show <run_id>` | スウォーム実行の詳細 |
| `/swarm cancel <run_id>` | 実行中スウォームをキャンセル |
| `/list` | 直近の実行 |
| `/show <run_id>` | 実行詳細と指標 |
| `/code <run_id>` | 生成された戦略コード |
| `/pine <run_id>` | インジケーターエクスポート（TradingView + TDX + MT5）|
| `/trace <run_id>` | 実行リプレイ |
| `/continue <run_id> <prompt>` | 実行を新指示で継続 |
| `/sessions` | チャットセッション一覧 |
| `/settings` | 実行時設定を表示 |
| `/clear` | 画面クリア |
| `/quit` | 終了 |
</details>

<details>
<summary><b>単発実行とフラグ</b></summary>

```bash
vibe-trading run -p "Backtest BTC-USDT MACD strategy, last 30 days"
vibe-trading run -p "Analyze AAPL momentum" --json
vibe-trading run -f strategy.txt
echo "Backtest 000001.SZ RSI" | vibe-trading run
```

```bash
vibe-trading -p "your prompt"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC outlook"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # インジケーターエクスポート（TradingView + TDX + MT5）
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

</details>

---

## 🌐 API サーバー

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | 実行一覧 |
| `GET` | `/runs/{run_id}` | 実行詳細 |
| `GET` | `/runs/{run_id}/pine` | マルチプラットフォームインジケーターエクスポート |
| `POST` | `/sessions` | セッション作成 |
| `POST` | `/sessions/{id}/messages` | メッセージ送信 |
| `GET` | `/sessions/{id}/events` | SSEイベントストリーム |
| `POST` | `/upload` | PDF/ファイルのアップロード |
| `GET` | `/swarm/presets` | スウォームプリセット一覧 |
| `POST` | `/swarm/runs` | スウォーム実行開始 |
| `GET` | `/swarm/runs/{id}/events` | スウォームSSEストリーム |

インタラクティブドキュメント: `http://localhost:8899/docs`

---

## 🔌 MCP プラグイン

Vibe-Tradingは、あらゆるMCP互換クライアント向けに17のMCPツールを提供します。stdioサブプロセスとして実行 — サーバーセットアップ不要。**17中16ツールはAPIキー不要**（HK/US/暗号）。`run_swarm`のみLLMキーが必要。

<details>
<summary><b>Claude Desktop</b></summary>

`claude_desktop_config.json`に追加:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

</details>

<details>
<summary><b>OpenClaw</b></summary>

`~/.openclaw/config.yaml`に追加:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / 他MCPクライアント</b></summary>

```bash
vibe-trading-mcp                  # stdio（デフォルト）
vibe-trading-mcp --transport sse  # Webクライアント向けSSE
```

</details>

**公開MCPツール（17）:** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`。

<details>
<summary><b>ClawHubからインストール（ワンコマンド）</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> 外部APIを参照するためVirusTotalの自動スキャンが走るので`--force`が必要。コードは完全オープンソースで検証可能。

スキル＋MCP設定がエージェントのskillsディレクトリにダウンロードされます。クローン不要。

ClawHubで閲覧: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — 自己進化スキル</b></summary>

全69金融スキルは[open-space.cloud](https://open-space.cloud)に公開され、OpenSpaceの自己進化エンジンで自律的に進化します。

OpenSpaceで使うには、両方のMCPサーバーをエージェント設定に追加:

```json
{
  "mcpServers": {
    "openspace": {
      "command": "openspace-mcp",
      "toolTimeout": 600,
      "env": {
        "OPENSPACE_HOST_SKILL_DIRS": "/path/to/vibe-trading/agent/src/skills",
        "OPENSPACE_WORKSPACE": "/path/to/OpenSpace"
      }
    },
    "vibe-trading": {
      "command": "vibe-trading-mcp"
    }
  }
}
```

OpenSpaceが全69スキルを自動検出し、auto-fix/auto-improve/コミュニティ共有を有効化。`search_skills("finance backtest")`でVibe-Tradingスキルを検索可能。

</details>

---

## 📁 プロジェクト構成

<details>
<summary><b>クリックして展開</b></summary>

```
Vibe-Trading/
├── agent/                          # バックエンド (Python)
│   ├── cli.py                      # CLIエントリーポイント — 対話型TUI + サブコマンド
│   ├── api_server.py               # FastAPIサーバー — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCPサーバー — OpenClaw / Claude Desktop向け17ツール
│   │
│   ├── src/
│   │   ├── agent/                  # ReActエージェントコア
│   │   │   ├── loop.py             #   メイン推論ループ
│   │   │   ├── skills.py           #   スキルローダー（69 SKILL.md, 7カテゴリ）
│   │   │   ├── tools.py            #   ツールオーケストレーション
│   │   │   ├── context.py          #   システムプロンプトビルダー
│   │   │   ├── memory.py           #   実行メモリ / アーティファクトストア
│   │   │   └── trace.py            #   実行トレースライター
│   │   │
│   │   ├── tools/                  # 21のエージェントツール
│   │   │   ├── backtest_tool.py    #   バックテスト実行
│   │   │   ├── factor_analysis_tool.py
│   │   │   ├── options_pricing_tool.py
│   │   │   ├── pattern_tool.py     #   チャートパターン検出
│   │   │   ├── doc_reader_tool.py  #   PDFリーダー（OCRフォールバック）
│   │   │   ├── web_reader_tool.py  #   webページリーダー（Jina）
│   │   │   ├── web_search_tool.py  #   DuckDuckGoウェブ検索
│   │   │   ├── swarm_tool.py       #   スウォームチーム起動
│   │   │   └── ...                 #   ファイルI/O, bash, tasks など
│   │   │
│   │   ├── skills/                 # 7カテゴリに渡る69金融スキル (各SKILL.md)
│   │   ├── swarm/                  # スウォームDAG実行エンジン
│   │   ├── session/                # マルチターンチャットセッション管理
│   │   └── providers/              # LLMプロバイダー抽象化
│   │
│   ├── backtest/                   # バックテストエンジン
│   │   ├── engines/                #   7エンジン + クロスマーケット複合エンジン + options_portfolio
│   │   ├── loaders/                #   5ソース: tushare, okx, yfinance, akshare, ccxt
│   │   │   ├── base.py             #   DataLoader Protocol
│   │   │   └── registry.py         #   レジストリ + 自動フォールバックチェーン
│   │   └── optimizers/             #   MVO, equal vol, max div, risk parity
│   │
│   └── config/swarm/               # 29のスウォームプリセットYAML定義
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, RunDetail, Compare
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustandステート管理
│
├── Dockerfile                      # マルチステージビルド
├── docker-compose.yml              # ワンコマンドデプロイ
├── pyproject.toml                  # パッケージ設定 + CLIエントリーポイント
└── LICENSE                         # MIT
```

</details>

---

## 🏛 エコシステム

Vibe-Tradingは**[HKUDS](https://github.com/HKUDS)**エージェントエコシステムの一部です:

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>エージェントスウォームインテリジェンス</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>超軽量パーソナルAIアシスタント</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>すべてのソフトウェアをエージェントネイティブに</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>自己進化型AIエージェントスキル</sub>
    </td>
  </tr>
</table>

---

## 🗺 ロードマップ

> 段階的にリリースします。作業開始時に[Issues](https://github.com/HKUDS/Vibe-Trading/issues)へ移動します。

| Phase | Feature | Status |
|-------|---------|--------|
| **Analysis & Viz** | オプションボラティリティサーフェスとギリシャ値3D可視化 | Planned |
| | ローリングウィンドウ＋クラスタリングによるクロスアセット相関ヒートマップ | Planned |
| | CLIバックテスト出力でのベンチマーク比較 | Planned |
| | バックテスト指標へのCalmar Ratio & Omega Ratio追加 | Planned |
| **Skills & Presets** | 配当分析スキル | Planned |
| | ESG/サステナブル投資スウォームプリセット | Planned |
| | 新興市場リサーチデスクスウォームプリセット | Planned |
| **Portfolio & Optimization** | レバレッジ・セクター上限・回転率制約付き高度ポートフォリオオプティマイザー | Planned |
| **Future** | 初心者チュートリアル: 「5分で自然言語バックテスト」 | Planned |
| | WebSocket経由のライブデータストリーミング | Exploring |
| | ストラテジーマーケットプレイス（共有・発見） | Exploring |

---

## 貢献

貢献を歓迎します！ガイドラインは[CONTRIBUTING.md](CONTRIBUTING.md)を参照してください。

**Good first issues**は[`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)タグ付き — どれか選んで始めてください。

より大きな貢献を検討中ですか？上記[ロードマップ](#-ロードマップ)を確認し、着手前にIssueで相談してください。

---

## コントリビューター

Vibe-Tradingに貢献してくださった皆さんに感謝します！

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## 免責事項

Vibe-Tradingはリサーチ・シミュレーション・バックテスト用途のみです。投資助言ではなく、リアルトレードを実行しません。過去の実績は将来の結果を保証しません。

## ライセンス

MIT License — [LICENSE](LICENSE)を参照

---

<p align="center">
  <b>Vibe-Trading</b>への訪問に感謝 ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
