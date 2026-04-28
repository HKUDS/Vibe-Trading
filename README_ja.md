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
  <img src="https://img.shields.io/badge/Skills-72-orange" alt="Skills">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="Swarm">
  <img src="https://img.shields.io/badge/Tools-27-0F766E" alt="Tools">
  <img src="https://img.shields.io/badge/Data_Sources-6-2563EB" alt="Data Sources">
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

- **2026-04-28** 🚀 **v0.1.6 リリース**（`pip install -U vibe-trading-ai`）: `pip install` / `uv tool install` 後に `vibe-trading --swarm-presets` が空を返す問題を修正（[#55](https://github.com/HKUDS/Vibe-Trading/issues/55)）— プリセット YAML を `src.swarm` パッケージ内に同梱、6 件の回帰テストでピン留め。加えて AKShare ローダーが ETF（`510300.SH`）と外国為替（`USDCNH`）を正しいエンドポイントにルーティング、レジストリフォールバックも強化。v0.1.5 以降の更新を集約: ベンチマーク比較パネル、`/upload` ストリーミング + サイズ制限、Futu ローダー（HK + A 株）、vnpy エクスポートスキル、セキュリティ強化、フロントエンド遅延ロード（688KB → 262KB）。
- **2026-04-27** 📊 **ベンチマーク比較パネル + アップロード安全性**: バックテスト出力にベンチマーク比較パネル（銘柄 / ベンチマークリターン / 超過リターン / 情報比率）を追加、yfinance 経由で SPY・CSI 300 などを解決（[#48](https://github.com/HKUDS/Vibe-Trading/issues/48)）。加えて `/upload` を 1MB チャンクのストリーミングに変更し、`MAX_UPLOAD_SIZE` を超えた時点で中断 + 部分ファイルをクリーンアップ。50MB 上限が悪意/巨大リクエスト下でも実効化（[#53](https://github.com/HKUDS/Vibe-Trading/pull/53)）—— 4 件の回帰テストでピン留め。
- **2026-04-22** 🛡️ **ハードニング + 新規連携**: `safe_path` でパス封じ込めを強制 + 取引明細/シャドウアカウント系ツールをサンドボックス化、`MANIFEST.in` を追加して sdist に `.env.example` / テスト / Docker ファイルを同梱、フロントエンドのルート単位遅延ロードで初期バンドル 688KB → 262KB。加えて富途（Futu）の香港株/A 株データローダー（[#47](https://github.com/HKUDS/Vibe-Trading/pull/47)）と vnpy CtaTemplate エクスポートスキル（[#46](https://github.com/HKUDS/Vibe-Trading/pull/46)）を追加。

<details>
<summary>過去のニュース</summary>

- **2026-04-21** 🛡️ **ワークスペース + ドキュメント**: 相対 `run_dir` をアクティブな run ディレクトリに正規化（[#43](https://github.com/HKUDS/Vibe-Trading/pull/43)）。README に使用例を追加（[#45](https://github.com/HKUDS/Vibe-Trading/pull/45)）。
- **2026-04-20** 🔌 **推論モデル + Swarm 修正**: `reasoning_content` を `ChatOpenAI` の全シリアライズパスで保持 — Kimi / DeepSeek / Qwen thinking がエンドツーエンドで動作（[#39](https://github.com/HKUDS/Vibe-Trading/issues/39)）。Swarm をストリーミング化 + Ctrl+C のクリーン終了（[#42](https://github.com/HKUDS/Vibe-Trading/issues/42)）。
- **2026-04-19** 📦 **v0.1.5**: PyPI と ClawHub に公開。`python-multipart` CVE 下限バンプ、新規 MCP ツール5つ接続（`analyze_trade_journal` + シャドウアカウント系4つ）、`pattern_recognition` → `pattern` レジストリ名の不一致を修正、Docker 依存を本体に合わせる、SKILL マニフェスト同期（22 MCP ツール / 71 スキル）。
- **2026-04-18** 👥 **シャドウアカウント Shadow Account**: ブローカーの取引明細から自分の戦略ルールを抽出 → マーケット横断でシャドウをバックテスト → 8セクションのHTML/PDFレポートが、どこでいくら取りこぼしたか（ルール違反・早すぎる利確・見逃したシグナル・逆張り）を正確に可視化。新規ツール4つ、新スキル1つ、合計32ツール。Trade Journal / Shadow Accountのサンプル例文がWeb UIウェルカム画面に追加。
- **2026-04-17** 📊 **取引明細アナライザー + ユニバーサルファイルリーダー**: ブローカーの取引明細（同花順/東方財富/富途/汎用CSV）をアップロード → 取引プロフィール（保有日数、勝率、損益比、最大ドローダウン）+ 4つの行動バイアス診断（処分効果、過剰取引、追随買い、アンカリング）を自動生成。`read_document`はPDF、Word、Excel、PowerPoint、画像（OCR）、40+テキスト形式を1回の呼び出しで統一処理。
- **2026-04-16** 🧠 **エージェントハーネス**: クロスセッション永続メモリ、FTS5セッション検索、自己進化スキル（完全CRUD）、5層コンテキスト圧縮、読み書きツールバッチ処理。27ツール、107新テスト。
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.aiプロバイダー追加（[#35](https://github.com/HKUDS/Vibe-Trading/pull/35)）、MiniMax temperature修正+モデル更新（[#33](https://github.com/HKUDS/Vibe-Trading/pull/33)）。13プロバイダー対応。
- **2026-04-14** 🔧 **MCP安定性**: バックテストツールのstdioトランスポートにおける`Connection closed`エラーを修正（[#32](https://github.com/HKUDS/Vibe-Trading/pull/32)）。
- **2026-04-13** 🌐 **クロスマーケット複合バックテスト**: 新`CompositeEngine`で異なる市場の銘柄（例：A株＋暗号資産）を共有資金プールで同時バックテスト、市場ルールは銘柄ごとに適用。Swarmテンプレート変数フォールバックとフロントエンドタイムアウトも修正。
- **2026-04-12** 🌍 **マルチプラットフォーム出力**: `/pine`でTradingView (Pine Script v6)、TDX（通達信/同花順/東方財富）、MetaTrader 5 (MQL5) に一括エクスポート。
- **2026-04-11** 🛡️ **信頼性とDX**: `vibe-trading init` .envブートストラップ（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)）、プリフライトチェック、データソースフォールバック、バックテストエンジン強化。多言語README（[#21](https://github.com/HKUDS/Vibe-Trading/pull/21)）。
- **2026-04-10** 📦 **v0.1.4**: Docker修正（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)）、`web_search` MCPツール、12 LLMプロバイダー、`akshare`/`ccxt`依存追加。PyPIとClawHubに公開。
- **2026-04-09** 📊 **Backtest Wave 2**: ChinaFutures、GlobalFutures、Forex、Options v2エンジン追加。モンテカルロ、Bootstrap CI、ウォークフォワード検証。
- **2026-04-08** 🔧 **マルチマーケットバックテスト**: 市場別ルール、Pine Script v6エクスポート、自動フォールバック付き5データソース。

</details>

---

## 💡 Vibe-Tradingとは？

Vibe-Tradingは、自然言語リクエストをグローバル市場向けの実行可能なトレーディング戦略、リサーチ洞察、ポートフォリオ分析へと変換する、AI駆動のマルチエージェント金融ワークスペースです。

### 主な能力:
• **自然言語 → 戦略** — アイデアを記述するだけ、エージェントがコードの作成・テスト・エクスポートを実行<br>
• **5データソース、ゼロ設定** — A株、HK/US、暗号、先物、FX対応、自動フォールバック<br>
• **29の専門チーム** — 投資・トレーディング・リスク向けマルチエージェントスウォームワークフロー<br>
• **クロスセッションメモリ** — ユーザーの好みやインサイトを記憶し、再利用可能なスキルを自動生成・進化<br>
• **7つのバックテストエンジン** — クロスマーケット複合テスト + 統計検証 + 4種オプティマイザー<br>
• **マルチプラットフォームエクスポート** — ワンクリックでTradingView、TDX、MetaTrader 5へ

---

## ✨ 主な機能

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="Research"/><br>
      <h3>🔍 トレーディング向けDeepResearch</h3>
      <img src="https://img.shields.io/badge/72_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="Skills" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 72の専門スキル + クロスセッション永続メモリ<br>
        • 自己進化: エージェントが経験からワークフローを構築・改善<br>
        • 5層コンテキスト圧縮 — 長い会話でも情報損失なし<br>
        • 全金融ドメインにわたる自然言語タスクルーティング
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="Swarm"/><br>
      <h3>🐝 スウォームインテリジェンス</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="Swarm" /><br><br>
      <div align="left">
        • 即戦力の29種トレーディングチームプリセット<br>
        • DAGベースのマルチエージェントオーケストレーション<br>
        • リアルタイムストリーミングダッシュボード（エージェントステータス表示）<br>
        • FTS5クロスセッション検索で過去の全会話を横断検索
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

## 7カテゴリにわたる72スキル

- 📊 72の金融特化スキルを7カテゴリに整理
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

### 🎯 推奨モデル

Vibe-Tradingはツール呼び出しに大きく依存するエージェントです — skill・バックテスト・メモリ・swarmはすべてtool callで動作します。モデル選択が、エージェントが**実際にツールを使う**か、訓練データから答えを捏造するかを直接決定します。

| 層 | 例 | 用途 |
|----|-----|------|
| **ベスト** | `anthropic/claude-opus-4.7`、`anthropic/claude-sonnet-4.6`、`openai/gpt-5.4`、`google/gemini-3.1-pro-preview` | 複雑なswarm（3+エージェント）、長い研究セッション、論文レベル分析 |
| **コスパ**（デフォルト） | `deepseek/deepseek-v3.2`、`x-ai/grok-4.20`、`z-ai/glm-5.1`、`moonshotai/kimi-k2.5`、`qwen/qwen3-max-thinking` | 日常利用 — tool-callingが安定、コスト約1/10 |
| **エージェント用途では非推奨** | `*-nano`、`*-flash-lite`、`*-coder-next`、小型 / 蒸留版 | tool-callingが不安定 — skillのロードやbacktest実行をせず「記憶で回答」してしまう |

デフォルトの `agent/.env.example` は `deepseek/deepseek-v3.2` — コスパ層の最安オプション。

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
| `/skills` | 72の金融スキルを一覧表示 |
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

Vibe-Tradingは、あらゆるMCP互換クライアント向けに22のMCPツールを提供します。stdioサブプロセスとして実行 — サーバーセットアップ不要。**22中21ツールはAPIキー不要**（HK/US/暗号）。`run_swarm`のみLLMキーが必要。

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

**公開MCPツール（22）:** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`。

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

全72金融スキルは[open-space.cloud](https://open-space.cloud)に公開され、OpenSpaceの自己進化エンジンで自律的に進化します。

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

OpenSpaceが全72スキルを自動検出し、auto-fix/auto-improve/コミュニティ共有を有効化。`search_skills("finance backtest")`でVibe-Tradingスキルを検索可能。

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
│   ├── mcp_server.py               # MCPサーバー — OpenClaw / Claude Desktop向け22ツール
│   │
│   ├── src/
│   │   ├── agent/                  # ReActエージェントコア
│   │   │   ├── loop.py             #   5層圧縮 + 読み書きツールバッチ処理
│   │   │   ├── context.py          #   システムプロンプト + 永続メモリからの自動リコール
│   │   │   ├── skills.py           #   スキルローダー（72バンドル + ユーザーCRUD作成）
│   │   │   ├── tools.py            #   ツール基底クラス + レジストリ
│   │   │   ├── memory.py           #   実行ごとの軽量ワークスペースステート
│   │   │   ├── frontmatter.py      #   共有YAMLフロントマターパーサー
│   │   │   └── trace.py            #   実行トレースライター
│   │   │
│   │   ├── memory/                 # クロスセッション永続メモリ
│   │   │   └── persistent.py       #   ファイルベースメモリ (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 27の自動検出エージェントツール
│   │   │   ├── backtest_tool.py    #   バックテスト実行
│   │   │   ├── remember_tool.py    #   クロスセッションメモリ (保存/リコール/削除)
│   │   │   ├── skill_writer_tool.py #  スキルCRUD (保存/パッチ/削除/ファイル)
│   │   │   ├── session_search_tool.py # FTS5クロスセッション検索
│   │   │   ├── swarm_tool.py       #   スウォームチーム起動
│   │   │   ├── web_search_tool.py  #   DuckDuckGoウェブ検索
│   │   │   └── ...                 #   bash, ファイルI/O, ファクター分析, オプション等
│   │   │
│   │   ├── skills/                 # 7カテゴリに渡る72金融スキル (各SKILL.md)
│   │   ├── swarm/                  # スウォームDAG実行エンジン
│   │   │   └── presets/            #   29のスウォームプリセットYAML定義
│   │   ├── session/                # マルチターンチャット + FTS5セッション検索
│   │   └── providers/              # LLMプロバイダー抽象化
│   │
│   └── backtest/                   # バックテストエンジン
│       ├── engines/                #   7エンジン + クロスマーケット複合エンジン + options_portfolio
│       ├── loaders/                #   6ソース: tushare, okx, yfinance, akshare, ccxt, futu
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   レジストリ + 自動フォールバックチェーン
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
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
| **Agent Harness** | クロスセッション永続メモリ（保存/リコール/削除） | **Done** |
| | 自己進化スキル — エージェントが自らワークフローを作成・修正・削除 | **Done** |
| | FTS5クロスセッション検索（過去の全会話を横断） | **Done** |
| | 5層コンテキスト圧縮（micro → collapse → auto → manual → iterative） | **Done** |
| | 読み書きツールバッチ処理 — 読み取り専用ツールの並列実行 | **Done** |
| **Next Up** | 自律リサーチループ — エージェントが仮説を一晩中反復 | In Progress |
| | IM統合（Slack / Telegram / WeChat） | Planned |
| **Analysis & Viz** | オプションボラティリティサーフェスとギリシャ値3D可視化 | Planned |
| | ローリングウィンドウ＋クラスタリングによるクロスアセット相関ヒートマップ | Planned |
| | CLIバックテスト出力でのベンチマーク比較 | Planned |
| **Skills & Presets** | 配当分析スキル | Planned |
| | ESG/サステナブル投資スウォームプリセット | Planned |
| **Portfolio & Optimization** | レバレッジ・セクター上限・回転率制約付き高度ポートフォリオオプティマイザー | Planned |
| **Future** | ストラテジーマーケットプレイス（共有・発見） | Exploring |
| | WebSocket経由のライブデータストリーミング | Exploring |

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

## スター履歴

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  <b>Vibe-Trading</b>への訪問に感謝 ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
