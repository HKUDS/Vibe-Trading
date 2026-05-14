<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: あなた専用のトレーディングエージェント</h1>

<p align="center">
  <b>1つのコマンドで、包括的なトレーディング能力をエージェントに付与</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="License"></a>
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-ニュース">ニュース</a> &nbsp;&middot;&nbsp;
  <a href="#-主な機能">機能</a> &nbsp;&middot;&nbsp;
  <a href="#-shadow-account">Shadow Account</a> &nbsp;&middot;&nbsp;
  <a href="#-デモ">デモ</a> &nbsp;&middot;&nbsp;
  <a href="#-クイックスタート">クイックスタート</a> &nbsp;&middot;&nbsp;
  <a href="#-例">例</a> &nbsp;&middot;&nbsp;
  <a href="#-api-サーバー">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-ロードマップ">ロードマップ</a> &nbsp;&middot;&nbsp;
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="#-クイックスタート"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 ニュース

- **2026-05-14** 🧠 永続メモリを CLI から `vibe-trading memory list/show/search/forget` で確認できるようになりました（[#102](https://github.com/HKUDS/Vibe-Trading/pull/102)、@Teerapat-Vatpitak に感謝）。
- **2026-05-13** 🧭 Swarm 実行では、取得済みの市場データでワーカーを grounding し、永続化レポートもより整理されました（[#93](https://github.com/HKUDS/Vibe-Trading/pull/93)、[#84](https://github.com/HKUDS/Vibe-Trading/pull/84)）。
- **2026-05-12** 🧾 バックテストは、再現可能なリサーチ実行のために artifacts と並んで `run_card.json` と `run_card.md` を出力するようになりました。

<details>
<summary>過去のニュース</summary>

- **2026-05-11** 🧭 **メモリ slug、swarm 集計、CLI プリフライト**: 永続メモリのファイル slug 生成で CJK 文字を保持するようになり、中国語/日本語/韓国語ノートの静かなファイル名衝突を防ぎます（[#95](https://github.com/HKUDS/Vibe-Trading/pull/95)、@voidborne-d に感謝）。Swarm run の合計は provider が返す token usage を優先し、従来の推定フォールバックも維持します（[#94](https://github.com/HKUDS/Vibe-Trading/pull/94)、@Teerapat-Vatpitak に感謝）。CLI run UI には一般的な環境問題を早めに見つける起動時プリフライトチェックも入りました（[#96](https://github.com/HKUDS/Vibe-Trading/pull/96)、@ykykj に感謝）。
- **2026-05-10** 🧱 **回帰ガードレール + run メタデータ**: Memory recall はアンダースコアを token 境界として扱うようになり、`mcp_wiring_test` のような snake_case の保存メモリが "mcp wiring" のような自然言語クエリに一致します（[#87](https://github.com/HKUDS/Vibe-Trading/pull/87)、@hp083625 に感謝）。MCP server には initialize → `tools/list` → `tools/call` を通す subprocess smoke test を追加し、初回呼び出し deadlock 経路の回帰を防ぎます（[#86](https://github.com/HKUDS/Vibe-Trading/pull/86)）。さらに Windows のパス依存テスト、API の best-effort 例外処理、backtest `run_dir` allowed-root 検証、SwarmRun provider/model メタデータの低リスク強化も入りました（[#88](https://github.com/HKUDS/Vibe-Trading/pull/88)、[#90](https://github.com/HKUDS/Vibe-Trading/pull/90)、[#91](https://github.com/HKUDS/Vibe-Trading/pull/91)、[#92](https://github.com/HKUDS/Vibe-Trading/pull/92)、@Teerapat-Vatpitak に感謝）。
- **2026-05-09** 🛡️ **API パス強化 + MCP server 安定化**: API の run/session ルートは参照前にパス ID を検証し、改行を含む不正なパラメータを拒否し、その挙動を auth/security 回帰テストで固定しました（[#80](https://github.com/HKUDS/Vibe-Trading/pull/80)、@SJoon99 に感謝）。MCP server は `tools/call` を処理する前にメインスレッドでツールレジストリを事前ウォームアップし、lazy tool discovery の初回呼び出しデッドロックを回避します（[#85](https://github.com/HKUDS/Vibe-Trading/pull/85)、@Teerapat-Vatpitak に感謝）。Vite dev proxy も `VITE_API_URL` を尊重し、非デフォルトのバックエンドターゲットを使えるようになりました（[#82](https://github.com/HKUDS/Vibe-Trading/pull/82)、@voidborne-d に感謝）。
- **2026-05-08** 🧾 **Tushare 財務諸表フィールドをフィルターへ**: A 株の日次バックテストで `fundamental_fields` から PIT-safe な財務諸表フィールドを要求できるようになり、signal engine は公告/開示日以降に `income_total_revenue`、`income_n_income`、`balancesheet_total_hldr_eqy_exc_min_int`、`fina_indicator_roe` など表名プレフィックス付き列でスクリーニングできます（[#76](https://github.com/HKUDS/Vibe-Trading/pull/76)、@mrbob-git に感謝）。後続の強化により、明示的な財務諸表フィールド要求で Tushare enrichment が失敗した場合は、価格バーだけに静かに戻るのではなく即時失敗します（[#77](https://github.com/HKUDS/Vibe-Trading/pull/77)）。
- **2026-05-07** 📈 **Tushare fundamentals + コミュニティ整理**: ファンダメンタル調査ワークフロー向けに point-in-time の `TushareFundamentalProvider` 契約を追加し、プロジェクトの `TUSHARE_TOKEN` 環境変数パスを回帰テストでカバーしました（[#74](https://github.com/HKUDS/Vibe-Trading/pull/74)）。コミュニティ整理では、Vibe-Trading は当面 UI を単一言語に絞って高速反復すること、DuckDuckGo ベースの `web_search` が既に同梱されているため重複する検索依存を追加しないこと、非公式ホスト先は API key やデータソース token を入力する信頼済み場所として扱わないことも明確にしました。
- **2026-05-06** 🚀 **v0.1.7 リリース**（[Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7)、`pip install -U vibe-trading-ai`）: セキュリティ境界強化版を PyPI と ClawHub に公開しました。API/読み取り/アップロード/ファイル/URL/生成コード/shell ツール/Docker の既定境界をより安全にしつつ、localhost の CLI/Web UI ワークフローは低摩擦のままです。このサイクルには Web UI Settings、相関ヒートマップ、OpenAI Codex OAuth、A 株 pre-ST フィルター、対話型 CLI UX、swarm preset inspection、配当分析、開発ワークフロー改善、frontend build-dependency floor の監査も含まれます。0.1.7 のコントリビューターと、協調的なセキュリティ検証を行った lemi9090 (S2W) に感謝します。
- **2026-05-05** 🛡️ **セキュリティ境界の追加強化**: 明示的な CORS origins、Settings の認証情報表示、Web URL 読み取り、Shadow Account コード生成まわりの残りのセキュリティ境界を補強し、それぞれに回帰テストを追加しました。通常の localhost CLI/Web UI ワークフローは従来どおりです。リモートデプロイでは引き続き `API_AUTH_KEY` と明示的な信頼済み origins を設定してください。
- **2026-05-04** 🖥️ **インタラクティブ CLI UX + CI 整理**: インタラクティブモードに、provider/model、セッション時間、直近実行時間、累計ツール呼び出し統計を表示するライブ下部ステータスバーを追加。さらに `prompt_toolkit` により上下キーの履歴移動と左右キーのカーソル編集に対応しました（[#69](https://github.com/HKUDS/Vibe-Trading/pull/69)）。`prompt_toolkit` または TTY が利用できない場合は、従来どおり Rich prompt にフォールバックします。CI のパス期待値も強化済みファイル import サンドボックスとクロスプラットフォームな `/tmp` 解決に合わせ、main はグリーンに戻りました（[`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)）。
- **2026-05-03** 🛡️ **セキュリティハードニングパッチ**: 非ローカルデプロイ向けの既定 API 認証を強化し、機密性の高い run/session/swarm 読み取りを保護、アップロードとローカルファイル読み取り境界を制限、shell 系ツールをエントリーポイント別に制御、生成戦略を import 前に検証し、Docker イメージは既定で非 root ユーザーかつ localhost 限定ポート公開で動作します。ローカル CLI と localhost Web UI は低摩擦のままです。リモート API/Web デプロイでは `API_AUTH_KEY` を設定してください。
- **2026-05-02** 🧭 **配当分析 + ロードマップ刷新**: インカム株、配当の持続性、増配、株主還元利回り、権利落ちメカニクス、利回りの罠チェックに対応する `dividend-analysis` skill を追加し、bundled-skill 回帰テストで固定しました。公開ロードマップは Research Autopilot、Data Bridge、Options Lab、Portfolio Studio、Alpha Zoo、Research Delivery、Trust Layer、Community 共有に絞りました。
- **2026-05-01** 🔥 **相関ヒートマップ + OpenAI Codex OAuth + A 株 pre-ST フィルター**: 新しい相関ダッシュボード/APIでローリングリターン相関を計算し、ポートフォリオや銘柄分析向けに ECharts ヒートマップで可視化します（[#64](https://github.com/HKUDS/Vibe-Trading/pull/64)）。OpenAI Codex provider は `vibe-trading provider login openai-codex` による ChatGPT OAuth に対応し、Settings メタデータとアダプター回帰テストも追加（[#65](https://github.com/HKUDS/Vibe-Trading/pull/65)）。A 株の ST/*ST リスクスクリーニング用 `ashare-pre-st-filter` skill を追加・強化し、Sina 処分公告の関連性フィルターにより証券口座リスト内の言及が E2 回数を水増ししないようにしました（[#63](https://github.com/HKUDS/Vibe-Trading/pull/63)）。
- **2026-04-30** ⚙️ **Web UI Settings + validation CLI 強化**: LLM provider/model、Base URL、reasoning effort、データソース認証情報をローカルで設定できる Settings ページを追加。settings API は local/auth で保護され、provider メタデータもデータ駆動設定に移行しました（[#57](https://github.com/HKUDS/Vibe-Trading/pull/57)）。さらに `python -m backtest.validation <run_dir>` を強化し、引数なし・空パス・不正パス・存在しないパス・ディレクトリでないパスを検証開始前に分かりやすく失敗させます（[#60](https://github.com/HKUDS/Vibe-Trading/pull/60)）。
- **2026-04-28** 🚀 **v0.1.6 リリース**（`pip install -U vibe-trading-ai`）: `pip install` / `uv tool install` 後に `vibe-trading --swarm-presets` が空を返す問題を修正（[#55](https://github.com/HKUDS/Vibe-Trading/issues/55)）。プリセット YAML は `src.swarm` パッケージ内に同梱され、6 件の回帰テストで固定されています。加えて AKShare loader が ETF（`510300.SH`）と forex（`USDCNH`）を正しい endpoint にルーティングし、registry fallback も強化しました。v0.1.5 以降の更新を集約: benchmark comparison panel、`/upload` streaming + size limits、Futu loader（HK + A 株）、vnpy export skill、security hardening、frontend lazy loading（688KB → 262KB）。
- **2026-04-27** 📊 **ベンチマーク比較パネル + アップロード安全性**: バックテスト出力に benchmark comparison panel（ticker / benchmark return / excess return / information ratio）を追加し、yfinance 経由で SPY、CSI 300 などを解決します（[#48](https://github.com/HKUDS/Vibe-Trading/issues/48)）。加えて `/upload` は request body を 1 MB chunks で stream し、`MAX_UPLOAD_SIZE` 超過時に中断するため、過大/不正な client の下でもメモリを抑えます（[#53](https://github.com/HKUDS/Vibe-Trading/pull/53)）。4 ケースの回帰テストで固定されています。
- **2026-04-22** 🛡️ **ハードニング + 新規連携**: `safe_path` でパス封じ込めを強制し、journal/shadow tool sandbox、`MANIFEST.in` による `.env.example` / tests / Docker files の sdist 同梱、route-level lazy loading による frontend 初期 bundle 688KB → 262KB を実施。さらに Futu data loader for HK & A-share equities（[#47](https://github.com/HKUDS/Vibe-Trading/pull/47)）と vnpy CtaTemplate export skill（[#46](https://github.com/HKUDS/Vibe-Trading/pull/46)）も追加しました。
- **2026-04-21** 🛡️ **Workspace + docs**: 相対 `run_dir` を active run dir に正規化しました（[#43](https://github.com/HKUDS/Vibe-Trading/pull/43)）。README usage examples も追加しました（[#45](https://github.com/HKUDS/Vibe-Trading/pull/45)）。
- **2026-04-20** 🔌 **Reasoning + Swarm**: `reasoning_content` をすべての `ChatOpenAI` path で保持し、Kimi / DeepSeek / Qwen thinking が end-to-end で動作します（[#39](https://github.com/HKUDS/Vibe-Trading/issues/39)）。Swarm streaming と clean Ctrl+C も入りました（[#42](https://github.com/HKUDS/Vibe-Trading/issues/42)）。
- **2026-04-19** 📦 **v0.1.5**: PyPI と ClawHub に公開。`python-multipart` CVE floor bump、新規 MCP tools 5 つ接続（`analyze_trade_journal` + shadow-account tools 4 つ）、`pattern_recognition` → `pattern` registry fix、Docker dep parity、SKILL manifest sync（22 MCP tools / 71 skills）。
- **2026-04-18** 👥 **Shadow Account**: broker journal から strategy rules を抽出 → market 横断で shadow を backtest → 8-section HTML/PDF report で取りこぼし（rule violations、early exits、missed signals、counterfactual trades）を正確に可視化。新規 tools 4 つ、skill 1 つ、合計 32 tools。Trade Journal + Shadow Account samples も Web UI welcome screen に追加されました。
- **2026-04-17** 📊 **Trade Journal Analyzer + Universal File Reader**: broker exports（同花順/東財/富途/generic CSV）を upload → auto trading profile（holding days、win rate、PnL ratio、drawdown）+ 4 bias diagnostics（disposition effect、overtrading、chasing momentum、anchoring）。`read_document` は PDF、Word、Excel、PowerPoint、images（OCR）、40+ text formats を 1 つの unified call に dispatch します。
- **2026-04-16** 🧠 **Agent Harness**: Persistent cross-session memory、FTS5 session search、self-evolving skills（full CRUD）、5-layer context compression、read/write tool batching。27 tools、107 new tests。
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.ai provider（[#35](https://github.com/HKUDS/Vibe-Trading/pull/35)）、MiniMax temperature fix + model update（[#33](https://github.com/HKUDS/Vibe-Trading/pull/33)）。13 providers。
- **2026-04-14** 🔧 **MCP Stability**: stdio transport 上の backtest tool `Connection closed` error を修正しました（[#32](https://github.com/HKUDS/Vibe-Trading/pull/32)）。
- **2026-04-13** 🌐 **Cross-Market Composite Backtest**: 新しい `CompositeEngine` が mixed-market portfolios（例: A-shares + crypto）を shared capital pool と per-market rules で backtest します。swarm template variable fallback と frontend timeout も修正しました。
- **2026-04-12** 🌍 **Multi-Platform Export**: `/pine` が strategies を TradingView（Pine Script v6）、TDX（通达信/同花顺/东方财富）、MetaTrader 5（MQL5）へ 1 コマンドで export します。
- **2026-04-11** 🛡️ **Reliability & DX**: `vibe-trading init` .env bootstrap（[#19](https://github.com/HKUDS/Vibe-Trading/pull/19)）、preflight checks、runtime data-source fallback、hardened backtest engine。Multi-language README（[#21](https://github.com/HKUDS/Vibe-Trading/pull/21)）。
- **2026-04-10** 📦 **v0.1.4**: Docker fix（[#8](https://github.com/HKUDS/Vibe-Trading/issues/8)）、`web_search` MCP tool、12 LLM providers、`akshare`/`ccxt` deps。PyPI と ClawHub に公開。
- **2026-04-09** 📊 **Backtest Wave 2**: ChinaFutures、GlobalFutures、Forex、Options v2 engines。Monte Carlo、Bootstrap CI、Walk-Forward validation。
- **2026-04-08** 🔧 **Multi-market backtest** with per-market rules、Pine Script v6 export、5 data sources with auto-fallback。

</details>

---

## ✨ 主な機能

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="Self-improving trading agent"/><br>
      <h3>🔍 自己改善型トレーディングエージェント</h3>
      <div align="left">
        • 自然言語による市場リサーチ<br>
        • 戦略ドラフトとファイル/Web 分析<br>
        • メモリに支えられたワークフロー
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="Multi-agent trading teams"/><br>
      <h3>🐝 マルチエージェント・トレーディングチーム</h3>
      <div align="left">
        • 投資、クオンツ、暗号資産、リスクの各チーム<br>
        • 進捗ストリーミングと永続化レポート<br>
        • 取得済み市場データで grounding されたワーカー
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="Cross-market data and backtesting"/><br>
      <h3>📊 クロスマーケットデータ & バックテスト</h3>
      <div align="left">
        • A/HK/US 株式、暗号資産、先物、FX<br>
        • データフォールバックと複合バックテスト<br>
        • PIT データ、検証、run cards
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • ブローカー取引日誌の行動診断<br>
        • ルールベースの Shadow Account 比較<br>
        • エクスポート可能な監査レポートと戦略コード
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 Vibe-Trading とは？

Vibe-Trading は、金融に関する問いを実行可能な分析へ変換するためのオープンソースのリサーチワークスペースです。自然言語プロンプトを、市場データ loader、戦略生成、バックテストエンジン、レポート、エクスポート、永続リサーチメモリへ接続します。

研究、シミュレーション、バックテストのために設計されています。ライブ取引は実行しません。

---

## ✨ できること

| タスク | 出力 |
|------|--------|
| **トレーディングの問いを投げる** | ツール、データ、ドキュメント、再利用可能なセッション文脈を使った市場リサーチ。 |
| **戦略アイデアをバックテストする** | 戦略コード、指標、ベンチマーク文脈、検証 artifacts、run cards。 |
| **自分の取引をレビューする** | ブローカー取引日誌の解析、行動診断、ルール抽出、Shadow Account 比較。 |
| **反復リサーチを改善する** | 永続メモリと編集可能な skills により、有用な手順を再利用可能なワークフローへ変換。 |
| **アナリストチームを走らせる** | 投資、クオンツ、暗号資産、マクロ、リスクのワークフロー向けマルチエージェント・リサーチレビュー。 |
| **使える artifacts を出力する** | レポート、TradingView Pine Script、TDX、MetaTrader 5、MCP tools、後続リサーチセッション。 |

---

## ⚡ クイック例

```bash
pip install vibe-trading-ai
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 👥 Shadow Account

Shadow Account は、汎用的な戦略テンプレートではなく、あなた自身の取引記録から始めます。

ブローカー export をアップロードし、エージェントに行動を要約させたうえで、実際の取引経路をルールベースの shadow strategy と比較します。

| ステップ | エージェントの出力 |
|------|--------------|
| **1. 取引日誌を読む** | 同花順、东方财富、富途、generic CSV 形式のブローカー export を解析します。 |
| **2. 行動をプロファイルする** | 保有日数、勝率、PnL ratio、drawdown、disposition effect、overtrading、momentum chasing、anchoring checks。 |
| **3. ルールを抽出する** | 繰り返し現れる entries/exits を、曖昧な要約ではなく明示的な strategy profile に変換します。 |
| **4. shadow を実行する** | 抽出したルールをバックテストし、rule breaks、early exits、missed signals、alternative trade paths を強調します。 |
| **5. レポートを届ける** | 後から確認、アーカイブ、または次回セッションで改善できる HTML/PDF report を生成します。 |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 🧪 リサーチワークフロー

多くの実行は、同じ evidence path をたどります。リクエストを routing し、適切な市場文脈を読み込み、ツールを実行し、出力を検証し、artifacts を確認可能な形で残します。

| レイヤー | 何が起きるか |
|-------|--------------|
| **Plan** | 必要な finance skills、tools、data sources、必要に応じて swarm preset を選びます。 |
| **Ground** | A 株、HK/US 株式、暗号資産、先物、FX、documents、Web context を利用可能な loaders から取得します。 |
| **Execute** | テスト可能な strategy code を生成し、tools を実行し、対応する backtest engine または analysis workflow を使います。 |
| **Validate** | metrics、benchmark comparison、Monte Carlo、Bootstrap、Walk-Forward、run cards、必要な warnings を追加します。 |
| **Deliver** | TradingView、TDX、MetaTrader 5、MCP clients、後続セッション向けの reports、artifacts、tool traces、exports を返します。 |

---

## 🔩 詳細な機能

メイン README を読みやすく保つため、詳細な一覧は以下に折りたたんでいます。利用できる構成要素を確認したいときに開いてください。

<details>
<summary><b>Finance Skill Library</b> <sub>8カテゴリにわたる74 skills</sub></summary>

- 📊 74 の金融特化 skills を 8 カテゴリに整理
- 🌐 伝統的市場から crypto & DeFi まで完全カバー
- 🔬 データ取得からクオンツリサーチまでを横断する包括的能力

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| Strategy | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 17 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>Preset Trading Teams</b> <sub>29 swarm presets</sub></summary>

- 🏢 すぐ使える 29 の agent teams
- ⚡ 事前構成済みの finance workflows
- 🎯 投資、トレーディング、リスク管理向け presets

| Preset | Workflow |
|--------|----------|
| `investment_committee` | Bull/bear debate → risk review → PM final call |
| `global_equities_desk` | A-share + HK/US + crypto researcher → global strategist |
| `crypto_trading_desk` | Funding/basis + liquidation + flow → risk manager |
| `earnings_research_desk` | Fundamental + revision + options → earnings strategist |
| `macro_rates_fx_desk` | Rates + FX + commodity → macro PM |
| `quant_strategy_desk` | Screening + factor research → backtest → risk audit |
| `technical_analysis_panel` | Classic TA + Ichimoku + harmonic + Elliott + SMC → consensus |
| `risk_committee` | Drawdown + tail risk + regime review → sign-off |
| `global_allocation_committee` | A-shares + crypto + HK/US → cross-market allocation |

<sub>さらに 20 以上の specialist presets があります。すべて確認するには vibe-trading --swarm-presets を実行してください。

</sub>

</details>

## 🎬 デモ

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
<td colspan="2" align="center"><sub>☝️ 自然言語バックテスト & マルチエージェント swarm debate — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 クイックスタート

### 1行インストール（PyPI）

```bash
pip install vibe-trading-ai
```

最初のリサーチタスクを実行します。

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **Package name vs commands:** PyPI package は `vibe-trading-ai` です。インストール後、3 つのコマンドが使えます。
>
> | Command | Purpose |
> |---------|---------|
> | `vibe-trading` | Interactive CLI / TUI |
> | `vibe-trading serve` | FastAPI web server を起動 |
> | `vibe-trading-mcp` | MCP server を起動（Claude Desktop、OpenClaw、Cursor など向け） |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### または利用経路を選ぶ

| Path | Best for | Time |
|------|----------|------|
| **A. Docker** | すぐ試す、ローカル設定ゼロ | 2 min |
| **B. Local install** | 開発、CLI へのフルアクセス | 5 min |
| **C. MCP plugin** | 既存 agent へ接続 | 3 min |
| **D. ClawHub** | clone 不要、1 コマンド | 1 min |

### 前提条件

- 対応 provider の **LLM API key**、または **Ollama** によるローカル実行（key 不要）
- Path B では **Python 3.11+**
- Path A では **Docker**
- OpenAI Codex は ChatGPT OAuth でも利用できます。`LANGCHAIN_PROVIDER=openai-codex` を設定し、`vibe-trading provider login openai-codex` を実行してください。`OPENAI_API_KEY` は使いません。

> **Supported LLM providers:** OpenRouter、OpenAI、OpenAI Codex（ChatGPT OAuth）、Anthropic Claude、DeepSeek、Gemini、Groq、DashScope/Qwen、Zhipu、Moonshot/Kimi、MiniMax、Xiaomi MIMO、Z.ai、Ollama（local）。設定は `.env.example` を参照してください。

> **Tip:** 自動フォールバックにより、すべての市場は API key なしで利用できます。yfinance（HK/US）、OKX（crypto）、AKShare（A-shares、US、HK、futures、forex）はすべて無料です。Tushare token は任意で、A-shares は AKShare が無料 fallback としてカバーします。

### Path A: Docker（設定ゼロ）

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

`http://localhost:8899` を開きます。Backend + frontend が 1 つの container で動作します。

Docker は既定で backend を `127.0.0.1:8899` に公開し、app を non-root container user として実行します。意図して API を自分の machine 外へ公開する場合は、強い `API_AUTH_KEY` を設定し、client から `Authorization: Bearer <key>` を送ってください。

### Path B: Local install

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# Activate
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

<details>
<summary><b>Web UI を起動（任意）</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev
```

`http://localhost:5899` を開きます。frontend は API calls を `localhost:8899` へ proxy します。

**Production mode（single server）:**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

</details>

### Path C: MCP plugin

下の [MCP Plugin](#-mcp-plugin) セクションを参照してください。

### Path D: ClawHub（1 コマンド）

```bash
npx clawhub@latest install vibe-trading --force
```

skill + MCP config が agent の skills directory にダウンロードされます。詳細は [ClawHub install](#-mcp-plugin) を参照してください。

---

## 🧠 環境変数

`agent/.env.example` を `agent/.env` にコピーし、使いたい provider block のコメントを外してください。各 provider には 3-4 個の変数が必要です。

| Variable | Required | Description |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | Yes | Provider name（`openrouter`, `deepseek`, `groq`, `ollama` など） |
| `<PROVIDER>_API_KEY` | Yes* | API key（`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` など） |
| `<PROVIDER>_BASE_URL` | Yes | API endpoint URL |
| `LANGCHAIN_MODEL_NAME` | Yes | Model name（例: `deepseek-v4-pro`） |
| `TUSHARE_TOKEN` | No | A-share data 用 Tushare Pro token（AKShare に fallback） |
| `TIMEOUT_SECONDS` | No | LLM call timeout、既定 120s |
| `API_AUTH_KEY` | Recommended for network deployments | API が非ローカル client から到達可能な場合に必要な Bearer token |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | No | remote API/MCP-SSE style deployments で shell-capable tools を明示 opt-in |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | No | document と broker-journal imports 用の追加 comma-separated roots |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | No | generated-code run directories 用の追加 comma-separated roots |

<sub>* Ollama は API key 不要です。OpenAI Codex は ChatGPT OAuth を使い、tokens は `agent/.env` ではなく `oauth-cli-kit` 経由で保存します。</sub>

**無料データ（key 不要）:** AKShare による A-shares、yfinance による HK/US equities、OKX による crypto、CCXT による 100+ crypto exchanges。システムは各市場に最適な利用可能 source を自動選択します。

### 🎯 推奨モデル

Vibe-Trading は tool-heavy agent です。skills、backtests、memory、swarms はすべて tool calls を通じて流れます。モデル選択は、agent が実際に *tools を使う* か、training data から作り話をするかを直接左右します。

| Tier | Examples | When to use |
|------|----------|-------------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.4`, `google/gemini-3.1-pro-preview` | 複雑な swarms（3+ agents）、長い research sessions、paper-grade analysis |
| **Sweet spot** (default) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.5`, `qwen/qwen3-max-thinking` | 日常使い。信頼できる tool-calling を約 1/10 の cost で |
| **Avoid for agent use** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | Tool-calling が不安定です。agent は skills 読み込みや backtests 実行ではなく「記憶から答えている」ように見えます |

既定の `agent/.env.example` は DeepSeek official API + `deepseek-v4-pro` で出荷されています。OpenRouter users は `deepseek/deepseek-v4-pro` を利用できます。

---

## 🖥 CLI リファレンス

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
```

<details>
<summary><b>TUI 内の slash commands</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | 全コマンドを表示 |
| `/skills` | 74 finance skills を一覧表示 |
| `/swarm` | 29 swarm team presets を一覧表示 |
| `/swarm run <preset> [vars_json]` | live streaming で swarm team を実行 |
| `/swarm list` | Swarm run history |
| `/swarm show <run_id>` | Swarm run details |
| `/swarm cancel <run_id>` | 実行中の swarm をキャンセル |
| `/list` | Recent runs |
| `/show <run_id>` | Run details + metrics |
| `/code <run_id>` | 生成された strategy code |
| `/pine <run_id>` | indicators を export（TradingView + TDX + MT5） |
| `/trace <run_id>` | Full execution replay |
| `/continue <run_id> <prompt>` | 新しい指示で run を継続 |
| `/sessions` | Chat sessions を一覧表示 |
| `/settings` | Runtime config を表示 |
| `/clear` | 画面をクリア |
| `/quit` | 終了 |

</details>

<details>
<summary><b>Single run & flags</b></summary>

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
vibe-trading --pine <run_id>           # Export indicators (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "refine the strategy"
vibe-trading --upload report.pdf
```

</details>

---

## 💡 例

### Strategy & Backtesting

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

### Market Research

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm Workflows

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"topic": "Is TSLA a buy at current levels?"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'
```

### Cross-Session Memory

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analyze Documents

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 API サーバー

```bash
vibe-trading serve --port 8899
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/runs` | runs を一覧表示 |
| `GET` | `/runs/{run_id}` | run details |
| `GET` | `/runs/{run_id}/pine` | Multi-platform indicator export |
| `POST` | `/sessions` | session を作成 |
| `POST` | `/sessions/{id}/messages` | message を送信 |
| `GET` | `/sessions/{id}/events` | SSE event stream |
| `POST` | `/upload` | PDF/file をアップロード |
| `GET` | `/swarm/presets` | swarm presets を一覧表示 |
| `POST` | `/swarm/runs` | swarm run を開始 |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE stream |
| `GET` | `/settings/llm` | Web UI LLM settings を読み取り |
| `PUT` | `/settings/llm` | local LLM settings を更新 |
| `GET` | `/settings/data-sources` | local data source settings を読み取り |
| `PUT` | `/settings/data-sources` | local data source settings を更新 |

Interactive docs: `http://localhost:8899/docs`

### Security defaults

localhost 開発では、`vibe-trading serve` は browser workflow を簡単に保ちます。非ローカル client では、sensitive API endpoints に `API_AUTH_KEY` が必要です。JSON/upload requests には `Authorization: Bearer <key>` を使ってください。Browser EventSource streams は、Settings で同じ key を一度入力した後、Web UI が処理します。

Shell-capable tools は local CLI と trusted localhost workflows で利用できますが、`VIBE_TRADING_ENABLE_SHELL_TOOLS=1` を明示的に設定しない限り remote API sessions には公開されません。Document と journal readers は既定で upload/import roots に制限されます。ファイルは `agent/uploads`、`agent/runs`、`./uploads`、`./data`、`~/.vibe-trading/uploads`、`~/.vibe-trading/imports` の下に置くか、`VIBE_TRADING_ALLOWED_FILE_ROOTS` で専用 directory を追加してください。

### Web UI Settings

Web UI Settings page では、local users が LLM provider/model、base URL、generation parameters、reasoning effort、Tushare token など任意の market data credentials を更新できます。Settings は `agent/.env` に永続化され、provider defaults は `agent/src/providers/llm_providers.json` から読み込まれます。

Settings reads は side-effect free です。`GET /settings/llm` と `GET /settings/data-sources` は `agent/.env` を作成せず、project-relative paths だけを返します。Settings の読み書きは credential state の公開や credentials/runtime environment の更新を伴うため、設定済みの場合は `API_AUTH_KEY` が必要です。dev mode で `API_AUTH_KEY` が未設定の場合、settings access は loopback clients からのみ受け付けます。

---

## 🔌 MCP Plugin

Vibe-Trading は MCP-compatible client 向けに 22 MCP tools を公開します。stdio subprocess として動作し、server setup は不要です。**22 tools のうち 21 tools は API key なしで動作します**（HK/US/crypto）。LLM key が必要なのは `run_swarm` のみです。

<details>
<summary><b>Claude Desktop</b></summary>

`claude_desktop_config.json` に追加:

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

`~/.openclaw/config.yaml` に追加:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / other MCP clients</b></summary>

```bash
vibe-trading-mcp                  # stdio (default)
vibe-trading-mcp --transport sse  # SSE for web clients
```

</details>

**公開される MCP tools（22）:** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

<details>
<summary><b>ClawHub からインストール（1 コマンド）</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` が必要なのは、skill が external APIs を参照し、VirusTotal の automated scan が起動するためです。コードは完全に open-source で、自由に確認できます。

これにより skill + MCP config が agent の skills directory にダウンロードされます。clone は不要です。

ClawHub で見る: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — self-evolving skills</b></summary>

74 の finance skills はすべて [open-space.cloud](https://open-space.cloud) に公開され、OpenSpace の self-evolution engine を通じて自律的に進化します。

OpenSpace と使うには、agent config に両方の MCP servers を追加してください。

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

OpenSpace は 74 skills を自動検出し、auto-fix、auto-improve、community sharing を可能にします。OpenSpace-connected agent では `search_skills("finance backtest")` から Vibe-Trading skills を検索できます。

</details>

---

## 📁 プロジェクト構成

<details>
<summary><b>クリックして展開</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli.py                      # CLI entrypoint — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 22 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (74 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 27 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, etc.
│   │   │
│   │   ├── skills/                 # 74 finance skills in 8 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   29 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   7 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   6 sources: tushare, okx, yfinance, akshare, ccxt, futu
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + auto-fallback chains
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, RunDetail, Compare
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand state management
│
├── Dockerfile                      # Multi-stage build
├── docker-compose.yml              # One-command deploy
├── pyproject.toml                  # Package config + CLI entrypoint
└── LICENSE                         # MIT
```

</details>

---

## 🏛 エコシステム

Vibe-Trading は **[HKUDS](https://github.com/HKUDS)** agent ecosystem の一部です。

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Ultra-Lightweight Personal AI Assistant</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Making All Software Agent-Native</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Self-Evolving AI Agent Skills</sub>
    </td>
  </tr>
</table>

---

## 🗺 ロードマップ

> 段階的に出荷します。作業が始まった項目は [Issues](https://github.com/HKUDS/Vibe-Trading/issues) に移動します。

| Phase | Feature | Status |
|-------|---------|--------|
| **Research Autopilot** | Overnight research loop: hypothesis → data pull → backtest → evidence report | In Progress |
| **Data Bridge** | Bring-your-own data: local CSV/Parquet/SQL connectors with schema mapping | Planned |
| **Options Lab** | Vol surface, Greeks dashboard, payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray, constraints, turnover-aware optimizer, rebalance notes | Planned |
| **Alpha Zoo** | Alpha101 / Alpha158 / Alpha191 factor libraries with screening + IC tests | Planned |
| **Research Delivery** | Scheduled briefs to Slack / Telegram / email-style channels | Planned |
| **Trust Layer** | Reproducible run cards: tool trace, data sources, assumptions, citations | In Progress |
| **Community** | Shareable skills, presets, and strategy cards | Exploring |

---

## Contributing

Contributions を歓迎します。ガイドラインは [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

**Good first issues** は [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) でタグ付けされています。気になるものから始めてください。

より大きな貢献を検討している場合は、上の [Roadmap](#-ロードマップ) を確認し、着手前に issue を開いて相談してください。

---

## Contributors

Vibe-Trading に貢献してくださった皆さまに感謝します。

最近の v0.1.7 cycle contributors and credits:

- @GTC2080 / TaoMu — Web UI Settings and provider/data-source configuration APIs (#57)
- @BigNounce90 — validation CLI hardening for backtest `run_dir` input (#60)
- @shadowinlife — A-share pre-ST filter skill (#63)
- @MB-Ndhlovu — correlation heatmap dashboard and review fixes (#64, #66)
- @ykykj — OpenAI Codex OAuth provider option (#65)
- @RuifengFu — interactive CLI live status bar and prompt editing (#69)
- @SiMinus — swarm preset inspection command (#73)
- @warren618 / Haozhe Wu — security hardening, release integration, docs, Docker, packaging, and local dev workflow
- lemi9090 (S2W) — coordinated security research, validation, and disclosure support

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## Disclaimer

Vibe-Trading は研究、シミュレーション、バックテスト専用です。投資助言ではなく、ライブ取引も実行しません。過去の成績は将来の結果を保証しません。

## License

MIT License — see [LICENSE](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  <b>Vibe-Trading</b> をご覧いただきありがとうございます ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
