<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a> | <a href="README_es.md">Español</a> | <a href="README_id.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: あなた専用のトレーディングエージェント</h1>

<p align="center">
  <b>1つのコマンドで、包括的なトレーディング能力をエージェントに付与</b>
</p>

<p align="center">
  <a href="https://www.star-history.com/HKUDS/Vibe-Trading"><img src="https://api.star-history.com/badge?repo=HKUDS/Vibe-Trading&amp;type=trending" height="55" alt="Star History: GitHub Trending"/></a>
  <a href="https://trendshift.io/repositories/25527"><img src="https://trendshift.io/api/badge/trendshift/repositories/25527/daily" height="55" alt="Trendshift: daily ranking"/></a>
  <a href="https://www.star-history.com/HKUDS/Vibe-Trading"><img src="https://api.star-history.com/badge?repo=HKUDS/Vibe-Trading" height="55" alt="Star History: global star ranking"/></a>
</p>

<p align="center">
  <b>GitHub トピック別スター数順位</b> · 2026年11月4日<br>
  <a href="https://github.com/search?q=topic%3Abacktesting&amp;type=repositories&amp;s=stars&amp;o=desc">#1 バックテスト</a> &nbsp;·&nbsp;
  <a href="https://github.com/search?q=topic%3Aalgorithmic-trading&amp;type=repositories&amp;s=stars&amp;o=desc">#3 アルゴリズム取引</a> &nbsp;·&nbsp;
  <a href="https://github.com/search?q=topic%3Aquantitative-finance&amp;type=repositories&amp;s=stars&amp;o=desc">#4 計量ファイナンス</a>
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
  <a href="https://discord.gg/6TdQnT5xcF"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="https://vibetrading.wiki/">公式サイト</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">ドキュメント</a> &nbsp;&middot;&nbsp;
  <a href="#-ニュース">ニュース</a> &nbsp;&middot;&nbsp;
  <a href="#-主な機能">主な機能</a> &nbsp;&middot;&nbsp;
  <a href="#口座と取引">シャドー口座</a> &nbsp;&middot;&nbsp;
  <a href="#-デモ">デモ</a> &nbsp;&middot;&nbsp;
  <a href="#-クイックスタート">クイックスタート</a> &nbsp;&middot;&nbsp;
  <a href="#-使用例">使用例</a> &nbsp;&middot;&nbsp;
  <a href="#-api-サーバー">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-ロードマップ">ロードマップ</a> &nbsp;&middot;&nbsp;
  <a href="#貢献者">貢献者</a>
</p>

<p align="center">
  <a href="#-クイックスタート"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

## 📰 ニュース

- **2026-11-14** 🔌 **LLM ゲートウェイの統合と更新確認** — Agent、CLI、API、Swarm のモデルプロバイダーを共通のカタログと設定層に統合しました。クライアントごとに設定を分離し、ネイティブアダプターは明示的なプロキシ設定に従います。認証情報やリクエスト本文を転送する前に、別オリジンへのリダイレクトをブロックします。
  Web の設定画面から新しいバージョンを確認できます。Desktop には署名付き更新の検証と復旧機能を追加しました。配信には更新フィードと発行者証明書の設定が必要です。**`main` に統合済み、次回の pip リリースに含まれます。**

- **2026-11-13** 🛠️ **調査結果の配信と計算ツールを刷新** — 数値の自動削除、強制書き直し、形式による完了判定を撤廃し、調査回答を直接ストリーミングします。委員会の実行が中断しても途中成果を保持し、完了済みの作業を再利用して未完了の役割を再開できます。
  全件の市場データへの参照をシェル不要の QuantLib 計算に接続し、役割間で元の証拠を共有します。Options Lab と `options_payoff` は株式とオプションの組み合わせに対応し、複数案を一度に計算・比較してコスト、損益の上下限、比較方向を返します。実効バックテスト費用、出力打ち切り・エラー状態を明示し、実取引の承認範囲と上限を維持します。**未リリース。**

- **2026-11-12** 🛠️ **バックテストの時系列、レポート数値、調査の完了判定を修正** — シャドー口座が指定された初期資金を使用し、出力トークン上限で途切れたワーカー応答を完了扱いしなくなりました。委員会の PM は有効な上流レポートを再取得なしで統合でき、ネイティブ Anthropic アダプターの既定出力枠は変更可能な 16,384 トークンです。
  生成戦略の出力目標に追加のシフトを検出した場合、意図的な遅延と明示しない限り実行を拒否します。指標の lookback は引き続き使えます。Grounding は証拠の検証を維持しつつ、金額単位の表記や正確な観測値の宣言に対応しました。SPY／GLD の実際のバックテストは、全 206／140 件の約定と総リターンで独立した帳簿計算と一致しました。**未リリース。**

<details>
<summary>過去のニュース</summary>

- **2026-11-11** 🧾 **ペーパートレードの部分約定と独立した帳簿照合** — 中国A株の5分足ペーパートレードで、注文ごとの出来高上限、部分約定、注文状態の出力を任意に有効化できます（[#2128](https://github.com/HKUDS/Vibe-Trading/pull/2128)）。新しい `paper_trade_reconcile` Agent/MCP ツールは、返された約定記録から手数料・現金・保有ポジション・純資産価値（NAV）の計算を独立して照合します（[#2197](https://github.com/HKUDS/Vibe-Trading/pull/2197)）。
  対応する複数行の百分率ヘッダーと、原文のラベルを保持した文書内の整数の明示的な引用を正しく処理します（[#2185](https://github.com/HKUDS/Vibe-Trading/pull/2185)、[#2192](https://github.com/HKUDS/Vibe-Trading/pull/2192)）。厳密な因子ベンチマークの入力も修正し（[#2195](https://github.com/HKUDS/Vibe-Trading/pull/2195)）、チャネルの応答待ちがタイムアウトした際に前のターンの回答を返さないようにしました（[#2194](https://github.com/HKUDS/Vibe-Trading/pull/2194)）。
  [@shadowinlife](https://github.com/shadowinlife)、[@he-yufeng](https://github.com/he-yufeng)、[@Jackzigen](https://github.com/Jackzigen)、[@divya0795](https://github.com/divya0795) に感謝します！**`main` に反映済みで、次の pip リリースに含まれます。**

- **2026-11-10** 📊 **編集可能な IV サーフェスとオプション分析の修正** — Options Lab で権利行使価格・満期別の IV グリッドを編集できます。観測値と補間値を区別し、外挿は拒否します（[#2186](https://github.com/HKUDS/Vibe-Trading/pull/2186)）。
  低価格銘柄のプリセット、数量入力、満期日の表示、再試行、言語切り替え時の読み込み停止、20 レッグ上限を修正。`CF501` など鄭州商品取引所の限月部分が3桁のコードは、中国先物のルールでバックテストされます（[#2193](https://github.com/HKUDS/Vibe-Trading/pull/2193)）。
  [@he-yufeng](https://github.com/he-yufeng) と [@GPT-AGI](https://github.com/GPT-AGI) に感謝します！**`main` に反映済みで、次の pip リリースに含まれます。**

- **2026-11-09** 🧭 **選択したリビジョン比較のエクスポートと、識別できないコードを拒否するバックテスト** — 比較中の2つの研究リビジョンを、Web・API・CLI から JSON または Markdown でダウンロードできます（[#2189](https://github.com/HKUDS/Vibe-Trading/pull/2189)）。どの市場ルールにも該当しないバックテストのコード（`local:BHP.AX` や `7203.T` など）は、中国A株のルールで実行されることなく、データ取得前に拒否されるようになりました。6桁のみのコードと上海の `.SS` 表記は引き続き使えます。OpenRouter の応答でモデル名が二重に表示されなくなり（[#2191](https://github.com/HKUDS/Vibe-Trading/pull/2191)）、`research-artifact export` に空のリビジョン ID を渡すとエラーになります。[@he-yufeng](https://github.com/he-yufeng) と [@Gloubiboulgator](https://github.com/Gloubiboulgator) に感謝します！**`main` に反映済みで、次回の pip リリースに含まれます。**

- **2026-11-08** 📝 **研究リビジョンの比較と全履歴のエクスポート** — 任意の2つのリビジョンの本文・根拠・メタデータを比較し（[#2168](https://github.com/HKUDS/Vibe-Trading/pull/2168)）、研究の全履歴を JSON または Markdown でエクスポートできます（[#2170](https://github.com/HKUDS/Vibe-Trading/pull/2170)）。研究記録の切り替え時には古い応答を無視し、Markdown では元の本文を独立したコードブロックに保存します。因子ウェイトの欠損、一部リターン欠損時の要因分解、IC のサンプル不足、非有限の評価入力、負のエントリー価格での証拠金計算も修正しました。**`main` に反映済みで、次回の pip リリースに含まれます。**

- **2026-11-07** 🧪 **Research Lab：取引コストとサンプル外検証** — 保存済み価格データを使い、手数料とスリッページを変えてバックテストを再実行します。訓練結果だけでパラメータを選び、固定してサンプル外テストと独立した最終ホールドアウト検証を行います。[Research Lab](guides/research-lab.md) は Web、CLI、API、Agent/MCP で同じ処理を使い、UI は全11言語に対応しています。窓の境界で欠落していたリターン、因子の初期化と長期窓の計算も修正し、証拠不足を明示するオフラインのタスク再検証ケースを20件追加しました。バージョン管理された調査記録に構造化財務データを保存できるようになり（[#2164](https://github.com/HKUDS/Vibe-Trading/pull/2164)）、取引所接尾辞のない中国先物コードの識別も修正しました（[#2177](https://github.com/HKUDS/Vibe-Trading/pull/2177)）。**`main` に反映済みで、次回の pip リリースに含まれます。**

- **2026-11-06** 📈 **インプライド・ボラティリティのグリッドとペーパー取引の修正** — 提供されたオプション観測値から権利行使価格 × 満期の IV グリッドを構築し、観測点と補間点を区別します。データ範囲外への外挿は行いません（[#2172](https://github.com/HKUDS/Vibe-Trading/pull/2172)）。極端な数値入力には有限の結果または明示的なエラーを返します。中国A株の5分足シミュレーションでは、値幅制限で約定できない成行注文を直ちに取り消します（[#2176](https://github.com/HKUDS/Vibe-Trading/pull/2176)）。銘柄をまたぐ約定処理も時刻順にし、後の売却代金で先の買い注文を賄うことを防ぎました。**`main` に反映済みで、次回の pip リリースに含まれます。公開の5分足リクエストは引き続き1ステップ1銘柄です。**

- **2026-11-05** 🚀 **v0.1.19 リリース**（[リリースノート](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.19)、`pip install -U vibe-trading-ai`）：チャットが終わっても残る調査へ。根拠付きの調査記録をバージョンごとに保存・改訂でき、以前のターンやセッションのバックテストを再利用でき、調査目標をその場で編集できます。新しいオプトイン機能：中国A株の5分刻みペーパーシミュレーション、Gildata の財務照会・銘柄抽出と Shannon のポートフォリオ診断（QVeris は削除。既存の `GILDATA_TOKEN` だけでは何も有効になりません）。ほかにアルゼンチン（BYMA）のバックテスト、Parallel ウェブ検索、Codex OAuth のモデル検出を追加し、0.1.18 の回帰 2 件をどちらも修正しました。マージ済みプルリクエスト 116 件に加え、メンテナーのコミット経由で取り込まれたものが 21 件あり、貢献者は 26 人です（[CHANGELOG](CHANGELOG.md)）。
  **本日の修正：** バックテストは実際に評価したベンチマークを報告し、ロング・ショートのポートフォリオにもリスク分析（risk x-ray）が付きます。GTJA alpha 17 は入力のウォームアップ中は欠損のまま保たれ、Shannon パネルは UI の 11 言語すべてに対応しました。レビュー済みで未取り込みだった貢献者の修正 2 件も取り込みました（[#2042](https://github.com/HKUDS/Vibe-Trading/pull/2042) 欠損四半期をまたぐ TTM 合計の修正、[#1985](https://github.com/HKUDS/Vibe-Trading/pull/1985) 3:2 株式分割の検出）。[@rudycelekli](https://github.com/rudycelekli)、[@he-yufeng](https://github.com/he-yufeng)、[@Jackzigen](https://github.com/Jackzigen)、[@Shizoqua](https://github.com/Shizoqua)、[@cgycorey](https://github.com/cgycorey)、[@dajiaohuang](https://github.com/dajiaohuang)、[@zeus229](https://github.com/zeus229)、[@alexwan02](https://github.com/alexwan02)、[@BHhhh-123](https://github.com/BHhhh-123)、[@remote-controlled-man](https://github.com/remote-controlled-man)、[@shadowinlife](https://github.com/shadowinlife)、[@TWJxi](https://github.com/TWJxi)、[@lishuanghong1989-netizen](https://github.com/lishuanghong1989-netizen)、[@TerryF7](https://github.com/TerryF7)、[@davidalmeida90](https://github.com/davidalmeida90)、[@DrDLyuan](https://github.com/DrDLyuan)、[@goatyyc](https://github.com/goatyyc)、[@hnq-ai](https://github.com/hnq-ai)、[@kadyrbekovhamit-cyber](https://github.com/kadyrbekovhamit-cyber)、[@MetaAviator](https://github.com/MetaAviator)、[@octo-patch](https://github.com/octo-patch)、[@RowanAldean](https://github.com/RowanAldean)、[@VectorPeak](https://github.com/VectorPeak)、[@wavebyrd](https://github.com/wavebyrd)、[@yufengsika](https://github.com/yufengsika) に感謝します！
  **リリース後に main で修正（次の pip リリースに含まれます）：** バックテストのベンチマークは、戦略と同じく評価期間最初の足の始値で買うようになり、ウォームアップ最後の終値からは計算しなくなりました。超過リターンにはその値動きが含まれなくなります（AAPL 20/60 SMA の例：22.5% → 18.4%）。

- **2026-11-04** 📊 **Gildataの財務照会・銘柄抽出とShannonのポートフォリオ診断** — 時価総額上位3銘柄とその半期売上高を一度に取得できます。Shannonでは10因子へのエクスポージャーと各銘柄のポートフォリオ変動への寄与を確認できます。9機能はトークン登録済みでも個別に有効化する必要があります。無料ソースからGildataへの自動切り替えはありません。 [#2117](https://github.com/HKUDS/Vibe-Trading/pull/2117) · [#2118](https://github.com/HKUDS/Vibe-Trading/pull/2118) · [#2119](https://github.com/HKUDS/Vibe-Trading/pull/2119)
  バックテストの約定が次の足の始値になることを明記し、Swarmのタイムアウト誤判定を修正しました。研究資料の重複チェックも高速化しました。 [#2137](https://github.com/HKUDS/Vibe-Trading/pull/2137) · [#2155](https://github.com/HKUDS/Vibe-Trading/pull/2155) · [#2159](https://github.com/HKUDS/Vibe-Trading/pull/2159)

- **2026-11-03** 🛠️ **記録の整合性と多言語対応**。トレース、監査台帳、会話検索の JSONL に U+2028/U+2029 が含まれても追記可能になりました。モデル名のアンダースコア表記を正規化し、第2段階の圧縮で引き継ぎ要約を保持。BOM 付きメタデータと右から左に読む言語の開始画面にも対応し、回帰テストを追加しました。

- **2026-11-02** 🛠️ **メタデータと結果表示**。引用符付きの値を正しく読み取り、大きすぎて符号化できない結果は読める長さに切り詰めます。開始画面とおすすめカードを調整し、回帰テストを追加しました。

- **2026-11-01** 🛠️ **日時と開始画面**。会話更新を UTC で記録し、ダークモードの主要ボタンの視認性を改善。サイドパネルの例を分類付きで選択できるようにし、回帰テストを追加しました。

- **2026-10-31** 🛠️ **開始画面と銘柄解析**。紙を思わせる暖色の2列表示に変更し、使用例と操作を整理。銘柄末尾の英字を中国A株やA/H指定と誤認する問題を修正しました。

[過去のニュース](guides/news.md) · [変更履歴](CHANGELOG.md)

</details>

## ✨ 主な機能

<div align="center">
<a href="assets/features/ja/feature-market-research-card.svg"><img src="assets/features/ja/feature-market-research-card.svg" width="50%" alt="🔍 市場調査 · 株価・開示資料・ETF の保有銘柄を調べる · DCF と同業他社の倍率で企業価値を評価 · 決算を追跡し、寄り付き前のレポートを予約"/></a><a href="assets/features/ja/feature-research-teams-card.svg"><img src="assets/features/ja/feature-research-teams-card.svg" width="50%" alt="🐝 調査チーム · 株式・クオンツ・暗号資産・リスクの計30チーム · 強気・弱気双方の論点とリスク評価を確認 · Pixel Office で調査を分担"/></a><br/>
<a href="assets/features/ja/feature-quant-lab-card.svg"><img src="assets/features/ja/feature-quant-lab-card.svg" width="50%" alt="📊 クオンツラボ · 5つのライブラリの478因子を比較 · 複数市場でバックテストし、標本外で検証 · オプションの損益・感応度とポートフォリオリスクを分析"/></a><a href="assets/features/ja/feature-trading-portfolio-card.svg"><img src="assets/features/ja/feature-trading-portfolio-card.svg" width="50%" alt="👥 取引とポートフォリオ · 19のブローカー接続に個別の取引権限 · 模擬約定を追跡し、対応する実取引に上限を設定 · シャドー口座で自分の売買ルールを再現"/></a>
</div>

## 💡 Vibe-Trading とは

金融に関する質問からレポート、実行可能なバックテスト、模擬ポートフォリオを作成できます。対応ブローカーには上限を定めて実取引を許可でき、いつでも停止できます。資金はブローカーの口座に留まります。

## ✨ できること

| 目的 | 始め方 |
|---|---|
| 市場・開示資料を調べる | Web チャットで質問するか、[資料を添付](guides/research.md#upload--analyze-documents)します。 |
| 戦略や因子を検証する | Run Detail でチャートと約定を確認し、`/alpha-zoo` で因子を比較します。 |
| 模擬取引・取引の振り返り | `/paper-trading` で日次約定と純資産を追い、CLI の `/journal` と `/shadow` で売買を検証します。 |
| 口座と配分を比較する | `/portfolio` で保有銘柄と配分変更案を確認します。[対応ブローカー](#ブローカー対応表) |
| オプションと相関を調べる | `/options` で複数レッグの損益とグリークスを、`/correlation` で市場局面を調べます。 |
| 調査を分担・定期実行する | [Swarm チーム](guides/research.md#swarm-workflows)を起動し、Pixel Office で分担するか、`/scheduled` で配信を予約します。 |
| 過去の根拠を確認する | `/research-artifacts` で日付付きの[調査履歴](guides/research.md#versioned-research-artifacts)を検索し、任意の2つのリビジョンを比較し、系列全体または選択した比較をJSONまたはMarkdownでエクスポートします。 |

## ⚡ 実行例

`vibe-trading init` の後、自然言語でバックテストを頼むか、端末で因子ライブラリを評価できます。

```bash
vibe-trading run -p "2024年の BTC-USDT を20期間と50期間の移動平均クロスでバックテストし、買い持ちと比較して最大ドローダウンを報告して。"
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**Run Detail** で買い持ちと比較し、下落局面の約定と実行カードのデータソースを確認します。

## 🧪 調査の流れ

| 手順 | 移動平均クロスの例 |
|---|---|
| 計画 | 対象ペア、期間、移動平均、ベンチマークを指定します。 |
| データ確認 | BTC-USDT の過去の足を取得し、出所と日付を確認します。 |
| 実行 | 戦略を作成して検証します。実行ディレクトリに戦略、約定、資産曲線が残ります。 |
| 検証 | 買い持ちと比較し、リターンと併せて回転率、下落幅、検証時の警告を確認します。 |
| 再検討 | 保存済みの実行を開くか、条件を変えて質問します。日付付きの結論を保存し、新しい根拠で改訂することもできます。 |

## 📡 データソースと自動切り替え

**28種類の市場データソース**に対応。`source: "auto"` では銘柄から市場を判定し、設定順に取得を試みます。

| 市場 | 取得順 |
|---|---|
| 中国A株・香港株 | まず Tencent、足が欠けていれば Eastmoney、その後は市場別の設定順です。 |
| 米国株 | Yahoo、Stooq、Sina の順に試します。 |
| 暗号資産 | まず OKX、Binance、CCXT を試します。 |
| 先物 | 中国の銘柄は AKShare またはローカルの足を使用。その他の国の先物はローカルデータを用意します。 |

取得元も指定できます。`vibe-trading-ai[ashare]` を追加すると BaoStock の中国A株日足をトークンなしで使えます。全取得順と認証要件は[データソース一覧](guides/capabilities.md#-data-sources--smart-fallback)を参照してください。

## 🔩 機能の詳細

### 市場調査

| 機能 | 用途 |
|---|---|
| 開示・保有銘柄 | SEC 13F で運用者の保有銘柄を四半期ごとに比較し、ETF の構成銘柄を確認できます。各報告には基準日を付記します。 |
| 企業価値評価 | `/dcf` で割引率や永久成長率の影響を、`/comps` で同業倍率を検証。財務三表連動モデルは Excel に出力できます。 |
| 論文・資料 | arXiv と OpenAlex でシグナルの定義を調べ、自分の銘柄群で検証します。開示資料、表計算、スライドの図表についても質問できます。 |
| 銘柄抽出 | Gildata を有効にすると、時価総額で絞り込み、半期売上高も取得できます。因子診断は個別に有効化します。 |

### クオンツ研究

| 機能 | 用途 |
|---|---|
| Alpha Zoo | Qlib、Alpha101、GTJA、学術・ファンダメンタル因子を比較。期間別の情報係数を調べ、ウォークフォワードで検証します。 |
| バックテスト | 中国A株の値幅制限、暗号資産の資金調達料、先物証拠金を再現。複数市場で資金を共有し、個別約定を確認できます。 |
| オプションラボ | レッグごとにスプレッドを組み、満期損益、グリークス、原資産価格と IV の変化を比較します。 |
| リスク | 下落幅、VaR、期待ショートフォールを確認。Brinson 分析で配分と銘柄選択を分け、市場間の相関を追えます。 |
| 戦略の追跡 | 根拠と共に戦略を登録し、新しい検証ごとにシャープレシオや因子の情報係数を追跡します。 |

### 口座と取引

| 機能 | 用途 |
|---|---|
| ポートフォリオ | 読み取り専用口座の保有銘柄を集約するか extraETF をインポートし、目標配分で金額の変化を確認します。 |
| 模擬取引 | 保存口座を1営業日進め、約定・現金・純資産を確認。別のシミュレーションで中国A株を5分刻みで再生することもできます。`paper_trade_reconcile` agent/MCP ツールは、相場やブローカーにアクセスせず、手数料・現金・ポジション・NAV の算術を独立に検証します。 |
| シャドー口座 | 取引履歴を取り込み、手数料や売買の癖を調べ、ルールに従った場合の約定と比較します。 |
| ブローカー接続 | CLI または Web で設定し、読み取りで接続確認。実取引の前に銘柄・注文・エクスポージャーの上限を定め、緊急停止もできます。 |

### チームと定期調査

| 機能 | 用途 |
|---|---|
| Swarm と Pixel Office | 強気・弱気の投資委員会やクオンツチームの報告を読み、Pixel Office で担当者を決めて共有ボードに結果を記録します。 |
| 定期レポート | 寄り付き前、決算、保有銘柄の点検から選び、設定済みの Slack、Telegram、メールなどへ定時配信します。 |
| 調査履歴 | 過去の会話と実行を検索。根拠付きの結論を日付とともに保存し、投資仮説の改訂を比較できます。 |
| 実行記録 | データソース、モデル、実行ログ、指標の根拠を調べ、約定と資産曲線から報告値を確認します。 |

### ブローカー対応表

<details>
<summary>読み取り・模擬・実取引を比較</summary>

読取は専用の読み取りプロファイル、模擬はサンドボックスまたはローカルでの注文、実売買は許可範囲内の注文です。✓ は対応の宣言、— は該当設定なしです。

<!-- BEGIN GENERATED broker-overview -->

| 接続先 | 読取 | 模擬 | 実売買 |
| --- | :---: | :---: | :---: |
| alpaca | ✓ | ✓ | ✓ |
| binance | ✓ | ✓ | ✓ |
| dhan | ✓ | ✓ | — |
| etoro | ✓ | ✓ | ✓ |
| futu | ✓ | ✓ | ✓ |
| ibkr | ✓ | — | — |
| kis | ✓ | ✓ | — |
| longbridge | ✓ | ✓ | — |
| mstock | ✓ | — | — |
| mt5 | ✓ | ✓ | ✓ |
| okx | ✓ | ✓ | ✓ |
| robinhood | ✓ | — | ✓ |
| scalable | ✓ | — | — |
| shoonya | ✓ | ✓ | — |
| tiger | ✓ | ✓ | ✓ |
| toss | ✓ | — | — |
| trading212 | ✓ | — | — |
| upbit | ✓ | ✓ | — |
| zerodha | ✓ | ✓ | — |

<!-- END GENERATED broker-overview -->

</details>

[プロファイル別の権限](guides/portfolio-and-brokers.md#full-broker-permissions)

## 🎬 デモ

<table>
<tr><th width="50%">Web · 質問から検証まで</th><th width="50%">CLI · 対話型端末</th></tr>
<tr>
<td width="50%" valign="top">

https://github.com/user-attachments/assets/2c595ee1-c577-481a-9460-34ea12bcf41c

</td>
<td width="50%" valign="top">

https://github.com/user-attachments/assets/ac79426e-f3f7-4349-b0d5-d997a2725784

</td>
</tr>
<tr><td>戦略を入力し、エージェントの作業と検証結果を確認します。</td><td>端末でリサーチ用テンプレートを一覧表示し、寄り付き前のブリーフを開きます。</td></tr>
</table>

## 🚀 クイックスタート

Python 3.11+ でインストールし、ウィザードでモデル提供元を選んで対話型 CLI を開きます。

```bash
pip install vibe-trading-ai
vibe-trading init
vibe-trading
```

Docker はフロントエンドと API を `http://localhost:8899` で公開します。クローン後、起動前に提供元を設定します。

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# agent/.env にモデル提供元と API キーを設定します。
docker compose up --build
```

PyPI パッケージは CLI、API、MCP サーバーを含みます。フロントエンド開発とローカルモデルは[インストールガイド](guides/installation.md)を参照してください。

## 🖥 CLI リファレンス

`vibe-trading` で端末を開き、`/help` でコマンドを表示します。

| コマンド | 用途 |
|---|---|
| `/model` | 会話の提供元やモデルを切り替える。 |
| `/history` | 過去の会話を表示して再開する。 |
| `/show <run-id>` | 保存済みの実行結果を開く。 |
| `/pine` | 戦略を Pine Script インジケーターに出力する。 |

シェルでは `vibe-trading alpha list` で因子、`vibe-trading playbook list` で定期調査テンプレートを一覧表示できます。

## 💡 使用例

- 2024年の AAPL と MSFT で月次リターンの差が最大だった月を調べ、後で `/history` から再開します。
- `/journal` で取引履歴を調べ、`/shadow` でルール通りの場合と比較します。
- 銘柄を選び、強気・弱気双方の議論から最終レポートまで確認します。

```bash
vibe-trading --swarm-run investment_committee '{"target":"TSLA","market":"US"}'
```

## 🌐 API サーバー

`vibe-trading serve --port 8899` を起動します。別の端末の `curl http://localhost:8899/runs` で実行一覧を取得し、返された ID で `GET /runs/{run_id}` を呼び出します。

| HTTP での調査 | エンドポイント |
|---|---|
| 会話を作成 | `POST /sessions` |
| 質問を送信 | `POST /sessions/{id}/messages` |
| 進捗を受信 | `GET /sessions/{id}/events` |

`http://localhost:8899/docs` で試せます。[認証が必要なクライアント](guides/cli-and-api.md#security-defaults)は `Authorization: Bearer` ヘッダーで API キーを送ります。

## 🔌 MCP プラグイン

MCP クライアントは同じパッケージを stdio で起動できます。Claude Desktop の `claude_desktop_config.json` に追加し、再起動して `list_skills` を呼びます。

```json
{
  "mcpServers": {
    "vibe-trading": { "command": "vibe-trading-mcp" }
  }
}
```

他のクライアントと出力先の変更は [MCP 設定](guides/mcp.md)を参照してください。

## 🏛 エコシステム

Vibe-Trading は **[HKUDS](https://github.com/HKUDS)** agent ecosystem の一部です。

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>Ultra-Lightweight Personal AI Assistant</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/AI-Trader"><b>AI-Trader</b></a><br>
      <sub>Agent-Native Signal &amp; Copy Trading Platform</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>Making All Software Agent-Native</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>Self-Evolving AI Agent Skills</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>Agent Swarm Intelligence</sub>
    </td>
  </tr></table>

---

## 🗺 ロードマップ

| 領域 | 利用可能 | 予定 |
|---|---|---|
| 模擬取引 | 口座の現金・約定・純資産を日単位で保存。別のシミュレーションで中国A株を5分刻みで再生。 | オプトインの出来高シェア約定（[#2128](https://github.com/HKUDS/Vibe-Trading/pull/2128)、ドラフト）。 |
| 調査 | 検証指標と根拠を実行カードに記録。日付付きの調査記録は改訂履歴を保持し、検索できます。 | 調査記録への構造化された財務データ（[#2164](https://github.com/HKUDS/Vibe-Trading/pull/2164)、レビュー中）。 |
| オプションラボ | 複数レッグの損益、感応度、原資産価格 × IV のシナリオ。 | `/options` で対話的なボラティリティ曲面グリッドを利用可能。 |

## 開発への参加

[初めての方向けの issue](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) を選ぶか、大きな変更は先に issue で相談してください。ローカル設定と PR 前の確認は[貢献ガイド](CONTRIBUTING.md)にあります。

## 貢献者

Vibe-Trading に貢献してくださった皆さまに感謝します。

### v0.1.19 · 貢献者

- @rudycelekli — 58 PRs (12 landed as maintainer ports): GTJA alpha formulas restored to the report (#2036/#2037/#2038/#2039/#2040/#2051), loaders that ask each vendor for the ticker form it serves and page at its own cap (Alpha Vantage #1997, AKShare #1998, CCXT #1999, Tushare minute lots #2001, Tiingo/Stooq class shares #2010/#2012, Nobitex Tehran days #1989, push2 decimals #1988), futures and market fees (micro index price limits #1992, the 30-year treasury fee #1994, India stamp duty on short covers #1995), quant-library and governance fixes (#1950/#1959/#1960/#1962/#1963/#2000/#2017), sub-penny prices kept in trades and charts (#1987/#1990), TTM sums that stop at a missing quarter (#2042), 3:2 splits and ST board limits in paper trading (#1985/#1984), a live halt key that cannot alias the global halt (#2003), session, memory, CLI and API fixes (#1969/#1970/#1982/#2002/#2006), and a string-"false" sweep across ten tools (#1976/#1977/#2008/#2009/#2011/#2013/#2014/#2015/#2016/#2018)
- @he-yufeng — 18 PRs (5 landed as ports): versioned research artifacts (#2079/#2159), background tasks scoped to their owner, reaped on cancel and reconciled after a restart (#2092/#2098/#2100/#2157), silent provider streams interrupted (#2099), cache and reasoning tokens kept in `llm_usage` (#2109), one tool policy across providers (#2087), Claude CLI tool-attempt recovery and structured finals (#2048/#2064/#2120), Qlib BETA/RESI/ROC/CORD semantics (#2062/#2069), magnitude suffixes in derived formulas (#2134), long/short risk x-ray and validation that refuses non-positive equity (#2162/#2161), and Unicode-safe swarm heartbeats (#2155)
- @Jackzigen — the bar-agnostic paper order lifecycle (#2066), swarm runs that stop when cancelled from the chat (#2059/#2060), document figures and percentage points in grounding (#2058/#2108), Robinhood portfolio reads with account selection (#2054), Moonshot reasoning effort for kimi-k3.1-pro (#2043), and Eastmoney JSONP, AKShare 1.20 forex and bare US ETF symbol fixes (#2082/#2083/#2086)
- @Shizoqua — research goals edited in place (#2093), Feishu, Teams, WeChat, WhatsApp and Discord channel fixes (#1957/#1958/#1967/#2078/#2114), heredoc commands in the bash tool (#2077), path-escape tests (#2094), and a run-directory fallback that no longer depends on the process cwd (#2116, landed as a port)
- @cgycorey — global futures priced on real contract multipliers and micro rates, with generic defaults reported (#1965/#1966/#1968/#1972), and a shadow account that honours every entry condition and currency (#2073/#2075)
- @dajiaohuang — transfer flow signs (#2023), aligned attribution benchmarks (#2044), overflow-free weight normalisation (#2046), and boolean payoff quantities refused (#2049)
- @zeus229 — the BYMA engine for Argentine shares and CEDEARs (#2071), backtests reused across turns and sessions (#2074), Codex OAuth model discovery (#2080), and financial units kept in grounding evidence (#2072)
- @alexwan02 — Longbridge per-currency cash (#1940), `.env` read by the MCP server (#1974), and Futu US symbol mapping (#2076)
- @BHhhh-123 — cross-sectional factor combination with walk-forward weights (#1953), field-level data availability in alpha bench (#2057), and factor research provenance (#2067)
- @remote-controlled-man — comma-grouped document integers (#2135), one bounded retry for a withheld final answer (#2136), and A-share source setup docs (#2138)
- @shadowinlife — the opt-in five-minute A-share paper step and its bar-by-bar matching (#2110/#2111), and JoinQuant limit fills (#2127, landed as a port)
- @TWJxi and @lishuanghong1989-netizen — Gildata stock discovery and financial queries (#2117), stock screening with report-period indicators (#2118), and Shannon portfolio style and risk analysis (#2119)
- @TerryF7 — IBKR and Futu gateway endpoints per connection (#1983), and connection deletion without a credential vault (#2153, landed as a port)
- @davidalmeida90 — the next-bar signal delay documented in the strategy skill (#2137)
- @DrDLyuan — STAR Market and Beijing buys sized on their own order grid (#2105)
- @goatyyc — Binance HTTP 451 read failures explained (#1937)
- @hnq-ai — a crawlable documentation wiki (#2165, landed as a port)
- @kadyrbekovhamit-cyber — Heston prices for short expiries (#2140)
- @MetaAviator — invalid journal quantities refused (#2052)
- @octo-patch — MiniMax M3.1 Flash as the default MiniMax model (#1936)
- @RowanAldean — optional Parallel search in `web_search` (#2113)
- @VectorPeak — voice notes forwarded in four IM adapters (#2106)
- @wavebyrd — Yahoo three-letter `=X` forex symbols read as USD pairs (#1980)
- @yufengsika — non-finite and boolean inputs refused by financial rigor checks (#2053)

<details>
<summary>v0.1.17・v0.1.18 サイクルの貢献者</summary>

**v0.1.18** · @warren618 (Haozhe Wu) ツール定義のオンデマンド読み込み、大きな調査結果の保存、中断されたモデル呼び出しの使用量集計の修正を担当しました。

- @rudycelekli — a 92-PR correctness sweep (13 of them landed as maintainer ports): quant-library guards and edge cases (implied-vol price tolerance #1657, gaps in VaR breach transitions #1658, Heston inputs #1719, scheduled CDS coupons #1716, Carino coincidence #1943, undefined probabilistic-Sharpe and bond-accrual inputs #1821/#1822), missing prices kept out of risk x-ray return pairs and OU lag pairs (#1717/#1713), an undefined three-scenario upside and unbounded journal ratios reported as such (#1921/#1884), document reading that keeps PDF text, Word order, PowerPoint groups and Excel missing-value markers (#1838/#1839/#1840/#1841), session search limits, locking and snippets (#1827/#1828/#1832/#1834), more secret formats redacted (#1874/#1880), A-share board limits and Beijing codes (#1913/#1914), standalone revalidation and attribution on the run's own annualisation (#1915/#1948), and settings the selected engine ignores now warned about (#1947)
- @Shizoqua — 25 PRs (2 landed as ports): memory and cross-session search that read back clean and match non-English text (#1682/#1686/#1697/#1771/#1772), skill headings and saved skill names resolved consistently (#1797/#1858), Telegram and Matrix replies no longer dropped when the stream preview never sent and one WeCom stream id per reply (#1860/#1903/#1929), SSE events no longer double-delivered on reconnect (#1798), parallel CLI tool results paired with their own call (#1859), goal evidence confined to the claimed run (#1895), Carhart momentum no longer leaking today's price (#1578), Wilder RSI in the shadow account (#1457), direct-SDK positions priced from `current_price`/`ltp`/`market_val` (#1581), the email SPF/DKIM spoofing check (#1508), and swarm artifacts cleared before each fresh task (#1455)
- @he-yufeng — 24 PRs (2 landed as ports): the declared grounding-check registry and the fired checks recorded in the validation artifact (#1628/#1691/#1661), corrections that keep the figures already passed (#1702), percent-named evidence read as points in derived checks (#1823), additive A-share qfq converted to multiplicative when the offsets validate (#1551), mootdx retired from the default A-share chain and the health canary (#1730), the channel-authoring contract (#1630), the compaction-helper split out of `loop.py` (#1631), the first bar's result counted against initial capital in the options engine and per-bar returns (#1750/#1844), config keys nothing reads warned about (#1935), the US early-bell close on half-days (#1706), and the ReportLab fallback for Shadow Account PDFs (#1683)
- @shadowinlife — 19 PRs (5 landed as ports): daily paper trading with saved accounts across CLI, API and Web (#1939), the shared scheduler kernel adopted by the research, back-office and live loops (#1893/#1899), token usage in Run Detail, chat and swarm (#1890), `read_run_artifact` and a structured backtest tool summary (#1647/#1646), `get_southbound_flow` and a northbound flow that no longer serves a silent empty envelope (#1486/#1484), guided Web UI setup for Feishu, Slack and Discord with runtime errors surfaced in channel status (#1572/#1764/#1777/#1738/#1737), and thirteen fundamental and valuation factors, industry-neutral A-share value alphas and a monthly-horizon IC bench (#1787/#1788/#1802/#1801)
- @zeus229 — 18 PRs (4 landed as ports): grounding that fails closed on unresolved derived refs and suggests exact refs (#1835/#1837/#1638), parses complete derived formulas after labels (#1728), keeps identity in ticker-keyed metrics and blank-corner matrices (#1851/#1850) and leaves execution metadata out of numeric evidence (#1767); rich Email scheduled reports with optional PDF password protection (#1680/#1709), channel-aware scheduled-run editing (#1649), reproducible indicator reads and pinned portfolio snapshots (#1768/#1769), redundant MCP payload copies removed before agent context (#1634), and goal tool-call provenance (#1688)
- @alexwan02 — 16 PRs (4 landed as ports): the `claude-cli` provider backed by a local `claude -p` (#1804), Hong Kong orders sized on each symbol's own board lot (#1813), the Longbridge SDK config built through `from_apikey` (#1805), Futu multi-currency balances with average-cost basis (#1814), SDM registration that keeps its trading rules and records bench history for decay monitoring (#1848/#1849), a lightweight run preview built off the event loop (#1853), run trades listed newest first from the full trades.csv (#1865), trades.csv entry rows, offline benchmarks and Brinson weights fixed (#1780/#1781/#1782), and runtime connectors ordered by status (#1845)
- @Jackzigen — 13 PRs (2 landed as ports): the first `loop.py` extractions for tool-result helpers, run outcome and tuning (#1636/#1641/#1678), a byte-stable system prompt for prefix caching (#1708), after-close SEC filings kept out of the IC until the next bar (#1794), a free BaoStock fallback for `val:*` panels (#1799), undefined correlation pairs published as null instead of 0.0 (#1933), journal PnL pooled per settlement currency (#1811), `BASE-USDT-PERP` routed to the crypto market (#1864), the mStock read-only profile (#1675), and the shared OHLCV contract assertion in per-loader suites (#1725)
- @cgycorey — 12 PRs (3 landed as ports): only the engine's own output grounds a backtest report (#1685), adjusted and raw prices never mixed in one series (#1684), a stooq challenge latch that stops probing and sees every refusal (#1637/#1640), a loader health lane that says why a source is empty and keeps labelled credentials out (#1643/#1698), `get_macro_series` reporting when it caps a series (#1676), env-style credential names, URL userinfo and Basic auth redacted (#1765/#1742/#1744/#1846), and suffixed HK codes normalized for the duplicate-asset guard (#1746)
- @MetaAviator — 12 PRs (2 landed as ports): full-sample downside deviation for Sortino in the metrics and options engines (#1693/#1727), initial capital in Monte Carlo path metrics (#1664), missing equity kept out of adjacent validation returns (#1754), standalone revalidation that honours saved settings and entry dates (#1815/#1842), break-even exits and zero-bar trades kept in trade artifacts and holding periods (#1779/#1876), and trade-journal fixes for reversal fees, split date/time columns, equal timestamps and invalid dates (#1891/#1900/#1941/#1942)
- @lorenzozanee — unsupported Robinhood option orders gated before the broker (#1585), run cards that flag backtests possibly inside the model's training data (#1618), and option evidence in the broker bring-up checklist (#1770)
- @Mikesad — LLM usage accounting extracted from `loop.py` (#1662), swarm presets that take their variables from the prompt (#1674, landed as a port), and the factor registry suite running without symlink privileges (#1696)
- @remote-controlled-man — options legs priced on the run's bar cadence (#1753), the Futu journal format claimed only when its value columns exist (#1766), and three-statement balance tolerance threaded into projected periods (#1786, landed as a port)
- @Romzhou — a kill-switch sweep that fails closed on its own bookkeeping and input (#1703), and a runner driver kept alive for the scheduler's lifetime (#1704)
- @sambazhu — three Gildata research tools with off-exchange fund NAV (#1485), and an env-configurable ReAct iteration cap (#1833)
- @wavebyrd — spread and swap rates for Yahoo `=X` forex pairs (#1930), and per-cent multipliers for ICE coffee, sugar and cotton (#1944)
- @BHhhh-123 — factor neutralisation and PCA in the quant library (#1817, landed as a port)
- @Bortlesboat — Calmar kept finite on explosive equity paths (#1901)
- @bygordon130-hub — Pixel Office, a shared manual research-task board, and the Turkish locale (#1616)
- @davidalmeida90 — profit factor reported as undefined when no trade lost (#1602)
- @DrDLyuan — the equity.csv drawdown peak seeded with initial capital (#1818)
- @Emad211 — per-channel configuration, custom providers and the Persian locale (#1264)
- @Frank-zhu2000 — Futu profiles no longer pinning the HK trade market (#1812)
- @goatyyc — Binance balances that survive clock skew, with unpriced assets marking the snapshot incomplete (#1505)
- @hunters1011-ctrl — symlink tests skipped where symlinks are unavailable (#1803)
- @incorpore — Brazil (B3) market data and an opt-in ZimaOS template (#1783, landed as a port)
- @mdb1230 — five example options strategies and a candidate study of which to paper-trade (#1774)
- @mminkus — the interactive message cap raised to match the scheduled-run path (#1701)
- @passionbull — KIS reads that see SOR fills and recover from a server-invalidated token (#1726)
- @rwxyx518-prog — the Portfolio page's holdings table and history chart following the display currency (#1810)
- @ThreeTima — currency identity checked in financial figure grounding (#1905)
- @tomaszkubiak-courses — strategy provenance model fields set on the loop, so writing a strategy file no longer raises `AttributeError` (#1673)
- @xaritoku — dotenv loaded in the `alpha bench` / `alpha compare` CLI handlers (#1806)

</details>

<details>
<summary>v0.1.16 サイクルの貢献者</summary>

- @Shizoqua — a 55-PR correctness sweep (one landed as a port) across nearly every layer: quant-library fixes and input guards (Patell z degrees of freedom #1449, copula ties #1453, Kyle's lambda intercept #1477, HRP labels #1555, non-finite impact and yield-curve inputs #1557/#1558), Alpha Zoo NaN propagation and formula fixes (gtja191_038 #1523, alpha101_074 #1534, qlib158 WVMA #1594, GTJA HIGHDAY/LOWDAY #1604), backtest sizing for negative futures prices and shorts (#1547/#1548), venue bars per year in Monte Carlo validation (#1546), options annual return over elapsed bars (#1458), memory, swarm-store and session robustness (#1450/#1525/#1545/#1536/#1579), DingTalk, Signal, Slack and Discord channel fixes (#1506/#1478/#1524/#1537), Argentina listing identity in grounding (#1575), and a mandate narrowed to zero exposure stored as zero (#1593)
- @zeus229 — grounding that reads locale decimals and grouped numbers with precision-aware rounding (#1517/#1588), resolves explicit symbols and exact field refs from observed evidence (#1584/#1586), preserves `latest_date` timestamps (#1590) and keeps corrections text-only (#1600); Argentina (`.BA`) market data through Yahoo (#1543), ISO-4217 portfolio currencies with isolated FX failures (#1510), explicit header names compared case-insensitively (#1568), technical-indicator volume statistics and their replay after compaction (#1571/#1601), and bounded read-only replay after compaction (#1488)
- @cgycorey — a read-only extraETF export reader (#1406) and the read-only Scalable Capital MCP connector (#1417), run cards that keep non-scalar metrics (#1424), the backtest tool naming the directory it looked in (#1429), a tool-declared swarm `run_dir` confined to the workspace and worker message logs persisted on every terminal path (#1430/#1439), qlib158 CNTP/CNTN/CNTD NaN propagation (#1459), custom zoo roots that no longer replace the bundled module (#1468), `get_shareholder_count` answering again (#1490), Tencent's A-share and HK calibers stamped correctly (#1497)
- @shadowinlife — IM channels configured from the Web UI, with QQ, Email and WebSocket guided setups (#1520/#1529/#1544), stdlib logging placeholders across 12 channel adapters (#1533), Tencent history paginated backward from the end of the window (#1411), `state.json` written by the backtest tool so tool-driven runs are ingestible (#1413), per-worker swarm skill allowlists (#1414), the `1M` interval no longer folding to one minute (#1487), and welcome quick actions with a real selected state (#1500)
- @he-yufeng — tail-risk measure and confidence kept through the grounding gate (#1444), full history in the risk x-ray instead of sampled rows (#1462), shareholder-count history from the per-period report (#1518), backtests attaching to a running MT5 terminal without credentials (#1598), a per-read BaoStock socket deadline (#1615), the weekly live-source health canary (#1627), the broker capability matrix generated into the README (#1629), and the channel `stop_all` and WebSocket logger fixes carried over from #1521
- @lorenzozanee — dragon-tiger seat reports and lockup expiry data restored (#1512/#1513), malformed Robinhood buying power rejected (#1526), broker-only MT5 symbols resolved in `search_symbol` (#1597), hash-only traces and citations on run cards (#1612), expired Copilot CLI tokens refreshed (#1619), and Telegram polling ownership documented (#1583)
- @chiww — the Stooq warning naming the override variable the config layer reads (#1402), A-shares routed by market for sources without a dedicated branch (#1431), the declared interval checked against the served bars before annualising (#1432), and `_NO_NETWORK_FALLBACK_SOURCES` honoured for per-symbol gaps (#1441)
- @as950118 — three Korean broker connectors: KIS with separate paper and live hosts (#1407), Upbit capped at paper plus read-only (#1408), and read-only Toss Securities (#1409)
- @0xouzm — SDM decay metrics that treat NaN and infinite bench results as missing (#1447)
- @alanwilhelm — synchronized cold loader-registry initialization, so concurrent first lookups no longer see an empty registry (#1405)
- @modelpath-dev — the description-driven strategy-store adaptation substrate (#1391)
- @sambazhu — the Gildata A-share OHLCV loader over its raw-api MCP endpoint (#1474)
- @tingkk — broker-neutral SDK diagnostics across all locales (#1436)
- @tonydo — OpenCode as a built-in provider, sending the `x-opencode-session` header OpenCode Go requires (#1416)
- @woshi77777stars — the `Trigger.market` default restored on non-market triggers (#1599)
- @Yoruxyv — the Bahasa Indonesia UI locale and `README_id.md` (#1482)

</details>

<details>
<summary>v0.1.15 サイクルの貢献者</summary>

- @Shizoqua — 28 PRs: NaN propagated through 16 GTJA and Alpha101 alphas instead of fabricated values (#1371/#1372/#1373/#1374/#1379/#1380/#1381/#1382/#1383) and Alpha Zoo returns no longer forward-filling gaps (#1172), missing-price gaps preserved in the SDM template and cross-market volatility weights (#1397/#1398), multi-factor and social-media factor evaluation fixes (#1399/#1400), walk-forward ML training without future-label leakage (#1392), China futures product codes parsed for digit-prefixed, month-code-colliding and lower-case symbols (#1369/#1389), composite sub-engines synced before every dispatch (#1370), per-regime position sizing in strategy discovery (#1368), MCP goal sessions isolated per connection with current-goal defaults (#1173/#1331), Codex token usage and model metadata (#1334/#1348), and swarm cancellation reaching the in-flight worker (#1175)
- @he-yufeng — 26 PRs, mostly fail-closed live trading and backtest semantics: broker API errors and error envelopes fail closed in position reads and the halt sweep (#1212/#1232), the flatten latch persists across restarts (#1233), market-triggered ticks skip closed markets (#1253) and buy-limit orders are sized at the worse of quote and limit (#1312); the price-adjustment caliber stamped on served frames (#1317) with adjusted Yahoo prices (#1287), unresolved symbols retried down the fallback chain (#1288) and the stooq anti-bot challenge flagged (#1342); short option legs holding margin (#1306), perpetual funding settled by bar span (#1307), A-share and India rules enforced through composite state (#1309) and halted positions marked at the last traded close (#1332); Shadow Account PnL, attribution, FIFO short lots and cache keys (#1217/#1310/#1311/#1314); and each monitor's latest verdict rendered on the list (#1156)
- @cgycorey — 23 PRs: UK (LSE `.L`) equity support (#1206), swarm replay/resume of failed runs keeping completed artifacts (#1158), market-data validation of codes, dates and sources with aligned FX/index search and fetch (#1185/#1316), dotted US class shares routed as US equity (#1351), backtest execution fixes — requested targets separated from executed fills, 1x shorts liquidated, option signals filled on the next bar, default IV for HV warm-up and over-committed baskets scaled (#1281/#1298/#1299/#1305/#1344); live halt-sweep envelopes, per-episode latches and MCP buy-limit sizing (#1244/#1254/#1361); grounding clause and metric-table gates (#1326/#1338/#1375/#1378); the registry NaN contract on declared dependencies (#1377); compaction sized by tool-call arguments (#1352); and report audits that fail closed when nothing was verified (#1362)
- @santhreal — 16 PRs extending the quant library: factor risk decomposition, event-study rank and sign tests, OU calibration, drawdown analytics, barrier options, single-name CDS, key-rate duration, IC time series, Vasicek credit loss and group-purged CV (#1159–#1168), Heston pricing, HRP allocation, copulas and market microstructure (#1195–#1198), finite-difference barrier Greeks (#1203), and multi-segment test sets in cross-validation (#1204)
- @AirHua-byte — multi-file drag-and-drop and paste uploads (#1179), interrupted replies recovered after a service restart (#1180), shared HTTP clients preserved during cleanup (#1182), agent-confirmed scheduled research tasks (#1187), persisted Feishu QR login credentials (#1188), explicit market context kept in grounding (#1269), and the offline harness artifact verifier (#1271)
- @lorenzozanee — silent order-plan rejections surfaced through an `_on_plan_rejected` hook (#1245), the temperature self-heal on the OpenAI-compatible path (#1246), escalating stream retry delays that honour Retry-After (#1247), USD-M tolerance calibration (#1248), FMP's Stable endpoint with no silent fallback for an explicit source (#1276), adjusted prices on the FMP and Tiingo paths (#1320), and EPERM handled in desktop updater shutdown checks (#1284)
- @goatyyc — the read-only multi-broker portfolio dashboard and connection framework (#1072) with connector onboarding contracts (#1250), IBKR official MCP OAuth with verified read tools (#1190), and an isolated portfolio OAuth reconnect lifecycle with classified failures (#1211/#1251)
- @saju01 — the agent loop keeping tool results the model still needs (#1341), compacted results reconciled by exact call identity (#1358), and grounding that no longer reads percentage-point deltas as quoted prices (#1346/#1357)
- @aminak58 — symbol identity for bare joined crypto pairs (#1265), FX, metals and futures (#1280), and spot-gold aliases (#1282)
- @averatec0773 — the Anthropic static prefix cached with cache usage recorded (#1366), relocated `extra_body.temperature` stripped in the Anthropic self-heal (#1330), and an attempt start persisted so the elapsed clock survives navigation and reload (#1340)
- @Elfsa-Miranda — Alpaca submissions owned before broker writes, then recovered by exact client id and exact fills across restarts (#1213/#1221/#1222)
- @ethanstoner — skill-relative reference links resolved in `read_file` and on GitHub (#1252/#1328), and strategy-store history that is really newest first (#1347)
- @iagop03 — Web UI fixes: a stale `streamingSessionId` cleared on reopen, a scrollable main region with collapsed long prompts, and non-backtest runs pointed to Studio (#1257/#1258/#1259)
- @Robin1987China — non-finite inputs refused across valuation and credit-risk functions (#1184/#1215), and Archimedean copula CDFs stabilized under large parameters (#1386)
- @Emad211 — cross-platform locks and path handling for Windows (#1261), and read-only Nobitex and Wallex market-data sources (#1263)
- @honginp — read-only Binance USD-M account snapshots (#1229) and USD-M drift evidence artifacts (#1230)
- @pengpengyi92 — bounded backoff on swarm worker retries (#1210), and crypto pairs resolved through an active Binance connector (#1242)
- @ashutoshsinghpr7 — the Zerodha Kite Connect broker for Indian equities (#1193)
- @be-student — the no-progress stop for repeated discovery without new evidence (#1363)
- @BigFishEmily — paginated Tencent finance history requests (#1154)
- @birdxs — Docker CI actions upgraded to Node.js 24 compatible versions (#1359)
- @bonyohana — the survivorship-bias disclosure rendered in the HTML bench report (#1289)
- @c020627 — the IBKR official read-only MCP seed pointed at `/mcp-public` (#1178)
- @guestccc — `/api` routes proxied in the Vite dev server (#1319)
- @Jackzigen — mandate adjustments that enforce narrowing for non-numeric and list fields (#1285)
- @JaxonHu1024 — Futu HKD valuations preserved in the portfolio (#1228)
- @laiyierjiangsu — HK-prefixed symbols (`HK.06693` → `06693.HK`) locked in grounding (#1384)
- @nandofmike — the Brazilian Portuguese (pt-BR) locale (#1327)
- @P1Piyush — metals treated as metals in the forex backtest: pip size, lot size and spreads (#1226)
- @sambazhu — per-market data-source priority in Settings and `MARKET_DATA_ORDER_*` (#1231)
- @SiMinus — `vibe-trading swarm retry` with a resume option (#1194)
- @sykuang — the IBKR public MCP OAuth flow (#1186)
- @thisisjun786 — calendar-triggered partial rebalancing (#1277)
- @wiliao — a run-stall watchdog, a bash tree-kill timeout and a compaction verification ledger (#1169)
- @youngjincho02-arch — the historical VaR quantile formula fixed in the risk-analysis skill (#1189)

</details>

<details>
<summary>v0.1.14 サイクルの貢献者</summary>

- @Shizoqua — a 13-PR correctness sweep across nearly every subsystem: grounding auto-recovers identity and price evidence within a bounded budget (#1092), swarm isolates worker artifacts between retries (#1053), rejects raw `ok`/`success` tool-result envelopes (#1052) and truncates oversized results with the shared notice (#1110), MCP gains offset paging for SEC filings and statements (#1138), routes `load_skill` through the registry so oversized skills page (#1137) and carries market-data provenance on `get_market_data` (#1131), plus `excess_return` consistency (#1058), Wilder-EWM RSI (#1056), the FTS5 tokenizer floor (#1071), non-finite prediction-market fields (#1136), in-flight delivery protection (#1140) and preserved backtest validation evidence (#1139)
- @shadowinlife — the run-analysis surface, four pages in one cycle: Options Lab (#1096), the Factor Research panel with its new IC correlation matrix (#1099), positions structure visualization (#1097) and the tearsheet tab (#1091); plus evidence-gated Strategy Discovery Phase 1 (#978) and Phase 2 decay monitoring (#1007), per-market volume units in market-data provenance (#1065) and baostock volume normalized to board lots (#1067)
- @pengpengyi92 — five quantlib numerics fixes: `xirr` and money-weighted return survive long-horizon discount underflow (#1119), zero-volatility options discount their forward value (#1066), the fixed-income curve keeps decay inside the requested bounds (#1076), event studies anchor to the prior session (#1078) and cross-validation aligns label ends to the prior observation (#1079)
- @cgycorey — reasoning effort honoured in chat completions (#1025), the per-task swarm `ChatLLM` closed to stop a pooled-connection leak (#1145) and the same for one-shot clients (#1153), `gross_profit` derived from revenue minus COGS when the SEC tag is absent (#1111), and `vibe-trading show <run_id>` dispatching its run id instead of the flag (#1147)
- @lorenzozanee — the test suite stopped escaping into the real config root and its live audit ledger (#1118, closes #1116), recovery steering delivered as user messages with inline system tags (#1112), and unsupported ticker-plus-name symbol queries marked skipped rather than failed (#1114)
- @AndyLongest — the interactive backtest research dashboard (#1084), the engine reporting actual post-fill positions (#1082), and grounding ignoring identity constants in rate formulas (#1083)
- @ofeksh-tr — eToro runtime UI parity for SDK connector status (#1051) and its crypto browse and flat market-data quotes (#1070), plus an empty `Response` for the `scheduled-runs` DELETE 204 (#1068)
- @wiliao — the agent-run reliability pass: grounding false-rejections, the final-answer gate and LLM timeouts (#1105), with prompt wording and support/resistance masking (#1060)
- @jay79-boop — a selectable IBKR market-data tier with starved quotes reported as `no_data` (#1075), and strict alpha t-stats surfaced in the bench JSON and HTML report (#1085)
- @Robin1987China — DCF refusing non-finite inputs instead of a silent negative share price (#1121), and grounding masking ISO dates that run into CJK text (#1132)
- @zzz607 — grounding masking line-leading ordered-list markers before number extraction (#1063), and the East Money research-report endpoint given the time parameters it now requires (#1077)
- @Echoandelementwebsites — worker prompts ordered for prompt-cache-friendly prefixes (#1057), and tool-less agents no longer instructed to call `write_file` (#1144)
- @549236606-oss — seven extended read-only Futu connector endpoints, each fail-closed through the existing gateway envelope (#1135)
- @QCYTSN — the desktop update safety boundary: PID-scoped shutdown, dormant candidate verification, interrupted-attempt recovery, and a tested tampered/unsigned/wrong-publisher/downgrade rejection matrix (#1101)
- @honginp — offline USD-M account reconciliation with immutable snapshot contracts and deterministic drift reporting (#1106)
- @he-yufeng — each monitor's latest verdict parsed server-side and persisted on the job for the Market Watch list (#1152)
- @sykuang — GitHub Copilot as a provider through the official SDK, with no borrowed client ID and no editor-impersonation headers (#990)
- @miguelangelo78 — the hosted TickerAll MetaTrader 5 data source, so forex and metals backtests need no local MT5 terminal (#968)
- @ngoanpv — Vietnam equity (HOSE) support: `.VN` no longer executes under China A-share rules (#1033)
- @jax-novita — Novita AI registered as a built-in OpenAI-compatible provider (#1059)
- @daviddaco1 — the Spanish locale and `README_es.md`, the sixth README (#1087)
- @1psconstructor — German (Deutsch) UI support (#1117)
- @x-lambda — the tencent loader building its SSL context from the certifi CA bundle, unblocking HK quotes (#1113)
- @er-s-an — `build_registry()` reporting partial construction instead of silently returning a short tool list (#1129)
- @straun-repo — reasoning effort passed through to the Anthropic adapter (#1115)
- @nstavros — `connector orders` rendering broker_sdk rows, with SDK enum reprs stripped and class-B tickers left intact (#1150)
- @lukiod — `.env.partial` created with owner-only permissions (#1086)
- @fixXxerTech — inferred strategy labels marked as inferred in the run dashboard (#1134)
- @birdxs — Docker images carrying the Feishu and Telegram channel dependencies, with a GHCR/Docker Hub build workflow (#1088)
- @zhiwuyazhe-fjr — a Docker Codex OAuth EOF that explains itself (#1054)

</details>

<details>
<summary>v0.1.13 サイクルの貢献者</summary>

- @santhreal — a 21-PR correctness sweep: trade-journal date and format parsing for Excel serials, UTF-16 BOM CSVs and BTCUSDT-style symbols (#778/#794/#811/#862/#868), loader interval mapping (#812/#838), skill frontmatter closed at EOF (#861), exact memory anchors and result bounds (#956/#957), negative-equity drawdown, insolvent empty cross accounts and `inf` from zero equity (#958/#959/#1041), NaN/inf in the grounding block (#1043), null and non-finite tool arguments (#911/#913), and resource-leak and robustness fixes in the rate limiter, HTTP throttle, event bus, store and Shoonya connector (#1039/#1047/#1046/#1045/#1038)
- @Robin1987China — read-only `technical_indicators` and `sentiment` tools (#921/#939), the final report aggregator stage for `quant_strategy_desk` (#1048), annualisation entries for 15 more data sources (#891), `factor_analysis` realigned on MCP to the registered tool's contract (#715), blank symbol rows skipped in the Futu and generic journal parsers (#749), loader payloads handled without sampling indicator inputs (#1005), and a real account label in CLI balances (#843)
- @he-yufeng — the options payoff and scenario explorer (#883, rebuilt by the maintainer as #946), the strict alpha bench gate via `alpha bench --strict` (#796), composable optimizer weight constraints (#818), rebalance notes and risk x-ray artifacts for portfolio runs (#795/#900), yfinance crypto routed to the crypto engine (#970), and memory entries written with their `.md` suffix (#984)
- @shadowinlife — memory Phase 1 lifecycle management and Tier 2 structural organization (#733/#815), JSON-string list/dict arguments accepted from MCP clients (#993), HK fallback routing repaired with a Tencent HK source (#1000), and MT5 `trading_history` numpy scalars made JSON-safe (#776)
- @honginp — USD-M perpetual realism: margin state contracts, isolated and cross liquidation risk, the funding and liquidation lifecycle and persisted fidelity evidence (#798/#889/#903/#936), plus opt-in atomic rebalancing integrated with strict USD-M positions (#951/#1019)
- @Shizoqua — swarm detection of `ok:false` / `success:false` tool failures (#1028), importance decay in FTS5 memory ranking (#1032), remote server identity in the MCP specs cache key (#1049), and lowercase `4h` requests resampled in the yfinance loader (#1013)
- @tyj147454413-cmd — three fixes split from #543 that landed with their authorship: one run per session with honest terminal states (#676), redaction of free-text tool results (#675), and durable trace records and sidecars (#662)
- @cgycorey — Alpha Zoo tools exposed on MCP with a bounded `alpha_bench` (#979), and mapping-shaped Responses stream events accepted (#1034)
- @darkknight4563 — opt-in non-positive prices in the daily-bar validator (#816, closes #571), and `bar_returns` keeping the real move across a long trading halt (#895)
- @MuggleJinx — sessions, runs and uploads stored under the user runtime root instead of the code tree (#925), and the `connector` CLI loading `~/.vibe-trading/.env` (#902)
- @00EVA — a model dropdown that resizes so full provider/model slugs are readable (#1006)
- @AmirF194 — universe metadata forwarded into the `alpha bench` JSON and HTML output (#841)
- @CRui5in — Web UI LLM settings saved on Windows without an HTTP 500 (#561)
- @ddy4633 — the correlation matrix no longer forward-filling missing closes (#873)
- @Echoandelementwebsites — dataclass tool results serialized without a false circular-reference crash (#849)
- @g0rdonL — historical USD-M funding consumed, with settlement jitter rounded (#819)
- @JungHoonGhae — Korea equity (KRX: KOSPI/KOSDAQ) as a backtest engine (#693, landed as a port)
- @klmtseng — restated PIT fundamentals deduplicated without regressing to an older fiscal period (#772)
- @ngoanpv — timezone-aware local schedules for scheduled research (#954)
- @QCYTSN — live model discovery and runtime identity in Settings (#924)
- @sambazhu — `temperature=1` forced for the whole Kimi K-series (#701)
- @shugaoye — the OpenBB Workspace bridge (#817, landed as a port)
- @TSENGCHIENFENG — the read-only Taiwan stock snapshot tool (#848, landed as a port)
- @wiliao — TSX/TSXV symbols end to end, with bash-written run-dir OHLC CSVs counted as observed evidence (#1037)
- @x-lambda — a config option to disable the agent proxy (#995)
- @xkam7ar — partial market-data results completed through the fallback chain instead of shrinking the universe (#689, landed as a port)
- @y85998607 — the vn.py export skill updated for the vn.py 4.x layout (#869)
- @yagnikpipaliya — the Anthropic adapter self-healing models that deprecate `temperature` (#890)
- @yrk111222 — ModelScope as an OpenAI-compatible provider (#1011)

</details>

<details>
<summary>v0.1.12 サイクルの貢献者</summary>

- @santhreal — a 30-PR correctness sweep: strict-JSON / finite-number hardening across metrics, factors, pattern, and options (#764/#765/#766/#767/#739/#740/#744), loader correctness (#761 yahoo 1m bars), and session / journal robustness (#762/#763/#768/#769/#770)
- @xkam7ar — broad reliability across packaging, web, scheduler, swarm, and CLI (#584), cancellation before the first AgentLoop iteration (#641, closes #638), CI / OOS gates (#630/#632), and journal month-filter / side-parse fixes (#626/#628)
- @shadowinlife — the Strategy Development Manager skill (#457, closes #455), pluggable OCR + LLM-vision extraction (#548), centralized provider credentials (#563), the 80× signal-alignment vectorization (#698), and swarm MCP-discovery caching (#704)
- @ebujinovch — the correlation regime timeline endpoint + UI (#756, closes #719) and its `correlation-regime` skill (#557), plus the `academic_corr_rewire` factor (#705)
- @honginp — Binance USD-M routing with execution/mark separation (#470/#716) and the maintenance-bracket decouple that keeps `-PERP` backtests zero-credential (#757)
- @StaniellG — the MetaTrader 5 (Exness) broker connector + `mt5` data source (#481)
- @tyj147454413-cmd — the Binance fallback loader (#643), bounded OKX history with rate-limit handling (#644), and codex stream-failure classification (#663)
- @Marnie0415 — composite sub-engine fallback for unknown symbols (#734) and the frontend `insertBefore` streaming DOM-race fix (#717)
- @YZY0108 — the look-ahead-bias fix across all five portfolio optimizers (#487)
- @UNHNQ — the SiliconFlow CN + Global providers (#565)
- @FenjuFu — the iFlytek Spark provider (#537)
- @jelech — the native Anthropic Messages API adapter (#695)
- @octo-patch — MiniMax regional API endpoints (#731)
- @Thibaultjaigu — the Requesty OpenAI-compatible gateway provider (#474)
- @Robin1987China — realized portfolio turnover metrics for every optimizer (#478)
- @YogeshModi24 — the Frazzini-Pedersen betting-against-beta academic factor (#480)
- @0xZKnw — opt-in TAP mode for Alpaca (#377)
- @sambazhu — the fundamental zoo `_VALID_ZOOS` whitelist (#707)
- @nareshkps — Robinhood connector `account_number` wiring (#726)
- @darkknight4563 — user swarm-presets directory discovery (#570)
- @MikeCer — IBKR thread-local connection pool + snapshot quotes (#636)
- @Shizoqua — `local` loader interval resampling (#467)
- @roberttidball — FastMCP transport import compatibility (#469)
- @yxhuang — bare-ticker resolution in the correlation matrix (#472, closes #471)
- @Bortlesboat — stale `OPENAI_BASE_URL` provider-switch fix (#484, closes #482)
- @ananaymital — preflight `EnvConfig` stale-cache fix (#479, closes #477)
- @GabbaTauchi — reported the native zai streaming / base-URL bug (#758)
- @warren618 / Haozhe Wu — the correlation regime backend integration, the zai provider streaming + base-URL resolution fix (#758), release integration, and open-PR/issue triage

</details>

<details>
<summary>v0.1.11 サイクルの貢献者</summary>

- @shadowinlife — the `api_server` modularization capstone (1,103 → 371 lines, #424 closing #331), centralized env config with the AST CI gate (#440), loader `fetch()` protocol conformance (#437), and the Strategy Development Manager RFC in review (#455/#457) — 12 merged PRs this cycle
- @Robin1987China — Research Autopilot Phase 3 loop closure (#267), 4 canonical academic alphas (#277), Shadow Account PIT-safe entry conditions (#302/#314/#316), the turnover-aware portfolio optimizer (#466), scheduled-research route tests (#452), and test-coverage batches for trade-journal / pattern / loader layers (#268/#269/#276)
- @muku314115 — first-class Indian equity (NSE/BSE) support: the `IndiaEquityEngine`, cost stack, `.NS`/`.BO` routing, and the `india_broker` bridge (#305)
- @mvanhorn — the end-to-end scheduled-research executor (#278), the Trading 212 read-only connector (#321), OpenAI default-model resolution (#319), and Robinhood config validation (#320)
- @fei-moss — the `analyze_image` vision tool (#464), NapCat DM pairing (#463), and the IM-media allowed-roots report (#465)
- @sambazhu — the value-investing toolkit: financial-rigor + report-audit tools, 4 skills, and the `value_investing_committee` preset (#407/#408)
- @Elfsa-Miranda — the evidence-bound alpha research pipeline exploration (#405/#416, since re-scoped into #442)
- @Hinotoi-agent — loopback CSRF rejection (#293) and authenticated remote same-origin UI requests (#304)
- @dpersek — configurable IM reply timeout (#413) and the provider-preflight redirect fix (#404)
- @digger-yu — cross-platform `setup`/`dev` commands (#292) and dev-dependency pre-checks (#349)
- @skloxo — tilde expansion + file-roots safety fallback (#299) and reactive zh-CN localization (#301)
- @kadaliao — the beginner tutorial (#393) and Alpha Library social cards (#396)
- @morluto — CLI resume first-message preservation (#448) and the Codex OAuth default model (#446)
- @yxhuang — the Kimi for Coding provider (#435) and the precise #433 diagnosis behind the governance-stack revert
- @isaveall — the `validation.json` artifacts-dir fix (#429) and clearer `--swarm-run` errors (#428)
- @mustafakamal88 — timezone-aware UTC timestamps (#397)
- @irfanallana-oss — the zero-size order guard in `trading_place_order` (#417)
- @Shizoqua — the central OHLC-invariant loader guard (#274)
- @hobostay — SSRF-guard hardening for CGNAT/mesh ranges + the QQ media redirect fix (#389)
- @aeonframework — Pillow / langchain CVE floor bumps (#390)
- @hannibal-lee — the pandas version-constraint fix (#329)
- @MarkfuGod — dynamic data-source counts + token-gated microcompaction (#296)
- @gyx09212214-prog — strict JSON validation outputs (#306)
- @LemonCANDY42 — the backtest report library (#224)
- @fanfpy — Longbridge Decimal→float serialization (#459)
- @asahikiko — packaged SKILL.md capability-count sync + the manifest guard test (#461)
- @wison1717-maker — the mandate second-confirmation dialog + unified error toasts (#453)
- @imsankz — opencode provider mappings (#444)
- @flash1234pku — the tushare reference code-fence fix (#449)
- @Penn-Live — the Docker startup route-iteration crash report (#450)
- @warren618 / Haozhe Wu — the fundamental factor layer (PIT-safe SEC panels), the IM channel runtime, India-equity integration review, CN search fallbacks, and release integration

</details>

<details>
<summary>v0.1.10 サイクルの貢献者</summary>

- @Hinotoi-agent — a security-hardening wave: local-shutdown auth (#241), loopback-host rebinding rejection (#242), agent shell-tool opt-in (#243), settings-write auth (#245), mandate proposal-id containment (#256), persistent-memory type validation (#257), and MCP swarm run-id containment (#258)
- @mvanhorn — the opt-in local data cache (#177), Gemini thoughtSignature round-trip over OpenAI-compat tool calls (#176), the custom data loader guide (#194), and the glm/zhipu provider alias + model-name inference (#247)
- @gyx09212214-prog — loader robustness for malformed crypto/RSSHub timeout env vars (#227, #240), requested yfinance end-date inclusion (#226), strict run-card JSON for non-finite metrics (#238), and ddgs retry-fallback coverage (#239)
- @BillDin — swarm agent status in the chat UI (#188), explicit preset-name handling (#189), the loader-backed market-data tool for swarm workers (#199), and preset-context continuations (#200)
- @Robin1987China — the Research Autopilot goal-hypothesis bridge (#260), the local CSV/Parquet/DuckDB data loader (#252), and an assistant-prefill fix + configurable Kimi User-Agent (#248)
- @LemonCANDY42 — the read-only runtime status dashboard (#210), persisted AgentLoop usage artifacts (#223), and opt-in Run Detail chart payloads (#225)
- @zwrong — the trace.jsonl overhaul with zero truncation + offload (#206) and session-id on exit + `resume <session-id>` (#218)
- @forge-builder — the AI contributor guide (#173) and the OpenClaw MCP research-only smoke-test docs (#165)
- @skloxo — Chinese (zh-CN) frontend localization (adopted from #217)
- @LeeCQiang — Chinese docstrings across all 452 Alpha Zoo factors (#180)
- @KaiLuettmann — GHCR pre-built image publishing on release (#187)
- @ngoanpv — Gemini thought_signature preservation through the AgentLoop dict path (#184)
- @ShahNewazKhan — Docker host-Ollama reachability via host.docker.internal (#196)
- @sambazhu — frontend sync of completed chat attempts (#236)
- @bhlt — baostock-native code format support (#230)
- @octo-patch — MiniMax M3 default model upgrade (#162)
- @warren618 / Haozhe Wu — the global data layer (8 sources + 18 read-only data tools), the 10 broker SDK connectors, the alpha-compare full stack, the provider-reliability overhaul, multi-engine web_search fallback, responsive Stop + SSE reconnect, and release integration

</details>

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

## 免責事項

Vibe-Trading は研究・取引ソフトウェアです。投資助言ではなく、資金を一切保管せず、取引所も運営しません。取引はご自身が明示的に認可したブローカーチャネル（例: Robinhood Agentic Trading）を通じてのみ行われ、設定した制限の範囲内で、いつでも停止できます。このブローカー取引機能は実験的であり、当方が実際のブローカー口座で検証したものではありません——自己責任でご利用ください。過去の成績は将来の結果を保証しません。

## ライセンス

[MIT ライセンス](LICENSE)をご覧ください。
