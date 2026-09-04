<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <b>日本語</b> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a> | <a href="README_es.md">Español</a>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading Logo"/>
</p>

<h1 align="center">Vibe-Trading: あなた専用のトレーディングエージェント</h1>

<p align="center">
  <b>1つのコマンドで、包括的なトレーディング能力をエージェントに付与</b>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/25527" target="_blank"><img src="https://trendshift.io/api/badge/repositories/25527" alt="HKUDS%2FVibe-Trading | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
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

> ⚠️ **セキュリティ警告：** Xアカウント `VibeTrading_HKU`、Virtualsプロジェクト `101845`、およびトークンコントラクト `0x640BDBF77b6447E8b7DB7894cED84BD1c40571f4` は、いずれもVibe-Trading公式のものではありません。Vibe-Tradingはこれまで、いかなるトークンやミームコインも発行・公認していません。購入、ウォレットの接続、署名は行わないでください。[詳細](SECURITY.md#official-channels--impersonation)

- **2026-09-02** 💵 **配当を損失として計上していた最後の 2 つの loader と、別人として応答していた明示的なソース**：FMP と Tiingo は未調整の OHLC を配信し続けており、チェーンの他のソースは調整済み価格を返していました——配当落ちのギャップが実際の下落として読まれる問題で、08-31 に Yahoo で修正したものを、今回この 2 つでも修正しました（[#1320](https://github.com/HKUDS/Vibe-Trading/pull/1320)、[#1296](https://github.com/HKUDS/Vibe-Trading/issues/1296) をクローズ）。同じ変更で価格調整基準テーブルの両者の行も訂正しました。調整済みのフレームに `raw` の刻印を押してはなりません。さもないと [#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317) で追加した基準混在の警告は、データではなくラベルを検査することになります。FMP は Stable エンドポイントにも移行し、明示的な `source="fmp"` は他ソースの数値を FMP の名前で返す代わりに、明確に失敗するようになりました（[#1276](https://github.com/HKUDS/Vibe-Trading/pull/1276)、[#1270](https://github.com/HKUDS/Vibe-Trading/issues/1270) をクローズ）。**修正：** 全角括弧内のティッカー——`公司名（代码）价格`——が自身の数値から切り離され、出典なしシンボルのゲートが両者を一緒に見ることがありませんでした（[#1326](https://github.com/HKUDS/Vibe-Trading/pull/1326)、[#1260](https://github.com/HKUDS/Vibe-Trading/issues/1260) をクローズ）。同梱スキル内のすべての `references/` リンクが、agent と GitHub 上でクリックする人間の双方で同じファイルに解決するようになりました（[#1328](https://github.com/HKUDS/Vibe-Trading/pull/1328)）。**新規：** ブラジルポルトガル語が 8 番目の言語としてインターフェースに加わりました（[#1327](https://github.com/HKUDS/Vibe-Trading/pull/1327)）。[@lorenzozanee](https://github.com/lorenzozanee)、[@thisisjun786](https://github.com/thisisjun786)、[@cgycorey](https://github.com/cgycorey)、[@jw232](https://github.com/jw232)、[@ethanstoner](https://github.com/ethanstoner)、[@nandofmike](https://github.com/nandofmike) に感謝します！

- **2026-09-01** 🎯 **オプションのバックテストはシグナル自身が算出した価格で約定し、ネイキッドショートは到底カバーできないプレミアムを売れた**：T 日付のシグナルが T 当日の終値と IV で価格付けされていました——敵対的なケースに限らず、すべてのオプションバックテストに含まれる見せかけのエッジです。シグナルは次のバーで約定するようになり、ショート脚は CBOE 方式の証拠金を計上して買付余力と照合します（[#1299](https://github.com/HKUDS/Vibe-Trading/pull/1299)、[#1306](https://github.com/HKUDS/Vibe-Trading/pull/1306)）。**修正**：無期限先物のファンディングが日足で 1 日 1 回しか清算されず、エンジン自身のモデルである 1 日 3 回と食い違っていました（[#1307](https://github.com/HKUDS/Vibe-Trading/pull/1307)）；1 倍のショートが強制決済から完全に除外されていました（[#1298](https://github.com/HKUDS/Vibe-Trading/pull/1298)）；コンポジット実行がインドの T+1 を取りこぼし、値幅制限の判定が毎バー素通りしていました（[#1309](https://github.com/HKUDS/Vibe-Trading/pull/1309)）。**新規**：配信されるすべてのフレームが価格の調整基準——調整済み、未調整、あるいは正直に不明——を明示し、基準が混在する実行はその旨を告げます（[#1317](https://github.com/HKUDS/Vibe-Trading/pull/1317)、[#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301) をクローズ）。[@he-yufeng](https://github.com/he-yufeng)、[@cgycorey](https://github.com/cgycorey)、[@lorenzozanee](https://github.com/lorenzozanee)、[@guestccc](https://github.com/guestccc) に感謝します！

- **2026-08-31** 🧮 **Yahoo は配当をすべて損失として計上し、表示されていたリバランス回数は約定と無関係だった**：Yahoo の 2 経路はいずれも配当調整前の OHLC を返す一方、チェーン上の他のソースは調整済み価格を返していたため、Yahoo がチェーンを勝ち取った米国株バックテストでは配当落ちギャップがそのまま実際の下落として読まれていました。OHLC は Yahoo の `adjclose` に合わせてスケールされ、yfinance 経路は調整済み系列を要求します。出来高は両経路とも生値のままです（[#1287](https://github.com/HKUDS/Vibe-Trading/pull/1287)）。これを検証するためにチェーンを実測したところ、はっきり述べておくべきことが分かりました：**sina と longbridge は今なお完全に未調整の価格を返します**。どのソースに当たるかで価格の基準が変わる状態は続いており、このギャップは [#1301](https://github.com/HKUDS/Vibe-Trading/issues/1301) で追跡しています。また `rebalance_count` は執行回数ではなく目標ウェイトの*変更*回数を数えていました。目標一定の SPY/BND 戦略が 1,269 回の取引に対してリバランス 1 回と報告していたのです。「要求」と「執行」は独立した指標になり、後者は不変の約定記録から導出されます（[#1281](https://github.com/HKUDS/Vibe-Trading/pull/1281)、[#1275](https://github.com/HKUDS/Vibe-Trading/issues/1275) をクローズ）。**新機能：** `rebalance_mask` により、毎バーではなくカレンダーまたは明示日付で部分リバランスを実行できます（[#1277](https://github.com/HKUDS/Vibe-Trading/pull/1277)、[#1273](https://github.com/HKUDS/Vibe-Trading/issues/1273) をクローズ）。HTML 版 alpha bench レポートにも、JSON には既にあった生存者バイアスの開示が構成銘柄ソースと基準日付きで載るようになりました（[#1289](https://github.com/HKUDS/Vibe-Trading/pull/1289)）。**修正：** 解決できないシンボルが 1 つあっても同一バッチの残りが取り残されなくなりました。チェーンは欠けているものだけを再試行し、来歴には各シンボルが実際に取得されたソースが記録されます（[#1288](https://github.com/HKUDS/Vibe-Trading/pull/1288)）。停止時のスイープが実行していない episode をラッチする可能性、および 2 つの並行完了が互いの記録を失う可能性を修正（[#1254](https://github.com/HKUDS/Vibe-Trading/pull/1254)）。稼働中の富途 OpenD 接続が、ヘルスレポートに `connection_state` が欠けていたため利用不可と表示される問題。デスクトップ更新機能が権限不足のプロセス確認を「バックエンド終了」と読む問題（[#1284](https://github.com/HKUDS/Vibe-Trading/pull/1284)）。ターン途中でバックグラウンドに回したセッションのサイドバー表示がタブを閉じるまで回り続ける問題（[#1257](https://github.com/HKUDS/Vibe-Trading/pull/1257)、[#1256](https://github.com/HKUDS/Vibe-Trading/issues/1256) をクローズ）。[@he-yufeng](https://github.com/he-yufeng), [@cgycorey](https://github.com/cgycorey), [@thisisjun786](https://github.com/thisisjun786), [@bonyohana](https://github.com/bonyohana), [@lorenzozanee](https://github.com/lorenzozanee), および [@iagop03](https://github.com/iagop03) に感謝します！
<details>
<summary>過去のニュース</summary>

- **2026-08-30** 🇬🇧 **LSE 株式がペンスをポンドと誤認せず利用可能になり、閉場中の live trigger も停止**：`.L` シンボルは Yahoo → yfinance → local の市場データフォールバック、株式プロファイルと財務諸表、取引ジャーナルと Shadow の消費先、GBP 決済のバックテストまで end-to-end で動作します。Loader は `.L` を取引所マーカーとしてのみ扱います。通貨が GBp/p と明示された価格は 100 で割り、GBP は変換せず通し、USD・その他・不明の通貨は静的な GBP 会計層に入る前に拒否します。シンボルごとの変換 provenance はキャッシュの往復後も保持され、古い危険なエントリが戻らないようキャッシュ版も更新しました。UK 執行には整数株と `slippage_uk` を使います（[#1206](https://github.com/HKUDS/Vibe-Trading/pull/1206)、[#1205](https://github.com/HKUDS/Vibe-Trading/issues/1205) をクローズ）。**修正：** 関連する全市場が閉場中の場合、market-triggered live tick はブローカー読み取り前に停止しますが、interval-only と event-driven のチャネルは引き続きゲート対象外です（[#1253](https://github.com/HKUDS/Vibe-Trading/pull/1253)）。Run Detail は長い prompt をスクロール・省略表示でき、run 切り替え時に再び折りたたみます（[#1258](https://github.com/HKUDS/Vibe-Trading/pull/1258)）。バックテスト以外の run は空の dashboard ではなく Studio へ移動し、空の trade artifact 配列がデータ入りの `trade_log` を隠さなくなりました（[#1259](https://github.com/HKUDS/Vibe-Trading/pull/1259)）。貢献に感謝します：[@cgycorey](https://github.com/cgycorey)、[@he-yufeng](https://github.com/he-yufeng)、[@iagop03](https://github.com/iagop03)。
- **2026-08-29** 🛑 **自らのアクションを飛ばしたキルスイッチと、別のコインとして解決された暗号資産ペア**：停止中チャネルのブローカー読み取りが失敗したとき——アダプタは例外を投げずにエラー封筒を返し、スイープはそれを注文リストとして反復していました——スイープはそれでも自らを発火済みとして記録していました。キルスイッチが実行するはずの注文取り消しと建玉の手仕舞いが、そのエピソードでは静かに飛ばされ、何も再試行しませんでした。現在はブローカーへの書き込みを実際に試みた後にのみラッチし、2 つのランナーが決済を重複させないよう各停止エピソードを排他的に確保し、トランスポート層の成功に包まれたブローカー拒否を受理として読まなくなりました（[#1244](https://github.com/HKUDS/Vibe-Trading/pull/1244)）。また、`ETH-USDT` を尋ねると `AETHUSDT-USD`——Aave Ethereum USDT という別の資産——が返っていました。シンボル検索が取引所ペアを扱っておらず、Yahoo の最も近い文字列が勝っていたためです。現在、正確なペアは公開されていてブローカー口座を必要としない取引所カタログに対して解決されます（[#1242](https://github.com/HKUDS/Vibe-Trading/pull/1242)、[#1234](https://github.com/HKUDS/Vibe-Trading/issues/1234) をクローズ）。**新規：** 組み込みコネクタが機械可読なオンボーディング契約を公開し、`vibe-trading connector setup` とポートフォリオの接続センターが同一の汎用フローを駆動します。シークレットは接続ごとに OS のキーリングに保管されます（[#1250](https://github.com/HKUDS/Vibe-Trading/pull/1250)）。**修正：** ストリーム再試行が段階的に延び、`Retry-After` を尊重するようになりました（[#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208)）。目標が 1 単元未満に丸められるスリーブは、一度も約定しないまま黙って消えるのではなく報告されます（[#1235](https://github.com/HKUDS/Vibe-Trading/issues/1235)）。明示的ベンチマークは取得ウィンドウではなく評価ウィンドウで測定され、昨日のウォームアップ境界が異なる 2 期間を比較しなくなりました。[@cgycorey](https://github.com/cgycorey)、[@pengpengyi92](https://github.com/pengpengyi92)、[@lorenzozanee](https://github.com/lorenzozanee)、[@goatyyc](https://github.com/goatyyc)、[@ethanstoner](https://github.com/ethanstoner)、[@QG8000](https://github.com/QG8000)、[@turtle696966969696](https://github.com/turtle696966969696) に感謝します！
- **2026-08-28** 📏 **クラッシュするバックテストと、頼んでいない 1 年分を黙って採点していたバックテスト**：v0.1.14 ではクロスマーケットのバックテストがすべて落ちていました——runner は複数市場にまたがるバスケットに対して意図的に `bars_per_year=None` を渡し、新しいリスク X 線がそれに `math.sqrt` を適用していたためです。同じ穴が他に 2 か所あり、4 か所すべてが期間から導出する共通の年率換算係数を使うようになりました（[#1239](https://github.com/HKUDS/Vibe-Trading/pull/1239)、closes [#1237](https://github.com/HKUDS/Vibe-Trading/issues/1237)）。より静かな方：長いルックバックの戦略は**要求した期間より前**のバーを必要とするため、エージェントは MA200 を満たそうと `start_date` を 1 年戻し——そしてその 1 年も採点していました。10 年と称する実行が 11 年を報告し、余分な 1 年の取引・CAGR・ベンチマークが混ざり、エラーは出ず、指標同士は整合していました。`warmup_bars`（または `evaluation_start_date`）がデータ期間と評価期間を分離します。ウォームアップのバーは指標を温めるだけで、他には一切届きません（[#1240](https://github.com/HKUDS/Vibe-Trading/issues/1240)）。**新機能：** `quantlib` に Heston (1993) 確率的ボラティリティ価格付け、階層的リスクパリティ、ガウス・アルキメデス型コピュラ、マイクロストラクチャ推定量（VPIN、Roll、Amihud、Kyle）、有限差分のバリアグリークスを追加——23 モジュール・306 個のテスト済み関数（[#1195](https://github.com/HKUDS/Vibe-Trading/pull/1195)–[#1198](https://github.com/HKUDS/Vibe-Trading/pull/1198)、[#1203](https://github.com/HKUDS/Vibe-Trading/pull/1203)）。**修正：** 8 本のスキル参照リンクが `read_file` では開けないパスを指しており、該当ドキュメントは黙って読み込みに失敗していました。[@cgycorey](https://github.com/cgycorey)、[@santhreal](https://github.com/santhreal)、[@turtle696966969696](https://github.com/turtle696966969696)、[@wanderkiller](https://github.com/wanderkiller) に感謝します！
- **2026-08-27** 🛑 **キルスイッチの一括クローズスイープが再起動を乗り越え、不安定なブローカー接続を信用しなくなりました**：ホールト中、キャンセル+クローズのスイープはブローカーの応答なら何でも成功として扱っていました——しかし MCP アダプタは失敗した呼び出しを `{"status": "error"}` エンベロープに変換するため、一度の接続断で、注文が生きたままなのに監査記録上は問題なしに見えていました。エラーエンベロープは両パスで fail-closed になりました（[#1232](https://github.com/HKUDS/Vibe-Trading/pull/1232)）。また「一度だけ発火」のラッチはメモリ上にしかなく、クローズ注文が約定前のまま再起動するとスイープ全体が再実行され——ポジションごとに新たな成行注文が出て、ロングの口座がネットショートに反転しかねませんでした。ラッチは HALT センチネルの隣に永続化され、そのホールトのエピソードに紐づくため、解除して再トリップすれば再武装されます（[#1233](https://github.com/HKUDS/Vibe-Trading/pull/1233)）。**新機能**：各市場のデータソースのフォールバック順序が *Settings → Data Source Priority* で確認・並べ替え可能に——ホット適用、市場ごとに永続化（`MARKET_DATA_ORDER_*`）、かつ並べ替えのみ許可：ソースの追加や削除は拒否され、オーバーライドがなければデフォルト順序は一切変わりません（[#1231](https://github.com/HKUDS/Vibe-Trading/pull/1231)）。Binance USD-M の照合結果は改ざん検出可能なドリフト証拠アーティファクトとして記録されます——厳格な JSON、不完全または未対応のスナップショットには fail-closed、発注面は一切ありません（[#1230](https://github.com/HKUDS/Vibe-Trading/pull/1230)、[#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030) に向けて）。ありがとう [@he-yufeng](https://github.com/he-yufeng)、[@sambazhu](https://github.com/sambazhu)、[@honginp](https://github.com/honginp)！
- **2026-08-26** ♻️ **ブローカー応答を失ったライブ Alpaca 注文が謎でなくなり、ゴールドのバックテストが摩擦ゼロでなくなりました**：注文ゲートはブローカー書き込み前に送信の所有権を永続化し、正確な `client_order_id` のみで結果を復元、符号付きポジション差分で約定を帰属させ、矛盾があれば HALT——復元経路は決して再送信しません（[#1213](https://github.com/HKUDS/Vibe-Trading/pull/1213)、[#1221](https://github.com/HKUDS/Vibe-Trading/pull/1221)、[#1222](https://github.com/HKUDS/Vibe-Trading/pull/1222)）。**修正：** 貴金属が FX の pip・ロット規約を使い、ゴールドのスプレッドコストが約 1,460 分の 1 に、1,000 オンス未満のポジションは静かにゼロ化（[#1226](https://github.com/HKUDS/Vibe-Trading/pull/1226)）；Futu の HKD 保有が USD として評価され、約 USD/HKD レート分過大（[#1228](https://github.com/HKUDS/Vibe-Trading/pull/1228)）；Shadow Account がランナーの出力しないメトリクスキーを読み、成功したバックテストが常に PnL = 0.00（[#1217](https://github.com/HKUDS/Vibe-Trading/pull/1217)）；ストリーミング LLM 呼び出しが usage を要求せず、swarm の出力トークンを約 18〜36 倍過少報告（[#1225](https://github.com/HKUDS/Vibe-Trading/pull/1225)）。**新機能：** 読み取り専用 Binance USD-M 口座スナップショット（オプトイン）——許可リスト化された署名付きリード 2 本のみ、注文面なし（[#1229](https://github.com/HKUDS/Vibe-Trading/pull/1229)、[#1030](https://github.com/HKUDS/Vibe-Trading/issues/1030) に向けて）；ポートフォリオの OAuth 再接続は制限付きサブプロセスで実行され、Web プロセスやコールバックポートを塞ぎません（[#1211](https://github.com/HKUDS/Vibe-Trading/pull/1211)）。[@Elfsa-Miranda](https://github.com/Elfsa-Miranda)、[@P1Piyush](https://github.com/P1Piyush)、[@JaxonHu1024](https://github.com/JaxonHu1024)、[@he-yufeng](https://github.com/he-yufeng)、[@honginp](https://github.com/honginp)、[@goatyyc](https://github.com/goatyyc) の皆さん、ありがとうございます！
- **2026-08-25** 🛡️ **ライブゲートの 2 件の fail-open を封鎖；purged CV がテストブロック間の訓練データを消す問題も修正**：Alpaca のショートが*プラス*のエクスポージャーとして計上され（`qty` は絶対値、方向は `side`）、売るほど `max_total_exposure_usd` が緩んでいた——数量は TAP JSON と直接 SDK の両経路で符号付きに（[#1209](https://github.com/HKUDS/Vibe-Trading/pull/1209)）；OKX/Futu は拒否された API 呼び出しを「空の帳簿、`status: ok`」に平坦化し、マンデートゲートが何もない帳簿で上限を評価していた——今は明示的なエラー封筒を返し、ゲートは fail-closed する（[#1212](https://github.com/HKUDS/Vibe-Trading/pull/1212)）。いずれも [#1207](https://github.com/HKUDS/Vibe-Trading/issues/1207) 監査ロードマップの Phase 0。**修正：** 組合せ purged CV が非連続テストブロックを一つのスパンとして扱い、その間の訓練観測をすべて purge していた；今はセグメント単位で purge し、訓練データが空になった fold は例外を上げる（[#1204](https://github.com/HKUDS/Vibe-Trading/pull/1204)）；信用リスク関数は NaN/inf 入力を拒否し、NaN スコアや「グレーゾーン」判定を返さない（[#1215](https://github.com/HKUDS/Vibe-Trading/pull/1215)、[#1214](https://github.com/HKUDS/Vibe-Trading/issues/1214) をクローズ）。**新機能：** swarm ワーカーのリトライは上限付き equal-jitter バックオフに（[#1210](https://github.com/HKUDS/Vibe-Trading/pull/1210)、[#1208](https://github.com/HKUDS/Vibe-Trading/issues/1208) に向けて）；`vibe-trading --swarm-retry <run_id>` / `/swarm retry` で失敗した実行を再実行、`--resume` で完了済みタスクを保持（[#1194](https://github.com/HKUDS/Vibe-Trading/pull/1194)）。[@he-yufeng](https://github.com/he-yufeng)、[@santhreal](https://github.com/santhreal)、[@Robin1987China](https://github.com/Robin1987China)、[@pengpengyi92](https://github.com/pengpengyi92)、[@SiMinus](https://github.com/SiMinus) の皆さん、ありがとうございます！
- **2026-08-24** 🔗 **IBKR 公式 MCP が「ツールを列挙するだけ」から実用の読み取り専用ポートフォリオソースへ；スケジューリングには単独では実行できないエージェントツールが追加**：[#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178) は URL を修正しましたが、IBKR ゲートウェイはログイン前に FastMCP 標準の OAuth クライアント登録を拒否していました。IBKR 専用の OAuth プロバイダ——ブラウザ相当のヘッダー、`token_endpoint_auth_method: none`、固定コールバックポート、失効登録の自動回復を、MCP ホストが `api.ibkr.com` の場合にのみ適用——が認可を完了させ（[#1186](https://github.com/HKUDS/Vibe-Trading/pull/1186)）、実口座で検証済みの `get_account_summary` / `get_account_positions` が汎用の口座/ポジション読み取りを支えるようになり、`ibkr-live-official-mcp-readonly` は `/portfolio` の有効なソースになりました（[#1190](https://github.com/HKUDS/Vibe-Trading/pull/1190)、[#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126) をクローズ）。**新機能：** エージェントに見えるスケジューリングツールは `scheduled_research` の 1 つだけ——`propose_create`/`propose_cancel` は、いま居るサーフェスで確認するまでジョブストアに触れません（Web の確認カード、CLI の `y/N`、IM では正確に `confirm`/`确认` と返信）。配信ターゲットはオペレーターが設定する不透明な参照で、生の chat/user id は決して露出せず、`end_at` を過ぎたジョブは期限切れになり再実行されません（[#1187](https://github.com/HKUDS/Vibe-Trading/pull/1187)）。**修正：** comps と三表モデルは、数値が演算に入るすべての入口で非有限入力を拒否するようになりました——従来は NaN のピア指標が倍率分布に*含まれて*中央値を NaN に引きずり、`abs(nan) > tolerance` は `False` のため NaN のバランスシートがハードチェックをすり抜けていました（[#1184](https://github.com/HKUDS/Vibe-Trading/pull/1184)、[#1183](https://github.com/HKUDS/Vibe-Trading/issues/1183) をクローズ）。`get_market_data` は不正な呼び出しでローダーのフォールバックチェーンを浪費する前に codes/日付/source/interval を検証し、source の列挙が登録済み 6 ソースを黙って拒否することもなくなりました（[#1185](https://github.com/HKUDS/Vibe-Trading/pull/1185)）。Feishu の QR ログインは、一度しか渡されないアプリ資格情報をアトミックかつ所有者限定の権限で永続化します（[#1188](https://github.com/HKUDS/Vibe-Trading/pull/1188)）。risk-analysis スキル文書のヒストリカル VaR の順序統計量式をコードに一致させました（[#1189](https://github.com/HKUDS/Vibe-Trading/pull/1189)）。[@sykuang](https://github.com/sykuang)、[@goatyyc](https://github.com/goatyyc)、[@AirHua-byte](https://github.com/AirHua-byte)、[@Robin1987China](https://github.com/Robin1987China)、[@cgycorey](https://github.com/cgycorey)、[@youngjincho02-arch](https://github.com/youngjincho02-arch) の皆さん、ありがとうございます！
- **2026-08-23** 🔌 **IBKR MCP シードが誤った URL を指していた問題と、LLM アダプタを 1 つ閉じると全部閉じてしまう問題**：公式 IBKR 読み取り専用 MCP プロファイルのシード、README、`SKILL.md` はいずれも `https://api.ibkr.com/v1/api/mcp` を指していましたが、IBKR 自身の AI 連携ページが公開しているエンドポイントは `https://api.ibkr.com/v1/api/mcp-public` です。シード・6 つの README・`SKILL.md` をすべてこちらに揃えました。`agent.json` に古い URL が残っている場合は `vibe-trading connector configure ibkr-live-official-mcp-readonly --yes` を再実行してください。IBKR ゲートウェイが OAuth クライアント登録を拒否する件は引き続き [#1126](https://github.com/HKUDS/Vibe-Trading/issues/1126) で追跡中です（[#1178](https://github.com/HKUDS/Vibe-Trading/pull/1178)）。**修正：** `ChatLLM.close()` が LangChain のプロセス全体で共有されるキャッシュ済み HTTPX クライアントまで閉じていたため、タイトル生成や画像認識の呼び出しが 1 回終わるだけで、以降のリクエストが再起動まで "client has been closed" で失敗していました。今は Vibe-Trading 自身が作成したトランスポートだけを閉じます（[#1182](https://github.com/HKUDS/Vibe-Trading/pull/1182)）。応答のストリーミング中にサービスが再起動すると出力済みテキストが失われ、attempt が *running* のまま残っていました。部分応答をチェックポイントとして保存し、次回起動時に明示的な *interrupted* エントリとして履歴に復元します（[#1180](https://github.com/HKUDS/Vibe-Trading/pull/1180)）。**新機能：** Web チャットでファイル選択・ドラッグ＆ドロップ・クリップボード貼り付けにより 1 ターンに最大 5 ファイルを添付できます（[#1179](https://github.com/HKUDS/Vibe-Trading/pull/1179)）。[@c020627](https://github.com/c020627) さん、[@AirHua-byte](https://github.com/AirHua-byte) さん、ありがとうございます！
- **2026-08-22** 💼 **Portfolio ページ：ブローカー横断で保有を読み取り専用に集約**：読み取り専用のコネクタープロファイル（`account.read` + `positions.read` を持つ接続インスタンス。IBKR 公式 MCP プロファイルはまだ対象外）を選ぶと、新しい `/portfolio` ページがそれらをイミュータブルなスナップショットに集約します——保有ごとの出所、USD/CNY 評価、CSV エクスポート、履歴チャート付き。更新に失敗したソースは**エラーとして報告され合計から除外**され——前回のキャッシュで埋めることはなく——スナップショットは不完全とマークされます。`portfolio_summary` ツールは既存の `portfolio_risk_xray` にそのまま渡せる `risk_xray_args` を返し、`vibe-trading portfolio show|refresh|sources` は同じスナップショットをターミナルに表示します。自作の読み取り専用コネクタープラグインは `~/.vibe-trading/connectors/` に置きます（書き込み能力を宣言したマニフェストは拒否、シークレットは `[keyring]` extra 経由で OS のキーチェーンへ）。この経路からは何も発注できません（[#1072](https://github.com/HKUDS/Vibe-Trading/pull/1072)、[#1171](https://github.com/HKUDS/Vibe-Trading/issues/1171) に向けて）。**修正：** Alpha Zoo の 13 ファクターがリターン計算前に欠損終値を前方補完し、データギャップを有限の「0% リターン」にしていました——ギャップは `NaN` のまま保たれます（[#1172](https://github.com/HKUDS/Vibe-Trading/pull/1172)）。同一 http/sse サーバー上の無関係な MCP クライアントが単一のフォールバック研究ゴールセッションを共有していました（[#1173](https://github.com/HKUDS/Vibe-Trading/pull/1173)）。メモリの GC と圧縮が古い FTS 行と孤立した relation サイドカーを残していました（[#1174](https://github.com/HKUDS/Vibe-Trading/pull/1174)）。`cancel_run()` がストリーミング中の swarm worker に届かず——ストリームを中断し、そのターンのツール呼び出しをスキップし、*キャンセル済み*タスクとして記録します（[#1175](https://github.com/HKUDS/Vibe-Trading/pull/1175)）。MCP `get_research_reports` が `beginTime`/`endTime` を落としていました（[#1176](https://github.com/HKUDS/Vibe-Trading/pull/1176)）。`get_options_chain` が別サイクルの満期に `ok: true` と他の日付の契約を返していました（[#1177](https://github.com/HKUDS/Vibe-Trading/pull/1177)）。貢献に感謝します：[@goatyyc](https://github.com/goatyyc)、[@Shizoqua](https://github.com/Shizoqua)、[@cgycorey](https://github.com/cgycorey)。
- **2026-08-21** ⏱️ **永久に固まる実行**：`bash` のタイムアウトは shell だけを kill し、パイプハンドルを持つ孫プロセスが生き残るため、実行は 20 分以上「実行中」のままでした。現在は専用プロセスグループで起動してツリー全体を kill し、新しいストール監視が前進のない実行を終了させ、圧縮もモデル自身の検証記録を捨てなくなりました（[#1169](https://github.com/HKUDS/Vibe-Trading/pull/1169)）。**修正：** 複数年の Tencent 履歴が 500 本で暗黙に切り詰められていました（[#1154](https://github.com/HKUDS/Vibe-Trading/pull/1154)）。**新機能：** swarm 実行は失敗サブグラフのみを再生（[#1158](https://github.com/HKUDS/Vibe-Trading/pull/1158)、[#1157](https://github.com/HKUDS/Vibe-Trading/issues/1157) をクローズ）。Market Watch は各モニターの最新判定を一覧内に表示（[#1156](https://github.com/HKUDS/Vibe-Trading/pull/1156)、[#943](https://github.com/HKUDS/Vibe-Trading/issues/943) をクローズ）。`quantlib` はテスト済み 286 関数に到達（[#1159](https://github.com/HKUDS/Vibe-Trading/pull/1159)–[#1168](https://github.com/HKUDS/Vibe-Trading/pull/1168)）。貢献に感謝します：[@wiliao](https://github.com/wiliao)、[@cgycorey](https://github.com/cgycorey)、[@he-yufeng](https://github.com/he-yufeng)、[@BigFishEmily](https://github.com/BigFishEmily)、[@santhreal](https://github.com/santhreal)、[@SiMinus](https://github.com/SiMinus)、[@alinv0](https://github.com/alinv0)。
- **2026-08-20** 🚀 **v0.1.14 リリース**（[リリースノート](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.14)、`pip install -U vibe-trading-ai`）：0.1.13 以降 272 コミット・74 件のマージ済み PR。**主役は、終わったバックテストが CSV の山ではなく「読めるもの」になったことです。** Run Detail に 4 つのタブが増えました——**ファクター研究**（平均線付きの日次 IC 系列、IC 統計、分位ポートフォリオの資産曲線、そしてこれまでどこにも無かった IC 相関行列）、**ポジション構成**（日付スライダー付きのウェイト円/ツリーマップ、業種別ネットエクスポージャー、ウェイト推移の面グラフ。円は**グロス**構成、バーは**ネット**なので、同一業種のロング／ショートはバーでは相殺されて 0 になり、円では両脚とも見えたままです）、**ティアシート**（月次リターンのヒートマップ、年次バー、上位 5 ドローダウンを資産曲線に重ねて表示）、そして KPI・ベンチマーク対比の資産推移・ローリングシャープ・全約定台帳を備えた対話型**リサーチダッシュボード**。4 つとも実行が既に書き出している artifact を読むだけで、新しいデータパイプラインはありません。新しい **Options Lab** ページでは満期損益図、原資産×IV のシナリオ行列、ポートフォリオのグリークス、ライブのオプションチェーンを、MCP ツールと同じテストで固定されたエンジンで計算します。**インストール：** Intel Mac で再び `pip install vibe-trading-ai` が通ります——`smartmoneyconcepts` が `llvmlite` を引き込み、後者は 0.46 以降 macOS x86_64 wheel を出していないため、Intel でのインストールは毎回 CMake を要するソースビルドになっていました。これをオプトインの `[smc]` extra に移し、古い `<3.14` 上限も外しました（[#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)）。**新機能：** Alpha Zoo と SDM ストアをまたぐ**エビデンス・ゲート付きストラテジー探索**（投入経路、読み取り時に算出する鮮度 `fresh`/`aging`/`stale`、陳腐化した行は既定の推奨から fail-closed で除外）、リース付き outbox で**自分から配信する**スケジュール調査と Market Watch 一覧向けに永続化される判定、7 つの読み取り専用 **Futu** エンドポイント、バックテスト市場としての**ベトナム（HOSE）**、オフラインの **USD-M 口座照合**、**Novita AI** と **GitHub Copilot** のプロバイダ、ホスト型 **MetaTrader 5** データソース、**スペイン語**と**ドイツ語**のロケール、そして MCP ツールは 74 個に。**正確性：** テストスイートがサンドボックスを抜け出して実際の設定ルートに書き込むことがなくなりました——以前はフル実行のたびにハッシュ連鎖の実口座監査台帳へ偽の `order_rejected` が追記されていました。`build_registry()` は欠けたツール表を黙って返しません。`xirr` は長期ホライズンの割引アンダーフローに耐え、DCF は非有限入力を負の株価で返さず拒否します。`.VN` 銘柄が A 株ルールで約定されることもなくなり、バックテストのアーカイブが 2 つの実行の成果物を混ぜることもなくなりました。さらに grounding の一連の修正で、日付・順序付きリスト・レート式中の恒等定数・見積りと誤読された注文行という誤拒否の一群が解消しました。@Shizoqua、@shadowinlife、@pengpengyi92、@cgycorey、@ofeksh-tr、@lorenzozanee、@AndyLongest、@zzz607、@wiliao、@jay79-boop、@Robin1987China、@Echoandelementwebsites、@zhiwuyazhe-fjr、@x-lambda、@sykuang、@straun-repo、@nstavros、@ngoanpv、@miguelangelo78、@lukiod、@jax-novita、@honginp、@he-yufeng、@fixXxerTech、@er-s-an、@daviddaco1、@birdxs、@QCYTSN、@549236606-oss、@1psconstructor の皆さんに感謝します。
- **2026-08-19** 🔌 **停止した実行、タスクごとに漏れる接続、インストールできない Intel Mac**：provider が無応答になると実行が無限に固まっていました。新しい `VIBE_TRADING_LLM_TIMEOUT_SECONDS`（既定 300s）が呼び出しを制限し、tool-call マークアップが最終回答として出力されることもなくなりました（[#1105](https://github.com/HKUDS/Vibe-Trading/pull/1105)）。swarm はタスクごとにプール済み HTTP 接続を 1 本漏らしていました（[#1145](https://github.com/HKUDS/Vibe-Trading/pull/1145)、[#1141](https://github.com/HKUDS/Vibe-Trading/issues/1141) をクローズ）。ほかに修正：`vibe-trading show <run_id>` のクラッシュ（[#1147](https://github.com/HKUDS/Vibe-Trading/pull/1147)、[#1146](https://github.com/HKUDS/Vibe-Trading/issues/1146) をクローズ）、処理中の配信の上書き（[#1140](https://github.com/HKUDS/Vibe-Trading/pull/1140)）、バックテスト検証エビデンスの欠落（[#1139](https://github.com/HKUDS/Vibe-Trading/pull/1139)）、MCP のページング（[#1137](https://github.com/HKUDS/Vibe-Trading/pull/1137)、[#1138](https://github.com/HKUDS/Vibe-Trading/pull/1138)）、予測市場の非有限値（[#1136](https://github.com/HKUDS/Vibe-Trading/pull/1136)）。**新機能：** 富途の読み取り専用エンドポイント 7 種（[#1135](https://github.com/HKUDS/Vibe-Trading/pull/1135)）と、推測された戦略名への明示的な `Inferred` チップ（[#1134](https://github.com/HKUDS/Vibe-Trading/pull/1134)）。**インストール：** `smartmoneyconcepts` は `[smc]` extra になりました。これが引き込む `llvmlite` は macOS x86_64 wheel を提供しないため、Intel Mac のインストールは毎回 cmake のソースビルドになっていました（[#1035](https://github.com/HKUDS/Vibe-Trading/discussions/1035)）。`<3.14` の上限もこれに伴い撤廃されます。貢献に感謝します：[@wiliao](https://github.com/wiliao)、[@cgycorey](https://github.com/cgycorey)、[@Shizoqua](https://github.com/Shizoqua)、[@Echoandelementwebsites](https://github.com/Echoandelementwebsites)、[@549236606-oss](https://github.com/549236606-oss)、[@fixXxerTech](https://github.com/fixXxerTech)。
- **2026-08-18** 🈶 **正しいレポートが拒否されなくなり、バックテストがノイズを売買しなくなりました**：`\b` は Unicode を認識するため `最` も語構成文字と見なされ、`(2026-07-14最低)` は「日」の直後に境界がありません。日付がマスクをすり抜け、`2026`・`7`・`14` が価格として OHLC 照合に入り、観測済みのどのレンジにも収まりませんでした（[#1132](https://github.com/HKUDS/Vibe-Trading/pull/1132)、[#1122](https://github.com/HKUDS/Vibe-Trading/issues/1122) をクローズ）。同系統の拒否をさらに 4 件修正：ハイフン形式の取引日（`08-10(一)`）、レンジで示した水準が下限だけマスクされ `-20` が残る件、GTC の注文行（`100 @ $3.50`）が観測値 2 つとして読まれる件、レポート形式の日付セルがどの証跡行にも一致しない件。**バックテスト：**`position_adjustment="hold"` は要求されたサイズ変更を黙って捨て、`"rebalance"` にはドリフト許容幅がまったくありませんでした。実測では日次 0.01% の変動で 30 本中 19 本のバーでポジションを取り直しており、独自の `rebalance_freq` を持つ戦略でも毎バー取引していたことになります。捨てられた要求は報告されるようになり、新しい `rebalance_tolerance` は実務家が言う「ウェイトが X 以上動いたらリバランス」の許容幅です。既定は `0.0` なので既存の実行結果は変わりません。さらに、業種中立の alpha101 アルファ 19 本は SP500 ベンチのたびにスキップされていました。パネルにセクタータグが無かったためですが、その情報は構成銘柄を取得している表に元から含まれていました。**新機能：** Market Watch のモニターは、実行完了後にブリーフィングを IM チャンネルへ配信できます。永続化されたアウトボックス経由なので、再起動で失われることも、同時実行のスイープで二重送信されることもありません（[#942](https://github.com/HKUDS/Vibe-Trading/issues/942)）。**ドイツ語が 7 番目の UI 言語**になりました（[#1117](https://github.com/HKUDS/Vibe-Trading/pull/1117)）。`run_dcf` は非有限の入力を、もっともらしい負の 1 株価格を返す代わりに拒否します（[#1121](https://github.com/HKUDS/Vibe-Trading/pull/1121)、[#1120](https://github.com/HKUDS/Vibe-Trading/issues/1120) をクローズ）。MCP の `get_market_data` 応答は docstring が約束していた `_provenance` を返すようになりました（[#1131](https://github.com/HKUDS/Vibe-Trading/pull/1131)）。インポートに失敗したツールモジュールは名指しされ、レジストリが静かに縮むことはなくなりました（[#1129](https://github.com/HKUDS/Vibe-Trading/pull/1129)、[#1124](https://github.com/HKUDS/Vibe-Trading/issues/1124) をクローズ）。オフラインの USD-M 口座リコンサイルも追加され、接続を開かずにローカルのリスク状態と取引所の観測値を比較します（[#1106](https://github.com/HKUDS/Vibe-Trading/pull/1106)）。**その他：** `backtest.runner` のインポートがプロセスへ `.env` を読み込まなくなりました。`agent/.env` があるマシンでは、これがローカルの全テスト実行を信用できないものにしていました（[#1123](https://github.com/HKUDS/Vibe-Trading/issues/1123)）。[@Robin1987China](https://github.com/Robin1987China)、[@newgo](https://github.com/newgo)、[@er-s-an](https://github.com/er-s-an)、[@Shizoqua](https://github.com/Shizoqua)、[@1psconstructor](https://github.com/1psconstructor)、[@honginp](https://github.com/honginp)、[@cgycorey](https://github.com/cgycorey)、[@alinv0](https://github.com/alinv0)、[@jelech](https://github.com/jelech) に感謝します！
- **2026-08-17** 🔒 **テストスイートが実際の設定ルート（ライブ監査台帳を含む）へ書き込まなくなりました**：プロジェクト自身のスイートを実行すると `~/.vibe-trading/live/audit.jsonl` に捏造された `order_rejected` レコードが追記されていました。これは追記専用のハッシュ連鎖台帳で、エントリを作り出せないことがその価値のすべてです。Windows では壊れた連鎖ファイルも残していました。`conftest.py` には設定ルートのサンドボックスが一切なく、インポート時に `Path.home() / ".vibe-trading"` を固定するモジュールは**どのプラットフォームでも**実ホームを解決していました。Windows がより深刻だったのは、そこでは `Path.home()` が `%USERPROFILE%` を読み `$HOME` を無視するため、スイートが従来使ってきた分離手法が無効になっていたからです。ホームは収集前にリダイレクトされ、サンドボックスはノブを1つだけ持つのでテストごとの分離が引き続き優先され、セッション終了時にはリダイレクトの有無ではなく実台帳がバイト単位で不変であることを検証します（[#1118](https://github.com/HKUDS/Vibe-Trading/pull/1118)、[#1116](https://github.com/HKUDS/Vibe-Trading/issues/1116) をクローズ）。ほかにも：`xirr` と `money_weighted_return` は約51年を超える期間で `ZeroDivisionError` を出していました（割引係数がゼロにアンダーフローするため）——まさに XIRR が存在する理由である長期・不規則なキャッシュフローです（[#1119](https://github.com/HKUDS/Vibe-Trading/pull/1119)）；アクティブな実行へアーカイブされたバックテストが前回の成果物とマージされ、1つのレポートが2つの異なるバックテストを記述しうる状態で、`/runs/{id}` は残存ファイルを自身の成果物として列挙していました（[#1094](https://github.com/HKUDS/Vibe-Trading/issues/1094)）。[@lorenzozanee](https://github.com/lorenzozanee)、[@straun-repo](https://github.com/straun-repo)、[@pengpengyi92](https://github.com/pengpengyi92) に感謝します！
- **2026-08-16** 🔧 **Anthropic の実行がリカバリー経路で停止しなくなり、シンボル検索が空結果を正常と報告しなくなった**：リカバリー経路が途中で追加する `system` メッセージは Anthropic API に拒否されて実行ごと停止していましたが、リカバリー指示はインラインの `<system>` タグ付きユーザーメッセージで送られるようになりました（[#1112](https://github.com/HKUDS/Vibe-Trading/pull/1112)、[#1109](https://github.com/HKUDS/Vibe-Trading/issues/1109) をクローズ）。`search_symbol` はティッカー＋企業名のクエリにゼロ候補を返しながら両ソースが `ok` を報告し、identity がロックされず全データツールが拒否されていました。Yahoo 経路はこのクエリ形状を `skipped` と報告するようになりました（[#1114](https://github.com/HKUDS/Vibe-Trading/pull/1114)、[#1108](https://github.com/HKUDS/Vibe-Trading/issues/1108) をクローズ）。ほかにも：`LANGCHAIN_REASONING_EFFORT` がモデル許可リスト経由で Anthropic ブランチに反映（[#1115](https://github.com/HKUDS/Vibe-Trading/pull/1115)）；Tencent ローダーが certifi CA バンドルで `CERTIFICATE_VERIFY_FAILED` から回復（[#1113](https://github.com/HKUDS/Vibe-Trading/pull/1113)）；`revenue - cogs` の粗利益フォールバックが死にコードでなくなる（[#1111](https://github.com/HKUDS/Vibe-Trading/pull/1111)）；swarm worker が共有ヘルパーで切り詰め、サブエージェントは常に切り詰め表示を見られる（[#1110](https://github.com/HKUDS/Vibe-Trading/pull/1110)）。[@lorenzozanee](https://github.com/lorenzozanee)、[@straun-repo](https://github.com/straun-repo)、[@x-lambda](https://github.com/x-lambda)、[@cgycorey](https://github.com/cgycorey)、[@Shizoqua](https://github.com/Shizoqua) に感謝します！
- **2026-08-15** 🛡️ **デスクトップ更新をより安全に、Windows パッケージングをより確実にし、Run Detail にファクター分析を追加**：休眠中の updater 境界は、再試行できるクリーンアップのために所有プロセスの証拠を保持し、HTTP health ではなく TCP listener でポートの生存を判定し、recovery journal を原子的に確保し、Authenticode とハッシュを同一の staged bytes に結び付け、起動直前にも再検証します（[#1101](https://github.com/HKUDS/Vibe-Trading/pull/1101)）。Windows パッケージングは、上限とチェックサム検証付きの Electron ダウンロードを自前で行い、不安定な旧 installer を実行せず、固定 GTK asset を 7-Zip でデータとして展開するようになりました。ネイティブ Windows CI は終了コード、タイムアウト、runtime 組み立て、NSIS、パッケージ後の起動を検証します（[#1104](https://github.com/HKUDS/Vibe-Trading/pull/1104)、[#1093](https://github.com/HKUDS/Vibe-Trading/issues/1093) を解決）。Run Detail には IC 系列・統計、quantile equity、IC 相関を追加し、artifact traversal と JSON 数値を境界内に保ちます（[#1099](https://github.com/HKUDS/Vibe-Trading/pull/1099)、[#1100](https://github.com/HKUDS/Vibe-Trading/issues/1100) を解決）。汎用 hash lock も Linux、macOS ARM64、Windows でネイティブ検証されました（[#1102](https://github.com/HKUDS/Vibe-Trading/pull/1102)、[#1089](https://github.com/HKUDS/Vibe-Trading/issues/1089) を解決）。[@QCYTSN](https://github.com/QCYTSN) と [@shadowinlife](https://github.com/shadowinlife) に感謝します！
- **2026-08-14** ⚙️ **何もしていなかった推論設定と、まだ回復できたのに止まっていた実行**：`LANGCHAIN_REASONING_EFFORT` はほぼすべてのプロバイダーで黙って無効でした——受け取っていたのは直接の OpenAI だけで、DeepSeek に `high` を設定しても何も変わらず、そのことはどこにも表示されませんでした。この設定は各アダプター固有のフィールドを通じて両方のトランスポートに届くようになりました：既定は Chat Completions、`LANGCHAIN_USE_RESPONSES_API=true` のときは Responses API です。トップレベルの `reasoning_effort` を受け取るプロバイダーは「OpenAI 形式を話すものすべて」ではなく**検証済みの許可リスト**です——リクエストボディを厳密に検証するエンドポイントは未知のキーを拒否して呼び出し自体を失敗させるため、誤った推測の代償は「効かない設定」ではなく「すべてのリクエスト」になります（[#1025](https://github.com/HKUDS/Vibe-Trading/pull/1025)）。grounding ゲートも、決定的な読み取り専用リカバリーがまだ可能な状態で「確認して続行」を返すのをやめました：未解決の銘柄は独自の上限付き予算で `search_symbol` → `get_market_data` を駆動し、反復回数を使い切ってフェイルクローズすることがなくなります（[#1092](https://github.com/HKUDS/Vibe-Trading/pull/1092)、[#1081](https://github.com/HKUDS/Vibe-Trading/issues/1081) をクローズ）。**新規：Options Lab** ページ——マルチレッグの満期損益図、原資産価格 × IV シナリオ行列、ポートフォリオのグリークス、ライブのオプションチェーン。計算は既存の payoff ツールと `quantlib` が担い、数式の二重実装はありません（[#1096](https://github.com/HKUDS/Vibe-Trading/pull/1096)）。**バックテストの tearsheet** タブ（月次リターンのヒートマップ、年次リターン、上位 N のドローダウン区間、[#1091](https://github.com/HKUDS/Vibe-Trading/pull/1091)）。**tickerall** が 25 番目のマーケットデータソースに——ホスト型 MetaTrader 5 の FX/貴金属バーで、どの OS でもローカル端末が不要。明示指定時のみ有効なのでブローカーキーが暗黙のフォールバック先になることはなく、切り詰められた履歴ウィンドウは静かに短い系列を返すのではなくエラーになります（[#968](https://github.com/HKUDS/Vibe-Trading/pull/968)、[#897](https://github.com/HKUDS/Vibe-Trading/issues/897) をクローズ）。そして **Novita AI** と **GitHub Copilot** が組み込みプロバイダーに（[#1059](https://github.com/HKUDS/Vibe-Trading/pull/1059)、[#990](https://github.com/HKUDS/Vibe-Trading/pull/990)）。eToro は商品タイプ別のアセットクラス閲覧に対応し、コピートレードはデモ口座を理由を明示して拒否するようになりました（[#1070](https://github.com/HKUDS/Vibe-Trading/pull/1070)）。Thanks [@cgycorey](https://github.com/cgycorey), [@Shizoqua](https://github.com/Shizoqua), [@shadowinlife](https://github.com/shadowinlife), [@miguelangelo78](https://github.com/miguelangelo78), [@jax-novita](https://github.com/jax-novita), [@sykuang](https://github.com/sykuang), と [@ofeksh-tr](https://github.com/ofeksh-tr)。
- **2026-08-13** 🎯 **バックテストのレポートが実際に約定した建玉を表示**：`positions.csv` にはオプティマイザの**目標**ウェイトが入っていたため、単元丸め・手数料・約定拒否でポートフォリオが約 20% でもレポートは 80% のエクスポージャーを主張しえました。同じ目標値が投資ウェイト指標とリスク X 線にも渡っていました。約定実績は `positions.csv`、要求値は `target_positions.csv` へ（[#1082](https://github.com/HKUDS/Vibe-Trading/pull/1082)）。Run Detail に**リサーチダッシュボード**（`?view=dashboard`）を追加（[#1084](https://github.com/HKUDS/Vibe-Trading/pull/1084)）、**スペイン語が 6 番目の UI 言語**に（[#1087](https://github.com/HKUDS/Vibe-Trading/pull/1087)）。ほかに：`get_research_reports` が全 A 株銘柄で HTTP 400 を返していた問題（[#1077](https://github.com/HKUDS/Vibe-Trading/pull/1077)）、IBKR の気配で要求した配信区分と実際に適用された区分を分離（[#1075](https://github.com/HKUDS/Vibe-Trading/pull/1075)）、`.env.partial` の原子的書き込み（[#1086](https://github.com/HKUDS/Vibe-Trading/pull/1086)）、Docker ワークフローの action を commit 固定しチャネル SDK をハッシュロック（[#1088](https://github.com/HKUDS/Vibe-Trading/pull/1088)）、grounding ゲートがサポート/レジスタンスや過去最高値を観測価格として読まないよう修正（[#1060](https://github.com/HKUDS/Vibe-Trading/pull/1060)）。Thanks [@AndyLongest](https://github.com/AndyLongest)、[@daviddaco1](https://github.com/daviddaco1)、[@zzz607](https://github.com/zzz607)、[@jay79-boop](https://github.com/jay79-boop)、[@lukiod](https://github.com/lukiod)、[@birdxs](https://github.com/birdxs)、[@wiliao](https://github.com/wiliao).
- **2026-08-12** 📏 **フォールバック先が変わっても、A 株の出来高がひそかに 100 倍跳ねることはなくなりました**：A 株のフォールバックチェーンでは 5 つのデータソースが board lot（手）で出来高を返す一方、BaoStock だけは株数を返していました。実際に応答したソースの provenance に単位がなかったため、フォールバック一回で全ての出来高シグナルが 100 倍ずれる可能性がありました。各 loader は市場別の出来高単位を宣言し、provenance は銘柄ごとに実際に採用されたソースの単位を公開します。BaoStock は loader 境界で株数を board lot に変換し、cache v4 が修正前のキャッシュ再利用を防ぎ、実データを使うクロスソース回帰テストが同一の確定取引日について 1% 以内の一致を要求します（[#1065](https://github.com/HKUDS/Vibe-Trading/pull/1065)、[#1067](https://github.com/HKUDS/Vibe-Trading/pull/1067)、[#1062](https://github.com/HKUDS/Vibe-Trading/issues/1062) をクローズ）。この 10 PR の正確性パスには、eToro の完全な runtime status と 5 言語の SDK 接続済み UI（[#1051](https://github.com/HKUDS/Vibe-Trading/pull/1051)）、scheduled-run DELETE の本当に空の 204 応答（[#1068](https://github.com/HKUDS/Vibe-Trading/pull/1068)）、CLI での Alpaca direct-SDK account payload 表示（[#1073](https://github.com/HKUDS/Vibe-Trading/pull/1073)）、実際のモデル構築でも共有される credential 境界での Ollama `/v1` 正規化（[#1074](https://github.com/HKUDS/Vibe-Trading/pull/1074)）、Docker Codex OAuth の stdin EOF に対する実行可能な TTY ガイド（[#1054](https://github.com/HKUDS/Vibe-Trading/pull/1054)、[#1050](https://github.com/HKUDS/Vibe-Trading/issues/1050) をクローズ）、Markdown 番号付きリストの `1.` を根拠のない数値主張として扱わない修正（[#1063](https://github.com/HKUDS/Vibe-Trading/pull/1063)）、`GE` のような 2 文字メモリ検索を FTS5 の有無で一致させる修正（[#1071](https://github.com/HKUDS/Vibe-Trading/pull/1071)）、およびゼロボラティリティ欧州オプションを割引済みフォワード本源的価値で評価し行使判定とプット・コール・パリティを復元する修正（[#1066](https://github.com/HKUDS/Vibe-Trading/pull/1066)）も含まれます。[@shadowinlife](https://github.com/shadowinlife)、[@ofeksh-tr](https://github.com/ofeksh-tr)、[@zhiwuyazhe-fjr](https://github.com/zhiwuyazhe-fjr)、[@zzz607](https://github.com/zzz607)、[@pengpengyi92](https://github.com/pengpengyi92)、[@Shizoqua](https://github.com/Shizoqua) に感謝します。
- **2026-08-11** 🧠 **コンパクションが会話内容を落とさず、swarm のリトライが自分の run を削除できなくなりました**：自動コンパクションは要約前にシリアライズ済み履歴をハードな 80,000 文字で切っていたため、その先の内容は要約呼び出しにも保持された末尾にも届かず、エラーなしで消えていました。これは関数自身の「情報減衰ゼロ」という保証に反し、しかも切断位置がオブジェクトの途中だったため、要約器には不正な JSON が渡されていました。履歴はメッセージ境界で詰め、既存の反復テンプレートでチャンクごとに折り畳むようになりました。1 つのメッセージが 1 チャンクに収まらない場合は切り詰めずラベル付きフラグメントに分け、モデルの空の返答でも、それまで蓄積した要約を消さなくなりました（[#1055](https://github.com/HKUDS/Vibe-Trading/issues/1055) を close）。新しいリトライ時の成果物クリーンアップは `run_dir/artifacts/<agent_id>` に対して `shutil.rmtree` を実行していましたが、`agent_id` は検証されない preset から届き、ユーザー preset は `~/.vibe-trading/swarm/presets/` から読み込まれるため、id が `..` だと run directory 自体に解決されていました。現在は、安全な 1 セグメントであり、解決先がその run の artifacts directory 内にある場合だけ受け入れます。さらに、`technical_indicators` の RSI は docstring がもともと示していた Wilder-EWM 規約に移行し、単純な rolling mean が値を 30/70 の境界の反対側へ動かす問題を直しました（[#1056](https://github.com/HKUDS/Vibe-Trading/pull/1056)）。`excess_return` は修正済み benchmark total から再導出し、同じ metrics dict 内の 2 つのフィールドが食い違わなくなりました（[#1058](https://github.com/HKUDS/Vibe-Trading/pull/1058)）。swarm の成果物検証は `ok`/`success` キーの raw tool envelope を分析として渡すことを拒否し（[#1052](https://github.com/HKUDS/Vibe-Trading/pull/1052)）、リトライされた worker は失敗した試行の `report.md` を引き継がず（[#1053](https://github.com/HKUDS/Vibe-Trading/pull/1053)）、worker prompt は agent 不変ブロックが 1 つのキャッシュ対象 prefix になる順序に整えられました（[#1057](https://github.com/HKUDS/Vibe-Trading/pull/1057)）。[@Shizoqua](https://github.com/Shizoqua) と [@Echoandelementwebsites](https://github.com/Echoandelementwebsites) に感謝します。
- **2026-08-10** 🚀 **v0.1.13 リリース**（[リリースノート](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.13)、`pip install -U vibe-trading-ai`）：0.1.12 以降 408 コミット・162 件のマージ済み PR で、これまでで最大のリリースです。**主役は新機能ではなく修正です：identity ゲートが、すでに証拠を持っている回答を拒否しなくなりました。**以前は整った質問でも実際のツール呼び出しに数分を費やしたうえで*「銘柄の同一性または価格の根拠を安全に確認できません」*と返っていました。原因は、`.SS` と `.SH` が別銘柄として扱われ**上海の銘柄コードがすべて恒久的に ambiguous** になっていたこと、失敗した傍系クエリがロック済みの identity を降格できたこと、Yahoo が CJK クエリすべてに HTTP 400 を返すのを「ここには上場していない」ではなくデータソースの*失敗*として記録していたこと、ツールごとのハードコードされた許可リストがドキュメント記載の 17 通りの引数表記のうち 11 通りを弾いていたこと、日本語・中国語の回答が ASCII のローダー名ではなく `雅虎` や `元` と書いたために拒否されたこと、そして桁区切りが `¥1,309.22` を分断し `1` が観測レンジと比較されていたことです。概念的な質問や比較レポートも行き止まりになりません。記録された OHLC の根拠を外れた価格は**引き続き拒否されます**。**新機能：** `src/quantlib` —— 17 モジュール・249 個のテスト済み関数（オプション、債券、クレジット、計量経済、VaR/CVaR/EVT、要因分解、イベントスタディ、purged CV）を読み取り専用の `quantlib_call` 経由で CLI・Web UI・REST API・MCP から利用でき、skill は markdown に数式を抱え込まず import するようになりました。**バリュエーションエンジン**（`run_dcf` / `run_comps` / 三表連動）は、入力が欠ければ黙ってデフォルトを埋めるのではなくモデルを実行不能にします。**エンティティ + 不規則キャッシュフローの背骨**（XIRR / MOIC / DPI / TVPI、`cashflow_performance` 経由の TWR / Modified Dietz）はバーエンジンとあえて並行に保たれています。**ガバナンスが全実行に組み込まれ**、プロンプト・skill・ツールレジストリ・パッケージバージョンのハッシュ manifest と、自分のハッシュを再計算した改変でも次のレコードで捕捉されるハッシュ連鎖 + fsync の監査台帳が入りました。無料の公開ソースに基づく読み取り専用データツールが 4 つ（四半期比の持高差分付き **SEC 13F**、CSI300 連動 ETF が四半期上位 10 銘柄ではなく純資産の 98.66% にあたる 342 銘柄まで解決する**ETF ルックスルー**、ラベル付き含意確率としての**予測市場**、出典に紐づく主張のみを抜く **arXiv/OpenAlex**）。さらに 6 つの機関投資家向けコマンド（`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`）、独立 skill 化した investor lenses、5 つのスケジュール可能なリサーチ playbook、チェックサム固定の Windows パッケージングと `safeStorage` を備えた**デスクトップ Electron シェル**、13 番目のブローカーコネクタ **eToro**、9 番目のバックテストエンジン **韓国 (KRX)**、**OpenBB Workspace ブリッジ**、カナダ株のエンドツーエンド対応、そして `sentiment`・`technical_indicators`・`options_payoff`・`orderbook_depth`・ModelScope・`vibe-trading update`。**正確性：** SEC の報告期間を `(start, end)` の期間で識別するようにしました —— 年次指定が単一四半期を返しており 4.2 倍の過小評価でした。tushare の A 株価格はコーポレートアクション調整済みになり、権利落ちをまたぐ生のリターンは最大 47 パーセントポイントずれていました。`bar_returns` は売買停止を 0% の変動として記録しなくなり、年率換算は 24 のデータソースすべてを網羅します。生成コードがブローカー層を import できたり、名前を変えた束縛経由で `socket`/`subprocess` に到達できたサンドボックスの穴も塞ぎました。通貨が混在するクロスマーケットのコンポジットバックテストは、1 本のエクイティカーブに合算せず拒否します。@santhreal、@shadowinlife、@Robin1987China、@he-yufeng、@QCYTSN、@Shizoqua、@honginp、@cgycorey、@wiliao、@ngoanpv、@x-lambda、@ofeksh-tr、@00EVA、@zwrong、@yrk111222、@su322、@hhj123123、@dineeshd、@sambazhu、@ddy4633、@tyj147454413-cmd、@y85998607、@JungHoonGhae、@shugaoye、@TSENGCHIENFENG、@darkknight4563、@MuggleJinx、@klmtseng、@ebujinovch、@g0rdonL、@AmirF194、@Echoandelementwebsites、@yagnikpipaliya、@dvirarad、@1anter の皆さんに感謝します。

- **2026-08-09** 🪟 **安全な Windows パッケージ、カナダ市場、ModelScope、MCP 上の Alpha Zoo**：Windows デスクトップのパッケージ処理は、checksum 固定の組み込み Python 3.12 runtime と x64 NSIS の review/signing 経路を組み立て、許可リスト内の credential を Electron `safeStorage` に保存できるようになりました。renderer は秘密を設定・消去できますが読み取れず、平文設定の移行は一度だけ、復号値は所有する backend にだけ渡ります。未署名 review build と署名 build は署名状態が違えば fail closed となり、この PR から installer artifact は公開されていません（[#1015](https://github.com/HKUDS/Vibe-Trading/pull/1015)）。カナダ株は end-to-end で利用可能になり、`.TO`/`.V` を CAD として分類し、Yahoo → yfinance → local の fallback で取得、カナダ固有の GlobalEquity rule で執行し、`XIC.TO` を benchmark とし、通貨混在の集計を拒否します。strict USD-M の過去 backtest でも `position_adjustment=rebalance` を opt-in でき、増減ポジションを通じて collateral、funding、fee、実現 P&L、清算挙動、不変の約定証跡を一貫させます（[#1024](https://github.com/HKUDS/Vibe-Trading/pull/1024)、[#1019](https://github.com/HKUDS/Vibe-Trading/pull/1019)、[#952](https://github.com/HKUDS/Vibe-Trading/issues/952) を close）。ModelScope は公式の OpenAI-compatible hosted-inference endpoint を通じて組み込み provider に加わり、default は `Qwen/Qwen3.5-27B` です（[#1011](https://github.com/HKUDS/Vibe-Trading/pull/1011)）。新しい `vibe-trading update` は wheel install と editable/source checkout を区別し、確認した厳密な release を導入して、新規 process の metadata で検証し、downgrade しません（[#1020](https://github.com/HKUDS/Vibe-Trading/pull/1020)）。さらに `alpha_zoo` と制限付き `alpha_bench` が MCP（計 64 tools）から利用可能になり、期間・結果数・出力先を制限して report を安全に作成します（[#979](https://github.com/HKUDS/Vibe-Trading/pull/979)）。検証済みの Python/frontend lock 更新では grouped dependencies、`postcss`、`akshare` も更新されました（[#1021](https://github.com/HKUDS/Vibe-Trading/pull/1021)、[#1023](https://github.com/HKUDS/Vibe-Trading/pull/1023)、[#1026](https://github.com/HKUDS/Vibe-Trading/pull/1026)、[#1027](https://github.com/HKUDS/Vibe-Trading/pull/1027)）。貢献に感謝します：[@QCYTSN](https://github.com/QCYTSN)、[@wiliao](https://github.com/wiliao)、[@honginp](https://github.com/honginp)、[@yrk111222](https://github.com/yrk111222)、[@zwrong](https://github.com/zwrong)、[@cgycorey](https://github.com/cgycorey)。
- **2026-08-08** 🧱 **デスクトップシェル、eToro、アトミック・リバランス、信頼性強化**：ソース版 Electron ホストが既存バックエンドのライフサイクルを担い、ランダムな loopback ポート、起動ごとの秘密鍵、5 言語の起動復旧、所有プロセスの後始末を提供します。eToro は demo/real を経路レベルで分離したコネクタとして加わり、実運用でリスクを増やす操作は引き続き mandate と監査のゲートを通り、API の機能エンドポイントは認証と CSP で保護されます（[#923](https://github.com/HKUDS/Vibe-Trading/pull/923)、[#989](https://github.com/HKUDS/Vibe-Trading/pull/989)、[#961](https://github.com/HKUDS/Vibe-Trading/pull/961)）。バックテストには不変の約定証跡を残す opt-in の同方向アトミック・リバランスを追加。Shadow は架空の FX 集計をせず決済通貨ごとに市場を分離し、設定済み runtime root に従います。指標は連続した未サンプリング履歴を使い、負の equity における drawdown と空の破産 cross account の清算境界も正しくなりました（[#951](https://github.com/HKUDS/Vibe-Trading/pull/951)、[#997](https://github.com/HKUDS/Vibe-Trading/pull/997)、[#1017](https://github.com/HKUDS/Vibe-Trading/pull/1017)、[#1005](https://github.com/HKUDS/Vibe-Trading/pull/1005)、[#958](https://github.com/HKUDS/Vibe-Trading/pull/958)、[#959](https://github.com/HKUDS/Vibe-Trading/pull/959)）。OpenAI Codex OAuth は独立した排他制御付き credential store と一度限りの 401 復旧を持ち、proxy 無効化は同期・非同期 client の両方に適用。sandbox run は正規の run root を保持し、定期リサーチは壊れた record を隔離して interval の timezone 検証を修正、lowercase `4h` は真の 4 時間足を返します（[#1014](https://github.com/HKUDS/Vibe-Trading/pull/1014)、[#995](https://github.com/HKUDS/Vibe-Trading/pull/995)、[#1012](https://github.com/HKUDS/Vibe-Trading/pull/1012)、[#1003](https://github.com/HKUDS/Vibe-Trading/pull/1003)、[#1004](https://github.com/HKUDS/Vibe-Trading/pull/1004)、[#1013](https://github.com/HKUDS/Vibe-Trading/pull/1013)）。QQ 返信は元 message ID を保持し、長い model slug は読めるまま、agent は証拠が十分なら調査を止めます（[#1008](https://github.com/HKUDS/Vibe-Trading/pull/1008)、[#1006](https://github.com/HKUDS/Vibe-Trading/pull/1006)、[#1010](https://github.com/HKUDS/Vibe-Trading/pull/1010)）。貢献に感謝します：[@QCYTSN](https://github.com/QCYTSN)、[@Shizoqua](https://github.com/Shizoqua)、[@ngoanpv](https://github.com/ngoanpv)、[@hhj123123](https://github.com/hhj123123)、[@su322](https://github.com/su322)、[@Robin1987China](https://github.com/Robin1987China)、[@shadowinlife](https://github.com/shadowinlife)、[@dineeshd](https://github.com/dineeshd)、[@honginp](https://github.com/honginp)、[@santhreal](https://github.com/santhreal)、[@00EVA](https://github.com/00EVA)、[@x-lambda](https://github.com/x-lambda)、[@ofeksh-tr](https://github.com/ofeksh-tr)。
- **2026-08-07** 🛡️ **誤拒否の削減、サンドボックスの穴を封鎖、QVeris を MCP へ**：グラウンディングゲートは「そもそも価格ではない数字」で整形済みの回答を拒否しなくなりました —— 確信度スコア、指標の値、移動平均の期間、`8/5` のような年なし日付、パーセント範囲、そして売買プラン自身のトリガー水準（`終値 ≥6.45` は条件であって提示値ではありません）。一方、記録された OHLC 証拠の範囲外の提示値は**引き続き拒否**され、`08-05` と書かれた価格表も証拠と突き合わせられるようになりました（[#1001](https://github.com/HKUDS/Vibe-Trading/issues/1001)、[#983](https://github.com/HKUDS/Vibe-Trading/issues/983)）。**サンドボックス**：生成された戦略コードはブローカー層を import できなくなり、リネームした束縛経由で `socket`/`subprocess`/`os.system`/`ctypes` に到達することもできません。いずれも従来は通っていました。戦略が使うべき `src.quantlib` は引き続き import できます。**QVeris** の discovery/inspect/execute が MCP に加わり（62 ツール）、コスト見積もりは呼び出し側の申告ではなくマーケットプレイスに問い合わせます（[#976](https://github.com/HKUDS/Vibe-Trading/pull/976)、closes [#964](https://github.com/HKUDS/Vibe-Trading/issues/964)、thanks [@shadowinlife](https://github.com/HKUDS/Vibe-Trading/shadowinlife)）。さらに、香港株データのフォールバック経路の修正と Tencent 香港ソースの追加、yfinance の暗号資産をクリプトエンジンへルーティング、メモリ項目の書き込みと復旧に `.md` 拡張子を付与、MCP の list/dict 引数が JSON 文字列クライアントを許容、実行詳細に Portfolio Studio 成果物を表示（[#1000](https://github.com/HKUDS/Vibe-Trading/pull/1000)、[#970](https://github.com/HKUDS/Vibe-Trading/pull/970)、[#984](https://github.com/HKUDS/Vibe-Trading/pull/984)、[#993](https://github.com/HKUDS/Vibe-Trading/pull/993)、[#980](https://github.com/HKUDS/Vibe-Trading/pull/980)、[#982](https://github.com/HKUDS/Vibe-Trading/pull/982)、[#966](https://github.com/HKUDS/Vibe-Trading/pull/966)、[#973](https://github.com/HKUDS/Vibe-Trading/pull/973)、thanks [@he-yufeng](https://github.com/HKUDS/Vibe-Trading/he-yufeng)、[@ngoanpv](https://github.com/HKUDS/Vibe-Trading/ngoanpv)、[@sambazhu](https://github.com/HKUDS/Vibe-Trading/sambazhu)）。
- **2026-08-06** 🧮 **テスト済み金融数学レイヤー + バリュエーションエンジン + 不定期キャッシュフロー + 配線済みガバナンス**：`src/quantlib` は skills の markdown に散在していた数式を、それぞれ唯一のテスト済み実装に置き換えました —— オプション、債券、クレジット、計量経済、VaR/CVaR/EVT、パフォーマンス要因分析、イベントスタディ、多重検定制御、purged クロスバリデーション —— 約 250 関数が、新しい読み取り専用ツール `quantlib_call` を通じて CLI・Web UI・REST API・MCP から利用できます。バリュエーションエンジン（`run_dcf`/`run_comps`/三表連動）は入力が欠けていればデフォルト値で埋めずに「実行不能」と判定します。新しいエンティティ + キャッシュフロー基盤により NAV・キャピタルコール・クーポンが扱えるようになりました（`cashflow_performance` が XIRR/MOIC/DPI/TVPI と TWR/Modified Dietz を、`orderbook_depth` が暗号資産 L2 のインパクトコストを提供）。各実行はハッシュ manifest を書き出し、監査台帳はハッシュチェーンで改ざんを検出可能に。30 の swarm プリセットはツールが実際に計算できる内容と照合して総点検され、計算できない成果物は数値をでっち上げる代わりにその旨を明示します。
- **2026-08-05** 🔭 **機関投資家保有、ETF ルックスルー、予測市場、論文検索**：無料の公開データのみを使う読み取り専用ツールが 4 つ —— SEC 13F 保有（四半期比の増減付き）、市場をまたぐ ETF 構成銘柄（CSI300 連動型は四半期開示の上位 10 ではなく 342 銘柄・純資産の 98.7% を返します）、イベント契約を単位付きの含意確率として提示、arXiv/OpenAlex 検索は原典にない値を推測せず「記載なし」と印を付けます。あわせて、定期リサーチのテンプレート 5 本、機関投資家向けコマンド 6 つ（`/comps` `/dcf` `/attrib` `/memo` `/earnings` `/screen`）、独立した skill としての investor lenses、そしてすべての数値を生成元のツールまで辿れる agent core。
- **2026-08-04** 🔧 **正確性の修正：ファンダメンタルズ、A 株価格、長すぎるツール結果**：SEC の報告期間は `(start, end)` の期間で識別するようになりました。10-Q は同じ期末日・同じ会計四半期の下に真の四半期と年初来フレームの両方を提出するため、`period="annual"` は AAPL の FY2018〜2020 で単一四半期を返しており（4.2 倍の過少計上）、四半期系列の第 4 四半期の枠にはすべて通年の数値が入っていました。`get_fundamentals("AAPL.US")` も `ok:true` と全 null のパネルを返さなくなります。Tushare の A 株価格はファクターベンチとバックテストの両方で権利落ち調整されるようになり（権利落ち日をまたぐ生の終値騰落率は最大 47 パーセントポイントずれていました。300750.SZ、2023-04-26）、CSI300 ベンチは各日付をその時点の指数構成銘柄でマスクします。クロスマーケットのコンポジットバックテストは、CNY・USD・KRW を 1 本の資産曲線に合算する代わりに、通貨が混在する銘柄セットを拒否します。オプションの各レグは建玉時のボラティリティで評価され、プレミアム比 +93% にも達していた初日の架空損益が解消されました。長すぎるツール結果は JSON の途中で切られる代わりに、総数を明示してレコード単位でページングされます。`calc_metrics` はトラッキングエラーとベンチマークベータを返します。
- **2026-08-03** ⏰ **タイムゾーン対応のスケジュール実行 + 銘柄スクリーニングのデッドロック解消**：スケジュールジョブに任意の IANA `timezone` を指定でき、cron はそのゾーンの壁時計で評価されるため、夏時間の切替をまたいでも周期が保たれます（春の存在しない時刻はスキップ、秋の重複する時刻は最初の 1 回だけ実行）。cron の各フィールドはカンマ区切りと範囲（`1,3-5`）に対応し、タイムゾーン未設定のジョブは従来どおり UTC で動作、Web UI にも 5 言語対応の **Scheduled** ページが追加されました（従来フロントエンドにはスケジュール画面が存在しませんでした）（[#954](https://github.com/HKUDS/Vibe-Trading/pull/954)、closes [#953](https://github.com/HKUDS/Vibe-Trading/issues/953)、[@ngoanpv](https://github.com/ngoanpv) に感謝）。スクリーニング要求が行き止まりにならなくなりました。多数の候補を含む絞り込み結果は「未解決」ではなく「回答」として扱われ、個別銘柄が確定した時点で役目を終えます。価格チェックは銘柄コードの数字・ローカライズされた日付・株数・建玉コストを価格として読まなくなりましたが、記録済み OHLC の範囲外の価格は従来どおり拒否します（closes [#955](https://github.com/HKUDS/Vibe-Trading/issues/955)）。Agent メモリのインデックスアンカー厳密一致と件数上限の修正も含みます（[#956](https://github.com/HKUDS/Vibe-Trading/pull/956)、[#957](https://github.com/HKUDS/Vibe-Trading/pull/957)、[@santhreal](https://github.com/santhreal) に感謝）。
- **2026-08-02** 🧠 **ライブモデル検出、正確なランタイム ID、検証済み依存関係更新**：Settings から設定済み provider のモデルをオンデマンドで取得でき、安定した警告コードと 5 言語の UI で表示します。各応答には実際に処理した provider/model/reasoning の不変 ID が記録・再読込され、セッション切替時には安全に消去されます（[#924](https://github.com/HKUDS/Vibe-Trading/pull/924)、[@QCYTSN](https://github.com/QCYTSN) に感謝）。さらに hash-lock された Python 依存 9 件と `jsdom`/`postcss` を更新し、正確なバージョンの import、重点テスト 330 件、本番ビルド、フロントエンドテスト 373 件、`main` の全 CI、Dependency Graph が成功（[#949](https://github.com/HKUDS/Vibe-Trading/pull/949)、[#948](https://github.com/HKUDS/Vibe-Trading/pull/948)）。破壊的変更を含む MCP 2.0 は、完全なロックとランタイム移行が整うまで未マージです（[#950](https://github.com/HKUDS/Vibe-Trading/pull/950)）。
- **2026-08-01** 🧮 **オプション戦略分析 + 市場センチメント + 監査可能な USD-M リサーチ**：新しいオプション損益ワークフローは、満期時の損益極値、連続する損益ゼロ区間を含む正確な損益分岐点、既存エンジンと整合するエントリー手数料、スポット価格 × IV シナリオを解析的に計算し、Agent と MCP から利用できます（[#946](https://github.com/HKUDS/Vibe-Trading/pull/946)、[#883](https://github.com/HKUDS/Vibe-Trading/pull/883) からクリーンに再実装、thanks @he-yufeng）。読み取り専用の `sentiment` ツールは任意のテキストをローカルでスコアリングし、API キーなしで暗号資産の Fear & Greed Index を取得します（[#939](https://github.com/HKUDS/Vibe-Trading/pull/939)、thanks @Robin1987China）。厳格な USD-M バックテストは、約定、資金調達、リスク、清算の各イベントを順序付きで永続化し、再現性サマリーも出力するとともに、100× 厳格モードで未対応の時間足を拒否します（[#936](https://github.com/HKUDS/Vibe-Trading/pull/936)、thanks @honginp）。信頼性向上として、シンボルと市場を解決してからマーケットデータを呼び出し、最終的な提示価格を記録済み OHLC 証拠と照合します。スケジュール済みリサーチは一時的な障害を再試行し、ネストした MCP 結果も安定してシリアライズされます。
- **2026-07-31** 🔧 **USD-M 清算ライフサイクル + テクニカル指標ツール + 状態ディレクトリのユーザー領域への移行**：オプトインの `perpetual_strict` モードが約定前に過去の資金調達率を精算し、アイソレーテッド/クロス証拠金の逸脱を実際の清算として実行します（[#903](https://github.com/HKUDS/Vibe-Trading/pull/903)、thanks @honginp）。読み取り専用の `technical_indicators` ツールが既存ローダー経由で RSI/MACD/ボリンジャー/SMA/EMA を計算します（[#921](https://github.com/HKUDS/Vibe-Trading/pull/921)、[#920](https://github.com/HKUDS/Vibe-Trading/issues/920) 参照、thanks @Robin1987China）。セッション・実行成果物・スウォーム実行・アップロードは `~/.vibe-trading` 配下に統一され（`VIBE_TRADING_HOME` で移転可能）、初回起動時に自動移行されます（[#925](https://github.com/HKUDS/Vibe-Trading/pull/925)、[#904](https://github.com/HKUDS/Vibe-Trading/issues/904) をクローズ、thanks @MuggleJinx）。ほかに 10 件の整合性修正——Yahoo の `.SS` を A 株に分類、裸/プレフィックス形式の A 株コード、スラッシュ区切りの暗号資産ペア、`nan`/`inf` ガードなど（[#919](https://github.com/HKUDS/Vibe-Trading/pull/919)、[#926](https://github.com/HKUDS/Vibe-Trading/pull/926)–[#935](https://github.com/HKUDS/Vibe-Trading/pull/935)、thanks @santhreal）。
- **2026-07-30** 🎨 **WebUI 刷新 + 韓国（KRX）市場対応 + OpenBB Workspace ブリッジ**：Web UI の guided-minimalism 改修が着地——初期フレームのちらつきを解消し、各ターンは単一の永続アクティビティオブジェクト（推論のライブ・ウィスパー + リロードでも復元されるツールトレイル）を持ち、セッション名は LLM が自動生成、5 言語が完全整合。**韓国株式（KRX：KOSPI/KOSDAQ）**が 9 番目のバックテストエンジンに——±30% 制限値幅を約定時点で判定、ロングオンリー、2026 年 0.20% の証券取引税、任意の `pykrx` ローダー（[#693](https://github.com/HKUDS/Vibe-Trading/pull/693)、thanks @JungHoonGhae）。加えて **OpenBB Workspace ブリッジ**（[#817](https://github.com/HKUDS/Vibe-Trading/pull/817)、thanks @shugaoye）と読み取り専用の**台湾株スナップショット**ツール（[#848](https://github.com/HKUDS/Vibe-Trading/pull/848)、thanks @TSENGCHIENFENG）。整合性：日次の値幅制限は判断バーの終値ではなく**約定時点**で判定。1 セッションの実行は常に 1 つ（HTTP 409）で、ユーザーの停止は独立した終端状態（[#676](https://github.com/HKUDS/Vibe-Trading/pull/676)、thanks @tyj147454413-cmd）。ほかにトレースの永続化（[#662](https://github.com/HKUDS/Vibe-Trading/pull/662)）、ツール結果の秘匿情報スクラブ（[#675](https://github.com/HKUDS/Vibe-Trading/pull/675)）、不正なツール引数のフェイルクローズ（[#913](https://github.com/HKUDS/Vibe-Trading/pull/913)/[#911](https://github.com/HKUDS/Vibe-Trading/pull/911)、thanks @santhreal）、OpenAI 直接接続の `reasoning_effort`（[#755](https://github.com/HKUDS/Vibe-Trading/pull/755)、thanks @1anter）、リスク X 線 / エッジ密度 / オプションエンジンの数値ガード（[#909](https://github.com/HKUDS/Vibe-Trading/pull/909)/[#908](https://github.com/HKUDS/Vibe-Trading/pull/908)/[#907](https://github.com/HKUDS/Vibe-Trading/pull/907)）。
- **2026-07-29** 🔧 **ギャップ安全なリターン + 強制清算リスクモデル + 全ランにリスクX線**：`bar_returns` はフォワードフィル窓を超える取引停止をまたぐ実際の値動きを消さなくなりました——再開バーの動きが無音で 0 と記録され、ボラティリティ過小評価と Sharpe 過大評価を招いていました。`inf` の直前価格がきれいな −100% に読める問題も修正（[#895](https://github.com/HKUDS/Vibe-Trading/pull/895)、thanks @darkknight4563）。年率換算は**全 24 データソース**の全インターバルをカバーし、エントリ欠落時に CI が失敗するカバレッジテストを追加（[#891](https://github.com/HKUDS/Vibe-Trading/pull/891)、closes [#884](https://github.com/HKUDS/Vibe-Trading/issues/884)、thanks @Robin1987China）。USD-M 永久先物リサーチに決定論的な**分離/クロスマージン清算**評価が追加され（[#889](https://github.com/HKUDS/Vibe-Trading/pull/889)、thanks @honginp）、ポートフォリオバックテストは毎回**リスクX線アーティファクト**（`risk_xray.json`/`.md`）を出力します（[#900](https://github.com/HKUDS/Vibe-Trading/pull/900)、thanks @he-yufeng）。`connector` CLI が `~/.vibe-trading/.env` を読み込むようになり、環境変数由来のブローカー資格情報が復活（[#902](https://github.com/HKUDS/Vibe-Trading/pull/902)、closes [#901](https://github.com/HKUDS/Vibe-Trading/issues/901)、thanks @MuggleJinx）。ほか、チャネルメッセージ分割のインデント保持とスキル frontmatter の EOF 解析を修正（[#867](https://github.com/HKUDS/Vibe-Trading/pull/867)/[#861](https://github.com/HKUDS/Vibe-Trading/pull/861)、thanks @santhreal）。

- **2026-07-28** 🔧 **次世代 Claude モデルの解禁 + 符号安全なリターン計算**：`temperature` フィールドを廃止した Claude モデル（opus-4-7、opus-5、sonnet-5）が利用可能になりました。API が当該フィールドを拒否するとアダプタが自動的に除去して一度だけ再試行し、そのモデルを記憶するため、モデルのリリースごとにパッチを当てる必要がありません（[#890](https://github.com/HKUDS/Vibe-Trading/pull/890)、[#856](https://github.com/HKUDS/Vibe-Trading/issues/856) をクローズ、@yagnikpipaliya さんに感謝）。非対話モードの `vibe-trading run` がホストのセッション ID を注入するようになりました。従来はリサーチゴール系ツールが毎回失敗する一方で、実行自体は成功として報告されていました（[#885](https://github.com/HKUDS/Vibe-Trading/issues/885)）。バイ・アンド・ホールドのリターンが符号安全になり、直前終値がゼロに近い場合に複利ベンチマークが発散する問題と、終値がちょうどゼロの場合に `inf`/`nan` になる問題を解消しました（[#872](https://github.com/HKUDS/Vibe-Trading/issues/872)、@darkknight4563 さんに感謝）。フロントエンドを **Node 22 + React Router 8** に移行し、重大度「高」のセキュリティ勧告を解消しています。
- **2026-07-27** 🔧 **相関行列の整合性修正 + vn.py 4.0 エクスポート修復 + エンコーディング修正バッチ**：ローリング相関行列が欠損終値を前方補完しなくなりました。従来は売買停止セッションが架空の 0% リターンとして扱われ、対象銘柄の実際の値動きと対比されて行列が歪んでいました（[#873](https://github.com/HKUDS/Vibe-Trading/pull/873)、@ddy4633 さんに感謝）。**vn.py エクスポート**スキルを vn.py 4.x のレイアウトに対応させました。上流で `vnpy.app.cta_strategy` が廃止されたため、テンプレートは `vnpy_ctastrategy` からインポートします（[#869](https://github.com/HKUDS/Vibe-Trading/pull/869)、@y85998607 さんに感謝）。さらに 6 件の修正：ドキュメントリーダーと取引履歴 CSV の UTF-16 BOM デコード、数値変換前の通貨記号除去、`BTCUSDT` 形式シンボルの暗号資産判定、小文字 `1h`/`1d` インターバルの年率換算、スキルディレクトリ名での CJK 文字保持（[#862](https://github.com/HKUDS/Vibe-Trading/pull/862)、[#863](https://github.com/HKUDS/Vibe-Trading/pull/863)、[#864](https://github.com/HKUDS/Vibe-Trading/pull/864)、[#865](https://github.com/HKUDS/Vibe-Trading/pull/865)、[#866](https://github.com/HKUDS/Vibe-Trading/pull/866)、[#868](https://github.com/HKUDS/Vibe-Trading/pull/868)、@santhreal さんに感謝）。
- **2026-07-26** 🔒 **依存関係ロック修復 + ベンチマーク・ユニバースの透明性**：Docker のハッシュロック付きインストールが復旧し、CI にロック検証を追加しました（[#858](https://github.com/HKUDS/Vibe-Trading/pull/858)、[#847](https://github.com/HKUDS/Vibe-Trading/issues/847) をクローズ）。`alpha bench` は CSI300/SP500 の出典、銘柄数、縮退フォールバック、生存者バイアスを開示します（[#859](https://github.com/HKUDS/Vibe-Trading/pull/859)、[#845](https://github.com/HKUDS/Vibe-Trading/issues/845) をクローズ）。Actions とフロントエンド依存関係 5 件も更新しました（[#850](https://github.com/HKUDS/Vibe-Trading/pull/850)–[#852](https://github.com/HKUDS/Vibe-Trading/pull/852)）。
- **2026-07-25** 🔧 **パーペチュアルのリアリティ向上 + MCP クラッシュ修正 + 正確性バッチ**: USD-M パーペチュアルが**証抠金ステートコントラクト**を獲得（[#798](https://github.com/HKUDS/Vibe-Trading/pull/798)、@honginp さんに感謝）。エンジンは取得して無視していた**過去の資金調達率**を実際に消費するようになりました（[#819](https://github.com/HKUDS/Vibe-Trading/pull/819)、@g0rdonL さんに感謝）。MCP の dataclass 結果が誤検出の `Circular reference detected` でクラッシュしなくなり（[#849](https://github.com/HKUDS/Vibe-Trading/pull/849)、@Echoandelementwebsites さんに感謝）、`alpha bench` の CLI/HTML が `_meta` の生存者バイアス開示を転送します（[#841](https://github.com/HKUDS/Vibe-Trading/pull/841)、[#797](https://github.com/HKUDS/Vibe-Trading/issues/797) をクローズ、@AmirF194 さんに感謝）。さらにジャーナル・コネクタ・チャネル横断の 12 件の正確性修正（[#799](https://github.com/HKUDS/Vibe-Trading/pull/799)–[#810](https://github.com/HKUDS/Vibe-Trading/pull/810)、@santhreal さんに感謝）、CLI 残高ビューに実際のアカウントラベルを表示（[#843](https://github.com/HKUDS/Vibe-Trading/pull/843)、[#846](https://github.com/HKUDS/Vibe-Trading/issues/846) をクローズ、@Robin1987China さんに感謝）。
- **2026-07-24** 🔀 **メモリ Tier 2、合成可能なオプティマイザ制約 + インターバル処理の総点検**：永続メモリが **Tier 2 の構造的な整理**を獲得しました（[#815](https://github.com/HKUDS/Vibe-Trading/pull/815)、@shadowinlife さんに感謝）。バックテストのオプティマイザが**合成可能な重み制約**を受け付けるようになりました（[#818](https://github.com/HKUDS/Vibe-Trading/pull/818)、@he-yufeng さんに感謝）。正確性：日次バーのバリデーターが**非正の価格**をオプトインできるようになり、負の価格バーでは始値を取りつつ、ゼロは引き続き拒否します（[#816](https://github.com/HKUDS/Vibe-Trading/pull/816)、[#571](https://github.com/HKUDS/Vibe-Trading/issues/571) をクローズ、@darkknight4563 さんに感謝）。さらに 19 件の PR によるローダーの**インターバル正規化の総点検**：小文字の `1h/4h/1d/1w` エイリアスを全域で受け付け、未対応のインターバルは日足を黙って返す代わりに fail fast し、Yahoo の `4H` は `1h` にマップ、MT5 は `1W/1M` を受け付けます（[#812](https://github.com/HKUDS/Vibe-Trading/pull/812)–[#838](https://github.com/HKUDS/Vibe-Trading/pull/838)、@santhreal さんに感謝）。加えて、トレードジャーナルの Eastmoney Excel シリアル日付の修正（[#811](https://github.com/HKUDS/Vibe-Trading/pull/811)、@santhreal さんに感謝）と README ナビゲーションアンカーの修正（[#840](https://github.com/HKUDS/Vibe-Trading/pull/840)、@dvirarad さんに感謝）。
- **2026-07-23** 🔧 **信頼性の総点検 + strict alpha-bench の導線追加 + オプトインのメモリライフサイクル**：22 件のコントリビューター PR のバッチ。広範な**信頼性の総点検**がタイムフレーム処理をエンドツーエンドで修正：yfinance `1M`→月足（分ではない）、CCXT `1W`/`1M`、akshare/india-broker がサポート外の間隔を黙って日足にせず拒否、Tiger/Alpaca/OKX/Shoonya/Longbridge コネクタが `1H`/`4H` を時間足として維持。さらに取引ジャーナルの Excel 日付正規化（eastmoney の浮動小数 `YYYYMMDD`、Futu/Tonghuashun のシリアル日付）、`report_audit` の有限数 JSON、空の `holding_days` バリデーション、Feishu/CLI の markdown テーブル端列（[#778](https://github.com/HKUDS/Vibe-Trading/pull/778)–[#794](https://github.com/HKUDS/Vibe-Trading/pull/794)、@santhreal さんに感謝）。**MT5** の `trading_history` は numpy スカラーをネイティブ Python 型に変換し、JSON シリアライズが `int64` で失敗しなくなりました（[#776](https://github.com/HKUDS/Vibe-Trading/pull/776)、[#774](https://github.com/HKUDS/Vibe-Trading/issues/774) をクローズ、@shadowinlife さんに感謝）。**PIT ファンダメンタルズ**は修正済み行を重複排除し、遅れて届いた修正発表でスナップショットが古い会計期に後退しないようにしました（[#772](https://github.com/HKUDS/Vibe-Trading/pull/772)、[#771](https://github.com/HKUDS/Vibe-Trading/issues/771) をクローズ、@klmtseng さんに感謝）。新機能：**`alpha bench --strict`** が、0.1.9 から存在しつつ導線のなかった strict な同一ユニバースのランダム対照 + OOS ゲートをついに接続（[#796](https://github.com/HKUDS/Vibe-Trading/pull/796)、[#773](https://github.com/HKUDS/Vibe-Trading/issues/773) をクローズ、@he-yufeng さんに感謝）、オプトインの**メモリライフサイクル**（品質スコアリング、エビングハウス減衰、アーカイブのみの GC——すべてデフォルト無効）（[#733](https://github.com/HKUDS/Vibe-Trading/pull/733)、[#732](https://github.com/HKUDS/Vibe-Trading/issues/732) をクローズ、@shadowinlife さんに感謝）、そしてバックテストの**リバランスノート**成果物 + 回転率メトリクス（[#795](https://github.com/HKUDS/Vibe-Trading/pull/795)、@he-yufeng さんに感謝）。
- **2026-07-22** 🚀 **v0.1.12 リリース**（[リリースノート](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.12)、`pip install -U vibe-trading-ai`）：**correlation regime タイムライン**が `GET /correlation/regime` エンドポイント + オプトインの Correlation タブストリップを追加しました —— エッジ密度を因果的なヒステリシス状態機械に通して FUSED（融合）した市場エピソードをマークするもので、シグナルではなく記述的なリスクコンテキストです（[#756](https://github.com/HKUDS/Vibe-Trading/pull/756)、[#719](https://github.com/HKUDS/Vibe-Trading/issues/719) をクローズ、@ebujinovch さんに感謝）。プロバイダーのエンドポイント解決が各プロバイダーの canonical な base URL にフォールバックし、非 SSE エンドポイントを適切に処理するようになり、glm-5.1 上のネイティブ **zai** プロバイダーを修正しました（[#758](https://github.com/HKUDS/Vibe-Trading/issues/758)）。さらに、metrics・factors・pattern・session・journal にわたる strict-JSON／有限数の**信頼性の総点検**（[#761](https://github.com/HKUDS/Vibe-Trading/pull/761)–[#770](https://github.com/HKUDS/Vibe-Trading/pull/770)、@santhreal さんに感謝）と、`-PERP` バックテストを資格情報ゼロに保つ Binance のメンテナンスブラケット分離（[#757](https://github.com/HKUDS/Vibe-Trading/pull/757)、@honginp さんに感謝）。0.1.11 以降 約 90 件の修正をまとめています。
- **2026-07-21** 🔧 **データローダーの完全性 + 信頼性修正の総点検**：部分的な市場データは、欠損したシンボルを fallback チェーンで補完し、補完できない場合はフェイルクローズするようになり、バックテストのユニバースを黙って縮小しなくなりました（[#689](https://github.com/HKUDS/Vibe-Trading/pull/689)、[#681](https://github.com/HKUDS/Vibe-Trading/issues/681) をクローズ、@xkam7ar さんに感謝）。また、OKX のバーは深い履歴バックフィルのためにレート制限リトライ付きで `history-candles` エンドポイントを使用します（[#644](https://github.com/HKUDS/Vibe-Trading/pull/644)、@tyj147454413-cmd さんに感謝）。さらに修正の総点検：MCP ネットワークガードが IPv6／大文字小文字違いのホストを受け入れ（[#750](https://github.com/HKUDS/Vibe-Trading/pull/750)、@Robin1987China さんに感謝）、取引ジャーナルのパーサーが空白/NaN のシンボル行をスキップし（[#749](https://github.com/HKUDS/Vibe-Trading/pull/749)、@Robin1987China さんに感謝）、Shadow Account が日足バーでは抽出された入場時間ゲートをスキップし（[#748](https://github.com/HKUDS/Vibe-Trading/pull/748)、@Robin1987China さんに感謝）、MiniMax のリージョン API エンドポイントが選択可能になりました（[#731](https://github.com/HKUDS/Vibe-Trading/pull/731)、@octo-patch さんに感謝）。
- **2026-07-20** 🔀 **プロバイダー、MetaTrader 5、堅牢性の総点検**：ネイティブの **Anthropic Messages API**（任意の `[anthropic]` extra、[#695](https://github.com/HKUDS/Vibe-Trading/pull/695)、@jelech さんに感謝）、**SiliconFlow**（[#565](https://github.com/HKUDS/Vibe-Trading/pull/565)、@UNHNQ さんに感謝）、**iFlytek Spark**（[#537](https://github.com/HKUDS/Vibe-Trading/pull/537)、@FenjuFu さんに感謝）がプロバイダーに加わり、**MetaTrader 5（Exness）** ブローカーコネクタ + `mt5` 為替/貴金属データソースが追加されました（ブローカーコネクタ → **12**、[#481](https://github.com/HKUDS/Vibe-Trading/pull/481)、@StaniellG さんに感謝）。さらに、プロバイダー非依存の **`llm-vision` OCR** エンジン（[#548](https://github.com/HKUDS/Vibe-Trading/pull/548)、@shadowinlife さんに感謝）、**80× のシグナル整列ベクトル化**（[#698](https://github.com/HKUDS/Vibe-Trading/pull/698)、@shadowinlife さんに感謝）、Binance **USD-M ファンディング/ブラケット** の履歴データ（[#716](https://github.com/HKUDS/Vibe-Trading/pull/716)、@honginp さんに感謝）、swarm の MCP ディスカバリキャッシュ（[#704](https://github.com/HKUDS/Vibe-Trading/pull/704)）、そして **13** 件の SSE/セッション/CLI/swarm/スケジューラの問題をクローズする信頼性統合（[#584](https://github.com/HKUDS/Vibe-Trading/pull/584)、@xkam7ar さんに感謝）。正確性の修正：オプションの**部分決済** がロット全体を清算せず要求数量だけを決済するように（[#577](https://github.com/HKUDS/Vibe-Trading/issues/577)）、プロバイダー資格情報解決の一元化（[#563](https://github.com/HKUDS/Vibe-Trading/pull/563)）、キュー中のキャンセル処理（[#641](https://github.com/HKUDS/Vibe-Trading/pull/641)）、フロントエンドのストリーミング DOM 競合（[#717](https://github.com/HKUDS/Vibe-Trading/pull/717)、@Marnie0415 さんに感謝）、コネクタ CLI レンダラー（[#726](https://github.com/HKUDS/Vibe-Trading/pull/726)、@nareshkps さんに感謝）。

- **2026-07-19** 🔧 **米国株/香港株の実ニュース記事 + MCP factor-analysis の修正 + 堅牢性の総点検**：株式ニュースツールは、米国株と香港株のティッカーに対して関連銘柄マッチではなく実際の **Yahoo Finance 記事**（title/url/source/published/snippet）を返すようになり、引き続き凍結された IP スロットリングクライアント経由でルーティングされます（[#730](https://github.com/HKUDS/Vibe-Trading/pull/730)、@yxhuang さんに感謝）。MCP の `factor_analysis` ツールは登録済みツールの実際の CSV コントラクトに揃えられ、実行前に `KeyError` で失敗しなくなりました（[#715](https://github.com/HKUDS/Vibe-Trading/pull/715)、[#635](https://github.com/HKUDS/Vibe-Trading/issues/635) をクローズ、@Robin1987China さんに感謝）。さらに堅牢性の総点検：**Kimi K シリーズ**全体（k2/k3/…/`for-coding`）が API の要求どおり `temperature=1` を自動で強制するようになり（[#701](https://github.com/HKUDS/Vibe-Trading/pull/701)、@sambazhu さんに感謝）、`split_message`・PDF ページ範囲・トレードジャーナルの日付フィルタは、退化した入力や逆転した入力に対してハングや暗黙の空結果を返す代わりに即座に失敗するようになりました（[#727](https://github.com/HKUDS/Vibe-Trading/pull/727)–[#729](https://github.com/HKUDS/Vibe-Trading/pull/729)、@santhreal さんに感謝）。

- **2026-07-18** 🔧 **Binance 暗号資産フォールバック + 並列実行と正確性の修正**：**Binance** loader が暗号資産のヒストリカルデータ fallback チェーンに加わりました（[#643](https://github.com/HKUDS/Vibe-Trading/pull/643)、@tyj147454413-cmd さんに感謝）。また IBKR コネクタはスレッドローカルな接続プールとスナップショット気配に移行し、並列 agent 実行時のハングを修正しました（[#636](https://github.com/HKUDS/Vibe-Trading/pull/636)、@MikeCer さんに感謝）。さらに正確性の総点検：factor analysis は非正の `n_groups` を拒否し、逆転した期間レンジと非正の検出ウィンドウは即座に失敗し、correlation matrix 内の名前なし `DatetimeIndex` を正しく処理し、`equity.csv` の nav/value 列エイリアスを受け付け、空の A 株コードはもう `000000.SZ` に強制変換されません（[#709](https://github.com/HKUDS/Vibe-Trading/pull/709)–[#714](https://github.com/HKUDS/Vibe-Trading/pull/714)、@santhreal さんに感謝）。correlation-rewiring 安定性ファクターが academic zoo に加わり（[#705](https://github.com/HKUDS/Vibe-Trading/pull/705)、@ebujinovch さんに感謝）、fundamental zoo が factor analysis のホワイトリストに追加され（[#707](https://github.com/HKUDS/Vibe-Trading/pull/707)、@sambazhu さんに感謝）、永続化された実行状態が fsync で確実になり（[#645](https://github.com/HKUDS/Vibe-Trading/pull/645)、@tyj147454413-cmd さんに感謝）、dev extra がドキュメント記載の Black/Ruff ツールチェーンをインストールするようになりました（[#634](https://github.com/HKUDS/Vibe-Trading/pull/634)、@xkam7ar さんに感謝）。

- **2026-07-17** 🧩 **correlation-regime skill + バックテスト / データ / ライブ安全性にわたる広範な正確性の総点検**：新しい **correlation-regime** 検出 skill（同梱 skills → 88、[#557](https://github.com/HKUDS/Vibe-Trading/pull/557)、@ebujinovch さんに感謝）、Longbridge のランタイム接続カード（[#569](https://github.com/HKUDS/Vibe-Trading/pull/569)、@fanfpy さんに感謝）、そして `~/.vibe-trading` から読み込むユーザー定義の swarm presets（[#570](https://github.com/HKUDS/Vibe-Trading/pull/570)、@darkknight4563 さんに感謝）。さらにスタック全体にわたる強化：Futu / Tencent / CCXT / mootdx の各 loader におけるサイレントなデータ破損の修正、factor bench と Shadow Account でのルックアヘッドバイアスと strict-OOS のガード、ライブ取引の安全性（符号付きエクスポージャー上限、アトミックな日次注文制限、同意優先の mandate コミット、fail-closed なライブ状態）、および journal / QVeris 予算 / swarm / CI ゲートの改善（[#552](https://github.com/HKUDS/Vibe-Trading/pull/552)、@xor-xe さんに感謝；正確性に関する作業の多くは @xkam7ar によるものです）。

- **2026-07-16** 🔧 **依存関係ロックの修復 + Windows 設定保存の修正**：ハッシュ検証付きランタイムロックを再生成し、Docker の `pip install --require-hashes` が再び正常に解決されるようにして、`caio`/`pydantic-core`/`websockets` の非互換ピンを修正しました（[#564](https://github.com/HKUDS/Vibe-Trading/pull/564)、[#558](https://github.com/HKUDS/Vibe-Trading/issues/558) をクローズ、@tianrking さんに感謝）。Web UI からの Agent LLM 設定の保存が Windows で HTTP 500 を返さなくなりました——POSIX 限定の `os.fchmod` 強化はプラットフォームで分岐し、`fchmod` のない環境向けの回帰テストを追加しています（[#561](https://github.com/HKUDS/Vibe-Trading/pull/561)、@CRui5in さんに感謝）。

- **2026-07-15** 🧮 **バックテストの正確性 + Portfolio Studio コア完成**：10 件の PR をまとめた今回の更新で、リバランスの因果性と順序非依存性、終端決済コスト、約定ベースの回転率、エクスポージャー上限、有限かつ厳格な検証出力を揃えました（[#530](https://github.com/HKUDS/Vibe-Trading/pull/530)/[#531](https://github.com/HKUDS/Vibe-Trading/pull/531)/[#532](https://github.com/HKUDS/Vibe-Trading/pull/532)/[#540](https://github.com/HKUDS/Vibe-Trading/pull/540)）。履歴チャートは実行時のデータソースを再利用し、反復可能な市場クエリは黙って除外されず、`.env` 読み込み後に設定キャッシュを更新します（[#535](https://github.com/HKUDS/Vibe-Trading/pull/535)/[#544](https://github.com/HKUDS/Vibe-Trading/pull/544)/[#554](https://github.com/HKUDS/Vibe-Trading/pull/554)）。Portfolio Studio [#456](https://github.com/HKUDS/Vibe-Trading/issues/456) と設定バグ [#541](https://github.com/HKUDS/Vibe-Trading/issues/541) をクローズし、provider 修正 [#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529) も完了しました。@YZY0108、@santhreal、@Robin1987China、@xkam7ar、@Marnie0415、@marichu99 に感謝します。

- **2026-07-14** 🌉 **Longbridge 市場データ + モダン MCP transport + provider reliability**：Longbridge が、キーで有効化される認証情報、日付ウィンドウ分割、厳格な完全性チェック、オプトイン SDK 依存関係とともに履歴データ fallback 層へ加わりました。中国市場の資金フロー系 4 ツールには検証済み Tushare fallback が追加され、最終純資産が負でもバックテスト指標がクラッシュしません。MCP server は Streamable HTTP に対応し、`write_file` は別名または欠落した path 引数を安全に復元、hypothesis 更新は未対応フィールドを拒否し、Correlation リクエストには認証が付きました。NVIDIA NIM は Web Settings と 2 つの CLI onboarding で first-class provider となり、報告された 403 に対処するバージョン付き互換 User-Agent を送信します。Web Settings は canonical な `~/.vibe-trading/.env` へ書き込み、legacy 設定を移行して権限エラーを明示することで、DeepSeek の保存時 500 を修正しました（[#534](https://github.com/HKUDS/Vibe-Trading/pull/534)、[#516](https://github.com/HKUDS/Vibe-Trading/issues/516)/[#524](https://github.com/HKUDS/Vibe-Trading/issues/524) をクローズ；[#528](https://github.com/HKUDS/Vibe-Trading/issues/528)/[#529](https://github.com/HKUDS/Vibe-Trading/issues/529)）。コード、報告、診断を寄せてくださった @fanfpy、@asahikiko、@santhreal、@sTunnaSu、@abhishekjaisinghani、@huangcheng、@ShiroKSH、@Meru143、@DIEGOD79、@not-knope に感謝します。

- **2026-07-13** 🔒 **セキュリティ強化：外部監査の 10 件をすべてクローズ + contributor batch**：2026-07-10 の外部セキュリティ監査（issue [#476](https://github.com/HKUDS/Vibe-Trading/issues/476)、discussion [#468](https://github.com/HKUDS/Vibe-Trading/discussions/468)）の全 10 件が `main` で対応済みになりました——digest 固定ベースイメージによる Docker マルチステージ再構築、ネットワーク/subprocess/eval/os.environ/安全でない open を（ネストした関数本体の内部も含めて）遮断する AST 硬化バックテストサンドボックス、短命・使い切りの SSE 認証チケット、強化された Compose（read-only rootfs、capabilities 削減、リソース制限）、`/correlation` の認証 + レート制限、セキュリティヘッダー、ハッシュ固定された依存関係、ほか多数。あわせて合流：Alpaca キー分離のオプトイン **TAP モード**（[#377](https://github.com/HKUDS/Vibe-Trading/pull/377)、@0xZKnw さんに感謝）、バックテスト指標への実現ポートフォリオ回転率の反映（[#478](https://github.com/HKUDS/Vibe-Trading/pull/478)、@Robin1987China さんに感謝）、**Frazzini-Pedersen の低ベータプレミアム**アカデミックファクター（Alpha Zoo → 461、[#480](https://github.com/HKUDS/Vibe-Trading/pull/480)、@YogeshModi24 さんに感謝）、5 つのポートフォリオオプティマイザ全体でのルックアヘッドバイアス修正（[#487](https://github.com/HKUDS/Vibe-Trading/pull/487)、@YZY0108 さんに感謝）、そして 2 件の preflight/provider 設定修正（[#479](https://github.com/HKUDS/Vibe-Trading/pull/479)/[#484](https://github.com/HKUDS/Vibe-Trading/pull/484)、[#477](https://github.com/HKUDS/Vibe-Trading/issues/477)/[#482](https://github.com/HKUDS/Vibe-Trading/issues/482) をクローズ、@ananaymital/@Bortlesboat さんに感謝）。

- **2026-07-12** 🧪 **Strategy Development Manager + contributor fix batch**：新しい `strategy-dev-manager` skill（87 個目）は、学術論文やブローカーレポートを登録済みファクター/戦略へ変換し、永続 artifact store と IC/Sharpe の自動減衰モニタリングを備えます —— `sdm_register` / `sdm_status` / `sdm_decay_scan` が active → monitoring → decayed → disabled のライフサイクルを `~/.vibe-trading/` 上で駆動します（[#457](https://github.com/HKUDS/Vibe-Trading/pull/457)、[#455](https://github.com/HKUDS/Vibe-Trading/issues/455) をクローズ、@shadowinlife さんに感謝）。あわせて：Correlation タブが素の ticker（`AAPL,SPY`）を受け付け、loader fallback chain を最後まで辿るようになり（[#472](https://github.com/HKUDS/Vibe-Trading/pull/472)、[#471](https://github.com/HKUDS/Vibe-Trading/issues/471) をクローズ、@yxhuang さんに感謝）、`local` loader は OHLCV リサンプリングで要求 interval を尊重（[#467](https://github.com/HKUDS/Vibe-Trading/pull/467)、@Shizoqua さんに感謝）、Binance USD-M 永続契約の履歴データが明示的な `BTC-USDT-PERP` ルーティング + 約定/マーク価格分離付きで [#462](https://github.com/HKUDS/Vibe-Trading/issues/462) の最初のスライスとして着地（[#470](https://github.com/HKUDS/Vibe-Trading/pull/470)、@honginp さんに感謝）、FastMCP transport imports は両方のモジュールレイアウトで動作します（[#469](https://github.com/HKUDS/Vibe-Trading/pull/469)、@roberttidball さんに感謝）、Requesty が OpenAI 互換 LLM ゲートウェイ provider として利用可能になりました（[#474](https://github.com/HKUDS/Vibe-Trading/pull/474)、@Thibaultjaigu さんに感謝）。

- **2026-07-11** 🚀 **v0.1.11 リリース**（`pip install -U vibe-trading-ai`）：0.1.10 以降の 3 週間分をまとめました——first-class なインド株式（NSE/BSE）バックテスト、PIT-safe なファンダメンタル因子レイヤー（Alpha Zoo → 460）、16 アダプターの IM チャンネルランタイム、エンドツーエンドの定期リサーチ、オプションの QVeris 有料データ、そして本日の contributor batch：turnover を考慮したオプティマイザ（[#466](https://github.com/HKUDS/Vibe-Trading/pull/466)、@Robin1987China さんに感謝）、`analyze_image` ビジョンツール + NapCat DM ペアリング + IM メディア読み取りの修正（[#464](https://github.com/HKUDS/Vibe-Trading/pull/464)/[#463](https://github.com/HKUDS/Vibe-Trading/pull/463)/[#465](https://github.com/HKUDS/Vibe-Trading/issues/465)、@fei-moss さんに感謝）、Longbridge の Decimal シリアライズ（[#459](https://github.com/HKUDS/Vibe-Trading/pull/459)、@fanfpy さんに感謝）、packaged-manifest のカウントガード（[#461](https://github.com/HKUDS/Vibe-Trading/pull/461)、@asahikiko さんに感謝）。詳細：[CHANGELOG](CHANGELOG.md) · [リリースノート](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.11)。

- **2026-07-10** 🇮🇳 **インド株式（NSE/BSE）対応 + 環境変数の一元管理**：専用の `IndiaEquityEngine` を追加——T+1 受渡、値幅制限バンド、config 駆動の STT/印紙税/取引所/SEBI/GST コストスタック——`.NS`/`.BO` シンボルルーティング、読み取り専用の Shoonya/Dhan データブリッジ（オプトイン）を備え、alpha101/qlib158 の 255 ファクターが新しい `equity_in` ユニバースに対応（[#305](https://github.com/HKUDS/Vibe-Trading/pull/305)、@muku314115 に感謝）。環境変数は単一の Pydantic `EnvConfig` スキーマに集約され、AST ベースの CI ゲートが今後の `os.getenv` 散在を防ぎます（[#440](https://github.com/HKUDS/Vibe-Trading/pull/440)、[#438](https://github.com/HKUDS/Vibe-Trading/issues/438) をクローズ、@shadowinlife に感謝）。ほか：実取引 mandate コミット前の確認ダイアログとエラートーストの統一（[#453](https://github.com/HKUDS/Vibe-Trading/pull/453)、@wison1717-maker に感謝）、scheduled-research ルートのテスト（[#452](https://github.com/HKUDS/Vibe-Trading/pull/452)、@Robin1987China に感謝）、zhipu プロバイダで GLM 思考モデルの reasoning ストリームが失われる問題の修正（[#458](https://github.com/HKUDS/Vibe-Trading/issues/458)）。

- **2026-07-09** 🧯 **Docker 起動ブロック解除 + provider/CLI contributor batch**：FastAPI の route 走査で `path` を持たない included-router-like エントリに当たっても、Docker/server startup がクラッシュしなくなりました（[#450](https://github.com/HKUDS/Vibe-Trading/issues/450)、@Penn-Live さんに感謝）。あわせて、キューにあった quick-win contributor fixes も入りました：OKX / Tushare / yfinance の loader `fetch()` signature を protocol と揃え（[#437](https://github.com/HKUDS/Vibe-Trading/pull/437)、@shadowinlife さんに感謝）、CLI resume prompt は最初のユーザーメッセージを保持します（[#448](https://github.com/HKUDS/Vibe-Trading/pull/448)、[#447](https://github.com/HKUDS/Vibe-Trading/issues/447) をクローズ、@morluto さんに感謝）。Codex OAuth default は `openai-codex/gpt-5.4` に更新され（[#446](https://github.com/HKUDS/Vibe-Trading/pull/446)、@morluto さんに感謝）、Kimi for Coding は独立 provider として利用可能になり（[#435](https://github.com/HKUDS/Vibe-Trading/pull/435)、@yxhuang さんに感謝）、opencode provider mapping も接続されました（[#444](https://github.com/HKUDS/Vibe-Trading/pull/444)、@imsankz さんに感謝）。Tushare reference の code fence も `pyhton` から `python` に修正済みです（[#449](https://github.com/HKUDS/Vibe-Trading/pull/449)、@flash1234pku さんに感謝）。検証は focused server/CLI/provider/loader tests、Docker build、`/health` smoke を含みます。

- **2026-07-08** 💎 **ファンダメンタル因子レイヤー（Phase 1）+ オプションの QVeris 有料データ + メンテナンスデー**：PIT-safe な SEC 財務データが日次因子 panel に直接流れ込むようになりました —— `fund:*` panel 列、filed 日アンカリング（リステートメント・YTD フレーム防護付き）、新規クオリティ/バリュー因子 4 本（zoo は 460 alphas に）。データルーティングにオプションの有料トラックを追加：18 の無料ソースが引き続きデフォルトで、QVeris は Settings → QVeris または `vibe-trading data mode paid` から 63+ providers を解放します（下の QVeris セクション参照）。ほかに：`api_server` のモジュール化が完了（1,103 → 371 行、[#424](https://github.com/HKUDS/Vibe-Trading/pull/424) が [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) をクローズ、@shadowinlife さんに感謝）、バックテストの `validation.json` が artifacts ディレクトリの事前存在を要求しなくなり（[#429](https://github.com/HKUDS/Vibe-Trading/pull/429)、@isaveall さんに感謝）、`--swarm-run` のエラーが明確になり（[#428](https://github.com/HKUDS/Vibe-Trading/issues/428)、@isaveall さんに感謝）、セッションチャットを壊した governance stack を revert しました（[#433](https://github.com/HKUDS/Vibe-Trading/issues/433)、的確な診断をくれた @yxhuang さんに感謝）。

- **2026-07-07** ✅ **Contributor PR batch**：キューにあった contributor work を merge しました。IM channel timeout configuration（[#413](https://github.com/HKUDS/Vibe-Trading/pull/413)、@SyntaxSawdust さんに感謝）、Alpha Library social previews と beginner tutorial（[#396](https://github.com/HKUDS/Vibe-Trading/pull/396)、[#393](https://github.com/HKUDS/Vibe-Trading/pull/393)、@kadaliao さんに感謝）、value-investing skills / tools / committee presets（[#407](https://github.com/HKUDS/Vibe-Trading/pull/407)、@sambazhu さんに感謝）、`trading_place_order` の zero-sized order-field handling（[#417](https://github.com/HKUDS/Vibe-Trading/pull/417)、@irfanallana-oss さんに感謝）、session/API paths の timezone-aware UTC timestamps（[#397](https://github.com/HKUDS/Vibe-Trading/pull/397)、@mustafakamal88 さんに感謝）です。

- **2026-07-06** 🧭 **Preflight hardening, API slices, and CN search fallback**：provider preflight は redirect を追わなくなり（[#404](https://github.com/HKUDS/Vibe-Trading/pull/404)、[#402](https://github.com/HKUDS/Vibe-Trading/issues/402) をクローズ、@SyntaxSawdust さんに感謝）、残りの API routes は focused modules に移りました（[#387](https://github.com/HKUDS/Vibe-Trading/pull/387)、[#383](https://github.com/HKUDS/Vibe-Trading/pull/383)-[#386](https://github.com/HKUDS/Vibe-Trading/pull/386) を supersede、@shadowinlife さんに感謝）。CN web-search fallback は Alibaba Cloud IQS を含むようになりました（[#408](https://github.com/HKUDS/Vibe-Trading/pull/408)、@sambazhu さんに感謝）。Maintainer cleanup で no-network fallback tests と EOF whitespace cleanup も追加済みです（[fbac74f](https://github.com/HKUDS/Vibe-Trading/commit/fbac74f77bfed58dd7fc23d0f001c29190b4b2b6)）；main CI は green です（[run 28780619018](https://github.com/HKUDS/Vibe-Trading/actions/runs/28780619018)）。

- **2026-07-05** ✅ **Contributor PR queue closed + Windows baseline green**：今日選んだ 4 つの non-draft PR を merge しました。A-share mootdx の batch pull は bare `except` で `KeyboardInterrupt` / `SystemExit` を飲み込まず、長い取得処理を `Ctrl+C` で止められるようになりました（[#399](https://github.com/HKUDS/Vibe-Trading/pull/399)、[#398](https://github.com/HKUDS/Vibe-Trading/issues/398) をクローズ、@shadowinlife さんに感謝）。Settings route slice と patched dependency floors も元の contributor PR として merge され、credit が残ります（[#382](https://github.com/HKUDS/Vibe-Trading/pull/382)、[#390](https://github.com/HKUDS/Vibe-Trading/pull/390)、@shadowinlife さんと @aeonframework さんに感謝）。Windows baseline compatibility は loader cache isolation、platform-aware OAuth cache assertions、Windows での fork-only mock test skip、MCP loopback fixtures の proxy bypass を含みます（[#401](https://github.com/HKUDS/Vibe-Trading/pull/401)、@Elfsa-Miranda さんに感謝）。Validation: `4701 passed, 47 skipped`。

- **2026-07-04** 🧩 **API route slices, Chinese tutorial docs, and safer dependency floors**：IM channel と Settings routes は `api_server.py` から `src/api/channels_routes.py` / `src/api/settings_routes.py` に移り、[#331](https://github.com/HKUDS/Vibe-Trading/issues/331) の狭い modularization path を継続します（[#379](https://github.com/HKUDS/Vibe-Trading/pull/379)、[#382](https://github.com/HKUDS/Vibe-Trading/pull/382)、@shadowinlife さんに感謝）。Wiki には非金融読者向けの中国語入門チュートリアルが加わり（[#393](https://github.com/HKUDS/Vibe-Trading/pull/393)、@kadaliao さんに感謝）、Pillow / LangChain / LangGraph の dependency floors も installable な patched track に更新されました（[#390](https://github.com/HKUDS/Vibe-Trading/pull/390)、@aeonframework さんに感謝）。

- **2026-07-04** 🧹 **セッション/API パスの UTC タイムスタンプ整理**：#395 のタイムスタンプ修正を強化し、session・goal・channel・API のタイムスタンプが明示的な ISO 形式のタイムゾーン付き UTC 値を出力するようになりました。

- **2026-07-03** 🛡️ **Robinhood MCP refresh + API modularization + SSRF guard**：Robinhood Agentic Trading は generic reads、live-runner plumbing、default read-only seeds、mandate-gate tests のすべてで現在の MCP tool names を使うようになり、interactive startup も provider loader と同じ `.env` 探索順（`~/.vibe-trading/.env` → `agent/.env` → `$CWD/.env`）を尊重します（[#391](https://github.com/HKUDS/Vibe-Trading/pull/391)、[#381](https://github.com/HKUDS/Vibe-Trading/issues/381) と [#380](https://github.com/HKUDS/Vibe-Trading/issues/380) をクローズ）。System routes（`/health`、`/correlation`、`/system/shutdown`、`/skills`、`/api`）は次の狭い API modularization slice として `src/api/system_routes.py` に移りました（[#378](https://github.com/HKUDS/Vibe-Trading/pull/378)、@shadowinlife さんに感謝）。Channel media SSRF defenses は fetch 前に CGNAT/mesh/non-global targets と QQ media redirect-to-internal を拒否するようになりました（[#389](https://github.com/HKUDS/Vibe-Trading/pull/389)、@hobostay さんに感謝）。

- **2026-07-02** ⚡ **Factor acceleration + safer runtime boundaries**：rolling factor のホットパスは `bottleneck`/NumPy fast path を使うようになり、alpha bench の process parallelism は巨大 panel payload を worker ごとに繰り返し渡さず、base equity 計算にも regression coverage が入りました（[#376](https://github.com/HKUDS/Vibe-Trading/pull/376)、[#339](https://github.com/HKUDS/Vibe-Trading/issues/339) をクローズ、元の実装は @shadowinlife さんの [#342](https://github.com/HKUDS/Vibe-Trading/pull/342)）。Upload と Shadow report routes は巨大な `api_server.py` から切り出され、API modularization の最初の狭い slice になりました。[#331](https://github.com/HKUDS/Vibe-Trading/issues/331) は引き続き open です（[#375](https://github.com/HKUDS/Vibe-Trading/pull/375)、[#358](https://github.com/HKUDS/Vibe-Trading/pull/358) ベース、@shadowinlife さんに感謝）。Generated backtest subprocess は parent secrets surface 全体ではなく allowlist された環境だけを継承するようになり（[#374](https://github.com/HKUDS/Vibe-Trading/pull/374)、[#332](https://github.com/HKUDS/Vibe-Trading/issues/332) をクローズ）、IM channels には `/new` session reset と case-insensitive pairing commands も入りました（[#372](https://github.com/HKUDS/Vibe-Trading/pull/372)、[#371](https://github.com/HKUDS/Vibe-Trading/issues/371) をクローズ、@shadowinlife さんに感謝）。

- **2026-07-01** 🧹 **Security polish + tracker cleanup**：API/Docker/frontend dev defaults を締め、Settings channel と `zh-CN` edges を安定化し、frontend dependency/CSP alerts を解消、古い WhatsApp + paper-trading tracker items も整理しました（[#338](https://github.com/HKUDS/Vibe-Trading/pull/338)、[#351](https://github.com/HKUDS/Vibe-Trading/pull/351)、[#349](https://github.com/HKUDS/Vibe-Trading/pull/349)、[#365](https://github.com/HKUDS/Vibe-Trading/pull/365)、[#367](https://github.com/HKUDS/Vibe-Trading/pull/367)、[#350](https://github.com/HKUDS/Vibe-Trading/pull/350)、[#335](https://github.com/HKUDS/Vibe-Trading/pull/335)、[#283](https://github.com/HKUDS/Vibe-Trading/issues/283)）。

- **2026-06-30** 💬 **研究配信用の IM チャンネルランタイム**：Vibe-Trading は同じ agent session runtime を 16 の組み込み message adapter に接続できるようになりました——WebSocket、Telegram、Slack、Discord、Matrix、WhatsApp、Signal、QQ/NapCat、WeChat/WeCom、Feishu/Lark、DingTalk、Teams、email、Mochat。CLI（`vibe-trading channels status/start/stop/login/pairing`）、REST（`/channels/status`、`/channels/start`、`/channels/stop`、`/channels/pairing/command`）、Web UI Settings panel が status、recovery hints、start/stop、sender pairing を扱い、SDK-backed adapters は `vibe-trading-ai[telegram]` や `vibe-trading-ai[channels]` などの extras の背後に残ります（[#341](https://github.com/HKUDS/Vibe-Trading/pull/341)）。

- **2026-06-29** 🛡️ **Live advisory safety + Trading 212 read-only connector + Windows/Gemini fixes**: live order guards now have an opt-in, broker-agnostic `PreTradeAdvisoryInterface` that records advisory reviews without bypassing the mandate gate, kill switch, or audit trail ([#328](https://github.com/HKUDS/Vibe-Trading/pull/328), closes [#317](https://github.com/HKUDS/Vibe-Trading/issues/317), thanks @shadowinlife). Trading 212 joins the connector layer with read-only account, positions, orders, history, and instrument-metadata support; `place_order` / `cancel_order` still hard-refuse until a structural paper/live boundary exists ([#321](https://github.com/HKUDS/Vibe-Trading/pull/321), closes [#309](https://github.com/HKUDS/Vibe-Trading/issues/309), thanks @mvanhorn). Windows startup avoids the pandas 3.0 `Timestamp` crash via the `<3.0.0` constraint ([#329](https://github.com/HKUDS/Vibe-Trading/pull/329), closes [#324](https://github.com/HKUDS/Vibe-Trading/issues/324), thanks @hannibal-lee); Gemini `thought_signature` dict-history replay was verified/fixed on `main` ([#318](https://github.com/HKUDS/Vibe-Trading/issues/318)); `.US` financial statements now route to SEC EDGAR instead of Eastmoney ([#325](https://github.com/HKUDS/Vibe-Trading/issues/325)); and the Alpha Library landing page got cache/date/selector/noscript/DNS-prefetch hardening while heavier CSP and social-card follow-ups stay tracked ([#323](https://github.com/HKUDS/Vibe-Trading/issues/323)).

- **2026-06-28** 🧰 **クロスプラットフォーム setup/dev + runtime と file tool の強化**：`vibe-trading setup` と `vibe-trading dev` は、Windows の TypeScript build、正しい cwd からの backend 起動、Vite の 5899 port、終了時の子プロセス cleanup を正しく扱うようになりました（[#292](https://github.com/HKUDS/Vibe-Trading/pull/292)、@digger-yu さんに感謝）。Runtime status polling はクラッシュせず graceful に degrade し（[#322](https://github.com/HKUDS/Vibe-Trading/issues/322)）、MCP OAuth cache key は sanitize され（[#313](https://github.com/HKUDS/Vibe-Trading/issues/313)）、OpenAI default と Robinhood `agent.json` validation も強化されました（[#319](https://github.com/HKUDS/Vibe-Trading/pull/319)、[#320](https://github.com/HKUDS/Vibe-Trading/pull/320)、@mvanhorn さんに感謝）。File tools には独立した read/write roots と sandbox tests の拡充も入りました（[#299](https://github.com/HKUDS/Vibe-Trading/pull/299)、@skloxo さんに感謝）。
- **2026-06-27** 🧯 **Content-filter resilience + Shadow Account feature contract cleanup**：event-driven / swarm run は、個別の LLM content-moderation hit をスキップし、filter rate が高い場合は run card で警告し、Gemini safety finish reason を認識して analysis 全体を abort しないようになりました（[#308](https://github.com/HKUDS/Vibe-Trading/pull/308)、[#307](https://github.com/HKUDS/Vibe-Trading/issues/307) をクローズ、@shadowinlife さんに感謝）。Shadow Account の extraction/codegen は同じ `PRICE_FEATURES` contract を共有し、4 桁小数の return bounds を保つことで、rule/codegen drift と `prior_5d_return` の精度落ちを防ぎます（[#316](https://github.com/HKUDS/Vibe-Trading/pull/316)、@Robin1987China さんに感謝）。
- **2026-06-26** 🎯 **Shadow Account の条件付きエントリー + tushare ETF/指数/HK ルーティング**：抽出された Shadow Account ルールが RSI / prior-return のレンジを持つようになり、生成される SignalEngine は保有サイクルを盲目的に再生せず、実際の条件（RSI がレンジ内、prior-return がレンジ内）でエントリーします（[#314](https://github.com/HKUDS/Vibe-Trading/pull/314)、[#302](https://github.com/HKUDS/Vibe-Trading/pull/302) の follow-up、@Robin1987China さんに感謝）。tushare loader も ETF/LOF を `fund_daily()`、指数を `index_daily()`、香港株を `hk_daily()` にルーティングし、非株式に対して静かに空を返す `daily()` を常に呼ぶのをやめ、銘柄ごとの空結果 + 部分取得の警告を追加しました（[#315](https://github.com/HKUDS/Vibe-Trading/pull/315)、[#310](https://github.com/HKUDS/Vibe-Trading/issues/310) をクローズ、@shadowinlife さんに感謝）。
- **2026-06-25** 🧪 **strict validation JSON + 落ち着いた agent context**：単独のバックテスト validation は、`artifacts/validation.json` や CLI stdout に書き出す前に入れ子の `NaN` / `Infinity` を正規化するようになり、strict JSON parser が validation payload で詰まらなくなりました（[#306](https://github.com/HKUDS/Vibe-Trading/pull/306)、@gyx09212214-prog さんに感謝）。Agent prompt も loader registry から現在の data-source 数を動的に導出し、`_microcompact()` は本当に token pressure がある時だけ動くため、短い実行で古い tool result が早すぎるタイミングで消されません（[#296](https://github.com/HKUDS/Vibe-Trading/pull/296)、[#282](https://github.com/HKUDS/Vibe-Trading/issues/282) をクローズ、@MarkfuGod さんに感謝）。
- **2026-06-24** 🎯 **Shadow Account の価格コンテキスト + reactive Chinese UI + LAN auth 修正**：Shadow Account のルール抽出は、`buy_dt` 時点の point-in-time-safe な entry context（`entry_rsi14` と `prior_5d_return`）を loader registry 経由で読めるようになり、offline / no-data では従来どおり graceful に落ちます（[#302](https://github.com/HKUDS/Vibe-Trading/pull/302)、[#295](https://github.com/HKUDS/Vibe-Trading/issues/295) の follow-up、@Robin1987China さんに感謝）。Web UI の主要パネルは charts、chat、Alpha Library、Correlation、Run Detail まで reactive English / zh-CN translation に寄せました（[#301](https://github.com/HKUDS/Vibe-Trading/pull/301)、@skloxo さんに感謝）。CSRF hardening 後も、`API_AUTH_KEY` を設定した remote same-origin Web UI deployment は POST / upload が通る一方、mismatch した cross-site origin は引き続き拒否されます（[#304](https://github.com/HKUDS/Vibe-Trading/pull/304)、@Hinotoi-agent さんに感謝）。
- **2026-06-23** 🛡️ **ローカル API の CSRF 対策強化**：悪意あるウェブページがループバック API に対して安全でないクロスサイトリクエスト（POST/PUT/DELETE）を発行できなくなりました——CORS はレスポンスの読み取りは防げても副作用は防げないため、ループバックの dev-mode 信頼を認める**前**に、安全でないメソッドへ既存のクロスサイトガードを適用します。安全なメソッドとローカル CLI / 非ブラウザのアップロードには影響しません（[#293](https://github.com/HKUDS/Vibe-Trading/pull/293)、@Hinotoi-agent さんに感謝）。
- **2026-06-22** 🔧 **ライブ認可の OAuth 修正 + Alpha Zoo 見出しの修正**：`connector authorize` が数分かかるブローカーのサインインの間も OAuth ハンドシェイクを維持し（`VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS` で調整可能）、リトライ時に競合するコールバックサーバーを起動しなくなったため、トークンが確実に保存されます（[#281](https://github.com/HKUDS/Vibe-Trading/pull/281)、[#259](https://github.com/HKUDS/Vibe-Trading/issues/259) をクローズ、@Robin1987China さんに感謝）。Alpha Zoo ページが alpha 数を二重に表示しなくなりました（[#287](https://github.com/HKUDS/Vibe-Trading/pull/287)、[#286](https://github.com/HKUDS/Vibe-Trading/issues/286) をクローズ、@digger-yu さんに感謝）。定期リサーチにも端から端までの使い方ドキュメントが追加されました（[#288](https://github.com/HKUDS/Vibe-Trading/pull/288)）。
- **2026-06-21** ⏰ **定期リサーチ実行エンジン + レポートライブラリ + バックテスト後アトリビューション**：定期リサーチが**エンドツーエンド**で動作するようになりました——デフォルト無効のバックグラウンド実行エンジン（`VIBE_TRADING_ENABLE_SCHEDULER`）が interval/cron で期限到来ジョブをセッションランタイム経由で実行します（[#278](https://github.com/HKUDS/Vibe-Trading/pull/278)、@mvanhorn さんに感謝、[#254](https://github.com/HKUDS/Vibe-Trading/issues/254) をクローズ）。新しい **`/reports` 実行ライブラリ**ページでは、レポートを生成した実行を一覧・検索・フィルタでき、Run Detail + Compare へのリンクも備えます（[#224](https://github.com/HKUDS/Vibe-Trading/pull/224)、@LemonCANDY42 さんに感謝）。さらにバックテストのたびにエージェントが**階層型アトリビューション**——取引レベルの勝ち/負けトップ、ベータ回帰、市場レジーム分析、モンテカルロ並べ替え検定——をデータの有無とルーティング条件に応じて自動実行します（[#280](https://github.com/HKUDS/Vibe-Trading/pull/280)、@shadowinlife さんに感謝）。
- **2026-06-20** 🔬 **Research Autopilot のループが完結（フェーズ3）+ ローダー OHLC 整合性ガード + 学術アルファ4本**：**Research Autopilot** が **仮説 → シグナルエンジン → バックテスト** をエンドツーエンドで実行します——`scaffold_signal_engine` が runner 契約に準拠したエンジンを生成し、`link_autopilot_backtest` がバックテスト指標を仮説へ自動で書き戻します（**68 ツール**）（[#267](https://github.com/HKUDS/Vibe-Trading/pull/267)）。構造的な **OHLC 健全性チェック**がローダー境界で不正な bar（`high < low`、非正の価格、high/low が open/close を包含しない）を一括除去し、すべてのデータソースを保護します（[#274](https://github.com/HKUDS/Vibe-Trading/pull/274)、@Shizoqua さんに感謝）。さらに **academic アルファファミリーが 6 → 10 に拡大**——Jegadeesh リバーサル、George-Hwang 52週高値、Amihud 非流動性、Harvey-Siddique 歪度（**456 ファクター**）（[#277](https://github.com/HKUDS/Vibe-Trading/pull/277)、@Robin1987China さんに感謝）。
- **2026-06-19** 🚀 **v0.1.10 — グローバルデータレイヤー**：市場データソースが 10 → 18 に拡大（無料の **Eastmoney / Sina / Stooq / Yahoo** + キー必須の **Finnhub / Alpha Vantage / Tiingo / FMP**、IP-ban リスク順の fallback）。さらに **18 個の読み取り専用データツール**（資金フロー、龍虎榜、北向き、信用取引、大口取引、SEC EDGAR + XBRL、財務、オプションチェーン、全市場スクリーニング…）を A 株 / 米国 / 香港にまたがり、すべて MCP 経由で公開。本リリースは 0.1.9 以降の全更新も同梱——10 のブローカーコネクタ、`alpha compare`、プロバイダ信頼性の大規模改修、任意のデータキャッシュ。`pip install -U vibe-trading-ai`
- **2026-06-18** 🔬 **Research Autopilot 第1フェーズ + ローカル Data Bridge ローダー、加えて Discord セキュリティ通知**：新しい `run_research_autopilot` + `generate_backtest_config` が **Hypothesis → Research Goal → backtest** を端から端までつなぎ（現在 **50 ツール**）、新しい **`local`** ローダーは自分の **CSV / Parquet / DuckDB** ファイルから直接 OHLCV を読み込みます（[#260](https://github.com/HKUDS/Vibe-Trading/pull/260)、[#252](https://github.com/HKUDS/Vibe-Trading/pull/252)、@Robin1987China さんに感謝）。さらに DeepSeek `DSML` ツール呼び出しの解析と識別子封じ込め強化も入りました。⚠️ **セキュリティ通知**：以前のコミュニティ Discord 招待は、現在管理していないサーバー（偽の Collab.Land ウォレット「認証」フィッシング）に解決されます——すべて削除済みで、**唯一**の公式 Discord は HKUDS サーバー（[discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)）です。ウォレット接続を求めることは決してありません。
- **2026-06-17** 🧩 **インストール互換性 + Opus/Kimi プロバイダ修正**：通常の `pip install vibe-trading-ai` では、任意機能の `pyharmonics` / `ta` 依存チェーンを引かなくなりました。harmonic detection は `vibe-trading-ai[harmonic]` extra の背後に移しつつ、同梱 fallback detector はそのまま使えます（[#250](https://github.com/HKUDS/Vibe-Trading/pull/250)、[#249](https://github.com/HKUDS/Vibe-Trading/issues/249) をクローズ）。Agent loop は Opus 4.8+ が拒否する assistant-prefill handoff message を送らなくなり、Kimi/Moonshot は `MOONSHOT_USER_AGENT` で client `User-Agent` を上書きできます（[#248](https://github.com/HKUDS/Vibe-Trading/pull/248)、[#246](https://github.com/HKUDS/Vibe-Trading/issues/246) と [#204](https://github.com/HKUDS/Vibe-Trading/issues/204) をクローズ）。follow-up tests は background-result と auto-compact の handoff 経路を直接カバーします（[#251](https://github.com/HKUDS/Vibe-Trading/pull/251)）。
- **2026-06-16** 🛡️ **セキュリティ/API 強化 + GLM/Zhipu alias**：Settings 書き込みは認証設定時に auth 必須になりました（[#245](https://github.com/HKUDS/Vibe-Trading/pull/245)）；API session の shell-capable tools は明示的な `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` opt-in が必要です（[#243](https://github.com/HKUDS/Vibe-Trading/pull/243)）；API key 設定時の local shutdown も auth 必須です（[#241](https://github.com/HKUDS/Vibe-Trading/pull/241)）；loopback に見えるが信頼できない Host は local 扱いせず拒否します（[#242](https://github.com/HKUDS/Vibe-Trading/pull/242)）。実行時の細部も改善: Web chat は完了済み attempts と同期し（[#236](https://github.com/HKUDS/Vibe-Trading/pull/236)）、run card は非有限メトリクスを strict JSON として出力（[#238](https://github.com/HKUDS/Vibe-Trading/pull/238)）、不正な `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` は安全に fallback（[#240](https://github.com/HKUDS/Vibe-Trading/pull/240)）、ddgs retry fallback は regression coverage 付きです（[#239](https://github.com/HKUDS/Vibe-Trading/pull/239)）。GLM/Zhipu は first-class provider alias となり、model-name inference も追加されました（[#247](https://github.com/HKUDS/Vibe-Trading/pull/247)、[#237](https://github.com/HKUDS/Vibe-Trading/issues/237) をクローズ）。

- **2026-06-15** 🧭 **Web 検索の堅牢化 + Web UI のラン継続性修正**：`web_search` は単一エンジンがレート制限されても失敗しなくなりました——複数の無料・キー不要のエンジン（DuckDuckGo、Google、Bing、Brave、Mojeek、Yahoo）を順に照会し、リトライ/バックオフを行い、「結果なし」をエラーではなく空の回答として扱い、すべてのエンジンが制限された場合は素っ気ない ❌ ではなく実行可能なメッセージを返します（エンジン一覧は `VIBE_TRADING_SEARCH_BACKENDS` で上書き可能）（[#232](https://github.com/HKUDS/Vibe-Trading/pull/232)、[#231](https://github.com/HKUDS/Vibe-Trading/issues/231) をクローズ、@Ethan-sun01 さんに感謝）。Web UI では、ラン中にページを切り替えても固まらなくなりました——チャットは戻った際にライブストリームへ再購読し、見逃した進捗を再生します（[#234](https://github.com/HKUDS/Vibe-Trading/pull/234)）——そして停止ボタンはイテレーション境界だけでなく、ストリーミング中やツール間でも有効になりました（[#235](https://github.com/HKUDS/Vibe-Trading/pull/235)）。これにより [#229](https://github.com/HKUDS/Vibe-Trading/issues/229) の両方が解決します（@kalkinj さんに感謝）。baostock loader は tushare 形式の `601398.SH` に加え、ネイティブの `sh.601398` / `sz.000001` コードも受け付けるようになりました（[#230](https://github.com/HKUDS/Vibe-Trading/pull/230)、@bhlt さんに感謝）。

- **2026-06-14** 📊 **ラン単位のトークン使用量 + Run Detail チャートの遅延読み込み**: 各 agent ランは、プロバイダ報告のトークン使用量をラン単位の `llm_usage.json` として永続化するようになりました——プロバイダ/モデル、累計合計、イテレーションごとの件数——`/runs/{id}` に追加的に提供されるため、ランが終わってライブストリームが消えた後もトークンコストを監査できます（プロバイダ報告値のみ；prompt/内容のキャプチャや価格推定はなし）（[#223](https://github.com/HKUDS/Vibe-Trading/pull/223)、@LemonCANDY42 さんに感謝）。Run Detail ページは、もはや全シンボルのローソク足を最初に読み込みません: 既定の `/runs/{id}` レスポンスは変更なしのまま、UI はまずランのサマリーを描画し、オプトインの `?chart_payload=summary` / `?chart_symbol=` モードで各シンボルのチャートをオンデマンドに読み込みます。シンボルごとの読み込み状態と「全件読み込み + 進捗」コントロール付きです（[#225](https://github.com/HKUDS/Vibe-Trading/pull/225)、@LemonCANDY42 さんに感謝）。2 つの loader 修正で締めくくり: yfinance の排他的な `end` 境界が、要求範囲の最終取引日を取りこぼさなくなりました——ダウンロード呼び出しは `end + 1 日` を渡し、キャッシュキーは元の範囲を保持します（[#226](https://github.com/HKUDS/Vibe-Trading/pull/226)、@gyx09212214-prog さんに感謝）——そして不正な `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` 値は、import 時に例外を投げて起動を妨げる代わりに、警告して既定値にフォールバックするようになりました（[#227](https://github.com/HKUDS/Vibe-Trading/pull/227)、@gyx09212214-prog さんに感謝）。
- **2026-06-13** ↩️ **CLI からセッションを ID で再開**: インタラクティブ CLI が終了時に session-id を表示し、コピペ可能な `vibe-trading resume <session-id>` のヒントも添えるようになりました——終了したランの trace を探すのに、`agent/sessions/` 配下のどのフォルダがタイムスタンプ的に最新かを当てる必要はもうありません。新しい `vibe-trading resume <session-id>` サブコマンドはその正確なセッションを再び開き、直近のターンを loop に再生します；存在しない id は空のセッションを黙って始めるのではなく即座にエラーで終了します（[#218](https://github.com/HKUDS/Vibe-Trading/pull/218)、@zwrong さんに感謝）。
- **2026-06-12** 🩺 **プロバイダ信頼性の全面強化——DeepSeek ハング、Kimi 接続、ストリーミング死活**：一連のプロバイダ報告——DeepSeek 実行が「Agent is working…」で停止（[#208](https://github.com/HKUDS/Vibe-Trading/issues/208)、@XYWOX さんに感謝）、`reached max iterations` がモデルの空応答を覆い隠す（[#203](https://github.com/HKUDS/Vibe-Trading/issues/203)、@mojianliang さんに感謝）、停止後に UI が復帰しない（[#195](https://github.com/HKUDS/Vibe-Trading/issues/195)、@mafia23 さんに感謝）、Kimi がクライアントを拒否（[#204](https://github.com/HKUDS/Vibe-Trading/issues/204)、@liao497 さんに感謝）——の根因は一つでした：すべての OpenAI 互換プロバイダが単一の shim を共有し、DeepSeek/Kimi/Gemini 固有の挙動をグローバルに適用し、ストリーム失敗を黙って握りつぶしていました。プロバイダ固有の挙動は明示的な**ケイパビリティ層**に移行——reasoning の捕捉/再送、Gemini thought signature、Kimi の `User-Agent`、OpenRouter の reasoning body はそれぞれ自分のプロバイダにのみ適用され、相互汚染しません。reasoning のみのストリームはリアルタイムの**「Reasoning…」**インジケータを表示；ストリーム失敗は文脈付きの `provider_stream_error` を送出し、一時的な切断は 1 回だけ自動リトライ（決定的な 4xx は即時失敗）、遅い非ストリーミング呼び出しへの静かなフォールバックは廃止；モデルの空応答は `empty_model_response` として正しく診断；SSE ハートビートが再接続リプレイを壊さなくなり；スタックした読み取り専用ツールはタイムアウトします。新コマンド **`vibe-trading provider doctor`** は秘匿化済みの provider/モデル/パッケージ/プロキシのスナップショットを出力し、環境起因のハングをワンコマンドで切り分け。DeepSeek は `pip install "vibe-trading-ai[deepseek]"` で公式ネイティブアダプタを選択でき、kimi-k2.x の `temperature=1` 要件は自動適用——Kimi 経路は実 API でエンドツーエンド検証済みです（`kimi-k2.6` のツール呼び出し + 厳格なマルチターン reasoning 再送）。

- **2026-06-11** 🐝 **swarm worker が loader 層経由で市場データを取得するように**: NVDA の投資委員会ランで一連のギャップが露呈しました——worker が場当たり的な yfinance スクリプトを書き、欠損した最新バー（出来高はあるが OHLC が空）を信じ、`NaN` が非厳密 JSON に漏れ、コンテキストを失った継続プロンプトが誤った preset にルーティングされていました（[#198](https://github.com/HKUDS/Vibe-Trading/issues/198)、卓越した診断と 2 つの修正 PR を寄せてくれた @BillDin さんに感謝）。swarm worker は MCP と同じ正規化 loader レジストリに裏打ちされたローカル `get_market_data` ツールを獲得——厳密 JSON、非有限浮動小数は `null` として直列化——**すべての市場データ系 preset**（13 preset、21 worker）に配線され、プロンプトポリシーが OHLCV 作業をツール優先に誘導します（[#199](https://github.com/HKUDS/Vibe-Trading/pull/199)）。`run_swarm` は明示的な `preset_name` を受け取り、曖昧な継続フラグメントは `equity_research_team` へ静かにフォールバックせず拒否されます（[#200](https://github.com/HKUDS/Vibe-Trading/pull/200)）。グラウンディングも賢くなりました: swarm プロンプト内の裸の米国ティッカー（例 `NVDA`）は `NVDA.US` に昇格され（ストップワードでガード）、worker は最初から権威ある事前取得価格を手にします。このツールはメイン agent レジストリにも加わり——現在 **48 ツール**です。さらに: **Docker のデータがアップデートを跨いで保持されるように**——永続メモリ、セッション検索インデックス、ユーザー作成スキル、shadow account、broker 設定は名前付きボリュームに置かれ、`docker compose up --build` でも消えません（[#197](https://github.com/HKUDS/Vibe-Trading/issues/197)、@FlyerJ さんに感謝）。
- **2026-06-10** 🐳 **Docker からホスト側 Ollama に標準で到達可能に**: コンテナ内の `localhost` はコンテナ自身を指すため、既定の `OLLAMA_BASE_URL=http://localhost:11434` では Docker + Ollama 構成の LLM プリフライトが必ず失敗していました。`docker-compose.yml` は既定で `http://host.docker.internal:11434` を指すようになり（`OLLAMA_BASE_URL` のエクスポートで上書き可）、`host-gateway` の `extra_hosts` マッピングも追加され、Docker Desktop だけでなく Linux でも同じファイルがそのまま動きます（[#196](https://github.com/HKUDS/Vibe-Trading/pull/196)、@ShahNewazKhan さんに感謝）。
- **2026-06-09** 🔑 **別マシンから Web UI を開いたときのエラーをより明確に**: `API_AUTH_KEY` 未設定のまま非ループバッククライアント（別のマシン、VM ホスト、LAN 上のスマートフォン）からチャットにアクセスすると、メッセージ送信・セッション一覧・live ステータスなどすべての機微なエンドポイントが `403` を返していましたが、チャットには汎用的な「Failed to send message, please retry.」しか表示されませんでした。送信パスが本当の理由——*「Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.」*——を表示するようになり、README の Web UI セットアップも localhost と LAN の違いと 3 つの対処法（同じマシンで `localhost` を使う／`API_AUTH_KEY` を設定して Settings に一度入力する／Docker Desktop のホストゲートウェイには `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1`）を明記しました（[#191](https://github.com/HKUDS/Vibe-Trading/issues/191)、@mafia23 さんに感謝）。
- **2026-06-08** 🔧 **Gemini 3.x マルチターンのツール呼び出し修正**: Gemini 3.x の思考モデル修正が完成しました。6/05 のラウンドトリップ（[#176](https://github.com/HKUDS/Vibe-Trading/pull/176)）は in-memory 履歴のみを対象にしていましたが、実際の agent loop は履歴を OpenAI 形式の dict で再生し、LangChain がリクエスト構築前にツール呼び出しごとの `thought_signature` を捨てていたため、マルチターンのツール呼び出しが依然 `missing thought_signature` で 400 になっていました。これが `invoke` と `stream` が共有する唯一のチョークポイント `_convert_input` で再付与されるようになりました（並列呼び出し——N 個のうち最初の 1 つだけ署名される——も対象）（[#184](https://github.com/HKUDS/Vibe-Trading/pull/184)、@ngoanpv さんに感謝）。
- **2026-06-07** 🐝 **チャットのタイムラインにライブ swarm ステータス**: agent がマルチエージェント swarm（投資委員会、クオンツデスク、リスク委員会……）を起動すると、チャットに各 worker の状態——待機 / 実行中 / 完了 / 失敗 / ブロック / リトライ——をリアルタイムにストリーミングするインライン**ステータスカード**が表示されるようになりました。独立した swarm ダッシュボードと同じエージェント単位の可視性です。ランタイムイベントは既存の `/swarm/runs` API を変えずにセッション SSE ストリームへブリッジされ、再接続や履歴再生時には完了済みカードが最終的な `run_swarm` 結果から復元されます（[#188](https://github.com/HKUDS/Vibe-Trading/pull/188)、@BillDin さんに感謝）。preset ルーティングも精密に: 明示的に指定された preset（例 `investment_committee`、アンダースコアの有無を問わず）がキーワードスコアより優先され、裸の `IV` デリバティブキーワードが「g**iv**en」のような普通の単語に誤マッチしなくなりました（[#189](https://github.com/HKUDS/Vibe-Trading/pull/189)、@BillDin さんに感謝）。
- **2026-06-06** ⚖️ **Alpha 比較 —— CLI / Web UI / REST / agent の全面対応**: 新しい `alpha compare` は、手で選んだ Alpha Zoo ファクターのショートリストを同じ universe・期間で総当たり比較し、IC 平均/標準偏差・IR・IC>0 比率・サンプル数で順位付けして、各ファクターのトップとの差を示します。zoo 全体の bench と違い、**指定したファクターだけ**を評価します（新しい `run_bench(only=…)` のサブセットフィルタ）。3 つを比較しても zoo の 191 個すべてを走らせません。1 つの共有コアがすべての面を支えます: `vibe-trading alpha compare <id1> <id2> … --sort ir`（CLI）、Alpha Zoo Web UI の **Compare ビュー**（カタログでファクターをチェック → ワンクリック比較 + ストリーミング順位表）、`POST /alpha/compare` + SSE（REST）、読み取り専用の `alpha_compare` agent ツール（**47 ツール**に）。
- **2026-06-05** 🇮🇳 **Dhan + Shoonya connector（インド）——ブローカー計 10 社**: connector-first の取引レイヤーにインド市場向けの **Dhan** と **Shoonya**（NSE/BSE 株式 + F&O）を追加し、ブローカーは計 10 社になりました。どちらも**ペーパー + 読み取り専用**です——Longbridge と同様、API がランタイムのペーパー/live 判別子を公開しないため、`place_order` / `cancel_order` は最初の行で非ペーパー設定を硬く拒否します（ルール: ランタイムのペーパー/live ガードを持たないブローカーはペーパー + 読み取り専用に制限）（[#181](https://github.com/HKUDS/Vibe-Trading/pull/181)、[#174](https://github.com/HKUDS/Vibe-Trading/issues/174) をクローズ）。今回は **Gemini 2.5 / 3.x の思考モデル**も修正: ツール呼び出しごとの `thoughtSignature` が OpenAI 互換パスを往復するようになり、マルチターンの function calling が `INVALID_ARGUMENT` で失敗しなくなりました（[#176](https://github.com/HKUDS/Vibe-Trading/pull/176)、[#170](https://github.com/HKUDS/Vibe-Trading/issues/170) をクローズ、@mvanhorn さん & @jliu6789 さんに感謝）。**452 個すべての Alpha Zoo ファクター**に中国語 docstring（中文名称/说明/用途）が追加され（[#180](https://github.com/HKUDS/Vibe-Trading/pull/180)、@LeeCQiang さんに感謝）、**フロントエンドのテストスイート（vitest 197 件）**とバックエンドの認証 / パストラバーサル / CORS セキュリティテストが CI に加わりました（[#175](https://github.com/HKUDS/Vibe-Trading/pull/175)、@sambazhu さんに感謝）。
- **2026-06-04** 🗃️ **全 7 データソース対応のオプトインローカルキャッシュ**: 新しい `VIBE_TRADING_DATA_CACHE` スイッチにより、各バックテスト loader——tushare、okx、ccxt、akshare、mootdx、yfinance、futu——が確定済みの過去 bar を `~/.vibe-trading/cache`（ユーザーホーム、リポジトリには決して書き込まない）にキャッシュし、繰り返しおよび長期 / クロスマーケットのバックテストがネットワークを省略してプロバイダーのレート制限を回避できます。デフォルトはオフ。バッチ / 接続型 loader（yfinance、futu）はキャッシュが全ヒットすると一括ダウンロード / FutuOpenD 接続を完全にスキップし、staleness ガードは当日で終わる範囲（最後の bar がまだ形成中）を決してキャッシュせず、キャッシュされたフレームは新規取得とバイト単位で一致します（[#177](https://github.com/HKUDS/Vibe-Trading/pull/177)、@mvanhorn さんに感謝）。AI / 自動化支援 PR 向けのコントリビューターガイドも追加され、安全なローカルチェックと高リスクな broker/MCP/認証情報の領域を整理しています（[#173](https://github.com/HKUDS/Vibe-Trading/pull/173)）。
- **2026-06-03** 🧹 **コミュニティトリアージ + トレース相関**: ツール呼び出しのトレースエントリに発信元の `call_id` が付与され、run トレースの再生時に `tool_result` を対応する `tool_call` に突き合わせられます——引数プレビューはトレースファイルを小さく保つため切り詰めたままです（[#168](https://github.com/HKUDS/Vibe-Trading/pull/168)、@zwrong さんに感謝）。ソースコードのコメントは、外部コントリビューターが見つけられない内部専用のドキュメントパスを指さなくなりました（[#166](https://github.com/HKUDS/Vibe-Trading/issues/166)、@jaleelpersonal さんに感謝）。また、インストール時の `langchain-community` の依存解決の警告は失敗ではなく残存パッケージによる無害な通知であることを明確化し（[#167](https://github.com/HKUDS/Vibe-Trading/issues/167)）、Gemini 2.5/3.0 の関数呼び出しにおける `thoughtSignature` の往復処理を、完全な修正計画付きの `help wanted` タスクとして整理しました（[#170](https://github.com/HKUDS/Vibe-Trading/issues/170)、@jliu6789 さんに感謝）。
- **2026-06-02** 🔌 **6 つの新しいブローカー connector（Tiger / Longbridge / Alpaca / OKX / Binance / Futu）**: connector-first の取引レイヤーに、IBKR（ローカル）と Robinhood（MCP）に加えて直接 SDK トランスポートが加わりました。各 connector は読み取り専用の account / positions / orders / quote / history に加え、ペーパー口座での発注を公開します——これらのブローカーのペーパー口座で戦略を検証できます。Tiger / Alpaca / OKX / Binance / Futu の 5 つは、Robinhood と同じ安全モデルの背後で、有界かつ mandate でゲートされた発注にも対応します: ユーザーがコミットした mandate（銘柄ユニバース／注文サイズ／エクスポージャー／レバレッジ／日次上限）、ファイルレベルの kill switch、fail-closed の発注前ゲート、完全な監査台帳。Longbridge はペーパー + 読み取り専用のみです（API がランタイムでのペーパー/live 判別子を公開しないため）。すべてのペーパー/live の区別はブローカー単位の構造的ガードです。新しい `trading_place_order` / `trading_cancel_order` ツールを追加し、mandate ユニバースに香港株と A 株のアセットクラスを追加しました。実験的 / 自己責任でご利用ください。
- **2026-06-01** 🚀 **v0.1.9 リリース**（`pip install -U vibe-trading-ai`）: 0.1.8 以降のすべてをまとめました。Connector-first ブローカー profile（IBKR ローカル読み取り専用 TWS / IB Gateway + OAuth・コミット済み mandate・order guard・audit ledger・instant halt の背後にある Robinhood Agentic Trading）。CLI / REST / MCP / Web を貫く Research Goal ランタイム。swarm 強化——live reconcile + MCP keepalive、operator 設定の worker MCP ツール、厳格 alpha-bench ランダムコントロール、失敗/stale run を再実行する新 `retry_run`（現在 **36 MCP tools**）。`agent/cli/` パッケージ refactor + 刷新したターミナル UI、`mootdx` トークン不要の A 株 loader、backtest / agent loop / session の堅牢性 pass。`--version` は常にインストール済みパッケージと一致し、0.1.8 のドリフトを修正（[#156](https://github.com/HKUDS/Vibe-Trading/issues/156)）。
- **2026-05-31** 🔌 **Connector-first ブローカーアーキテクチャ（IBKR + Robinhood）**: 取引アクセスは、個別のブローカー入口や live 入口ではなく、選択可能な connector profile から始まるようになりました。`vibe-trading connector list/use/check/account/positions/orders/quote/history` と MCP の `trading_*` ツールは同じ選択済み profile を共有し、paper/live は connector 配下の属性として扱われます。IBKR はローカル読み取り専用 TWS / IB Gateway profile ですぐ使え、公式 IBKR リモート MCP は安定した read tool 名が公開されるまで OAuth `mcp.read` probe として seed されています。Robinhood Agentic Trading は引き続き、OAuth、コミット済み mandate、order guard、audit ledger、instant halt の背後にある bounded live MCP connector です。
- **2026-05-30** 🧰 **堅牢性パス — backtest、agent loop、session**: LLM 生成の signal engine は、インスタンス化の前にインターフェース事前検証を通すようになりました。循環 self-import、`generate()` の欠落、デフォルト値のない `__init__` 引数、誤った戻り値型といった典型ミスを早期に捕捉し、生の traceback ではなく実行可能な JSON エラーで返します ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149))。続くフォローアップで、ソースレベルの AST 検証エラーも同じクリーンな JSON エンベロープに乗せました。agent loop は 50 反復を使い切って出力のない `failed` 状態に陥らなくなりました——swarm worker の実績ある方式に倣い、反復予算の 80% で wrap-up nudge を注入し、最後の反復で tool 定義を外してテキスト回答を強制します ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148))。途中でのみ発火するようガードしてあり、research-goal の文脈を押しのけることはありません。session のメッセージ書き込みは append ごとに `flush + fsync` するようになり、高価な AI 応答が書き込み途中のクラッシュでも残ります。読み取り側は壊れた JSONL 行をスキップし（復旧用に先頭 200 文字をログ）、`/messages` エンドポイント全体を 500 にしません ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147))。Web の入力欄は IME の Enter 処理も修正し、変換確定の Enter で語の途中送信が起きないようにしました ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146))。
- **2026-05-29** 🔐 **Robinhood Agentic Trading 対応（オプトイン・有界自律）**: Robinhood Agentic Trading に対応しました（リモート MCP、OAuth）。デフォルトでは無効かつ読み取り専用。エージェントはユーザーがコミットした mandate（銘柄／注文サイズ／エクスポージャー／レバレッジ／日次上限）の範囲内でのみ自律取引し、ファイルレベルの即時 kill switch、先制的なポジション手仕舞い、mandate の自動失効、完全な監査台帳、永続的な自律 runner を備えます。資金の保管なし・取引所運営なし——資金の保有と執行はブローカーが行い、こちらは意図を中継するだけです。実験的 / 自己責任でご利用ください。
- **2026-05-28** 🧪 **Swarm の安全性 + 厳格 alpha gate + worker 側 MCP**: Swarm DAG は上流タスクが失敗したとき下流タスクをブロックするようになりました ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145))。新規 `run_bench_strict()` は IC gate に同 universe のランダムコントロール + train/test OOS 分割を追加し、市場 beta を追っているだけの偽 factor を捕捉します ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143), @Soli22de さんに感謝)。Swarm worker は operator が設定した外部 MCP server からツールを呼べるようになり、信頼境界は専用テストで固定されています ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142), @shadowinlife さんに感謝)。
- **2026-05-27** 📊 **mootdx A 株データソース + 出力スタイル**: 新規 `mootdx` loader はネイティブ 通达信 TCP プロトコルで A 株 OHLCV を取得します（認証不要、IP 速度制限なし、日足 + 分足の 25 ページ walk-back ページング）。fallback chain では tushare と akshare の間に配置されます ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107))。CCXT loader は `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` を読み込み、制限されたネットワークから Binance/OKX の公開データを取得できるようになりました ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126), @ruok808 さんに感謝)。最終回答のレンダリングからは CLI と Web の見苦しい全幅 `---` セパレータを削除しました: system prompt は markdown table と `##` heading を促し、CLI renderer は単独 HR を defense-in-depth として除去し、chat bubble はすり抜けた `<hr>` を隠します ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139), @sdwxm188 さんに感謝)。
- **2026-05-26** ✅ **Research Goal ライフサイクルの閉ループ化**: Goal mode が実際のタスクランナーのように動くようになりました。Web UI で goal を作成すると session を作成または bind し、即座に kickoff turn を送ります。active goal は Web/API/CLI/MCP から continue/edit/cancel/complete でき、agent loop は最初の prompt だけでなく現在の goal snapshot（criteria、evidence、claims、open items）から前進します。criteria が covered でも goal が active のままなら silent stop ではなく audit/status update に入り、backend、CLI、MCP、frontend events の回帰で固定しました。

- **2026-05-25** 🧼 **よりクリーンな Chat UI + composer workflow**: Web UI は次の入力に集中できる形になりました。upload、swarm、research-goal mode は composer の `+` メニューにまとまり、floating panel で会話を邪魔しません。現在の context は input 上の compact chip として表示され、goal details は chip クリック時だけ inline 展開されます。旧 custom i18n layer も削除し、直接 English copy に統一。Full Report card は report-worthy run のみに表示され、local dev startup/status reporting もブラウザ smoke test 向けに安定化しました。
- **2026-05-24** 🎯 **Research Goal runtime**: backend、CLI、API/MCP、SSE、Web UI をまたぐ session-scoped Research Goal layer を追加しました。Goal は claim、acceptance criteria、evidence row、budget、completion policy を永続化します。agent tool は goal 作成と evidence 追加に対応し、`/goal` が CLI 入口になり、REST/MCP は goal snapshot と evidence write を公開し、SSE は chat client の状態を fresh に保ちます。後続 audit fixes では verified evidence をロックダウンし、agent tool からの live-trading risk tier をブロックし、CLI-created goal を後続 turn に接続し、session 削除時の goal ledger cleanup、replay-all 接続、frontend の cross-session snapshot race 修正を行いました。
- **2026-05-23** 🖥️ **インタラクティブ CLI の刷新**: ターミナル入口は大きな Vibe-Trading バナー、より見やすい prompt 区切り、前ターンの recap、実行後の所要時間、Claude Code 風の activity rail で live agent 作業を表示します。tool call、web/data fetch、shell 風 action、Markdown 回答、pipe table は読みやすい transcript として描画され、pipe や非 TTY 実行では自動化向けの plain-text 出力を維持します。生成 CLI スクリーンショットは committed docs ではなく local artifact として扱い、リポジトリを軽く保ちます。
- **2026-05-22** 🧭 **Swarm リカバリ + MCP keepalive**: Swarm の状態は読み取りのたびに live task ファイルから reconcile されるようになり、API/MCP/SSE/list ビューはクラッシュ済みまたは stale な run を復旧し、永遠に `running` のスナップショットを見せ続けません。`run_swarm` は polling 中に MCP progress heartbeat を送り、transport drop 後に再接続するクライアントでも handle を拾えるよう最初のフレームを `swarm_started run_id=<id>` に固定しました。worker も LLM streaming、grounding fetch、tool execution の各段階で heartbeat を出します。stale-run reaper は run ごとの閾値を使い、task 状態から終端状態を導出します。`SwarmTool` は待機予算が尽きても進行中の team をキャンセルせず、MCP クライアントは `reap_stale_runs()` で明示的に cleanup できます。今日の DX pass では provider の既定モデルも更新し、CI syntax check を新しい `agent/cli/` パッケージに合わせました。hydrate、終端復旧、stale reap、keepalive cadence、env parsing、heartbeat wiring を 22 件の新規回帰テストでカバーし、swarm/MCP 全体スイートは 169 passed、4 skipped です。
- **2026-05-21** 🧱 **CLI パッケージリファクタ**: `agent/cli.py`（3216 LOC）を `agent/cli/` パッケージへ分割 — インタラクティブな入口、slash ルーター、Rich コンポーネント、そしてすべてのサブコマンドを保ち `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` などの公開シンボルを再エクスポートする `_legacy.py` shim。新しい FastAPI ミドルウェアはブラウザが `/runs/{id}` または `/correlation` を直接開いた際に SPA シェルを返し、同じ絞り込みを Vite dev プロキシにも反映。バージョン文字列は `cli/_version.py` で一本化（`--version` とバナーのドリフト解消）、`python -m cli` を `__main__.py` で復活、chat ゲートを絞り `chat --help` / `chat extra` は REPL に飲み込まれずレガシー argparse に届きます。
- **2026-05-20** 🔬 **Hypothesis Registry CLI**: 2026-05-16 にバックエンドのみで公開された Hypothesis Registry の CLI 側を完成させました。`vibe-trading hypothesis list` は Rich テーブルまたは JSON を出力（`--status` フィルタと `--limit` をサポート）、`show <id>` はリンクされた run card を含む詳細パネルを描画、`invalidate <id> --note "..."` はステータスを `rejected` に切り替え、`--note` を省略すると既存の invalidation notes を保持します。既存の `VIBE_TRADING_HYPOTHESES_PATH` 環境変数オーバーライドに加え、呼び出し単位の `--path` も使えます。配線、JSON 出力、ステータスフィルタ、limit、ID 不在エラー、ノート永続化を 22 のテストでカバー。
- **2026-05-19** ✨ **ツールのライブフィードバック + グレースフルキャンセル**: 長時間実行されるツール（バックテスト、大きい PDF、swarm worker）が固まったように見えなくなりました。各ツール呼び出しは 3 秒ごとのハートビートに加え、構造化された段階進捗を発行します — `run_backtest` はフェーズマーカー（`validate` / `simulate` / `finalize`）、`read_document` は PDF ではページ単位、Excel ではシート単位、`read_url` は `fetch` / `parse` をマーク。CLI の Rich Live ダッシュボードは Unicode スピナー、ASCII プログレスバー、ETA を描画し、ツール名でキー付けして最大 3 つの並列ツールをスタック表示します。フロントエンドのチャットには新規 `ToolProgressIndicator` を追加し、rAF コアレッシング、ARIA `role="status"` + スクリーンリーダー向けの非表示 `<progress>`、合計が既知の場合は determinate な `ProgressRing` SVG を備えます。CLI 実行中の最初の `Ctrl+C` は `agent.cancel()` を呼んでグレースフル終了（現在のステップが完了し、trace がクリーンに閉じる）し、2 秒以内に 2 度目を押すと強制終了します。再利用可能なプリミティブ `ProgressBar.tsx` と `lib/tools.ts`（共有ツール名 i18n マッピング）も抽出。
- **2026-05-18** 🧹 **クリーンアップ + 3 つの潜在バグ修正**: `CompositeEngine` が取引所サフィックスのない中国先物コード（`RB2410` 等）を `GlobalFuturesEngine` に誤ルーティングしていた問題を修正。`_is_china_futures` を共有の `_market_hooks` モジュールに移し、製品コード表を大小文字正規化 + 非中国取引所のガードを追加、回帰ケース 9 件を新設しました。session FTS5 インデックスがタイムスタンプを永続化するようになり、クロスセッション検索を日付ソートできるようになりました。同じ修正で、re-upsert 経路が `started_at` を wall-clock で上書きしていた副次バグも解消しました。Vite 開発プロキシに `/alpha` を追加し、AlphaZoo ページが `npm run dev` で解決されるようになりました。`tests/test_e2e_harness_v2.py`（実 LLM の e2e スイート）は `VIBE_TRADING_RUN_LIVE_E2E=1` でゲート化し、CI が環境変数の有無で形を変えないようにしました。ruff に factor zoo 用の `per-file-ignores` を追加（F401 ノイズ 3783 → 0）、フロントエンド tsconfig は `noUnusedLocals` / `noUnusedParameters` を有効化して回帰ガードとし、`gtja191` alpha の未使用 `vw = vwap(...)` 雛形 76 件も削除しました。正味 **-918 行**。
- **2026-05-17** 🧬 **Alpha Zoo v1（0.1.8）**: 4 つの zoo にまたがる 452 個の事前構築 quant alpha を同梱しました — `qlib158`（Microsoft Qlib の Alpha158 特徴量、Apache-2.0 出処明示）、`alpha101`（Kakushadze の "101 Formulaic Alphas" を arXiv:1601.00991 から論文ベースで書き直し）、`gtja191`（国泰君安 2014 年の短期取引型 alpha レポート）、`academic`（Fama-French 5 + Carhart 動量の価格ベース proxy 実装）。任意の universe で 1 行 CLI: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`。AST 純関数ゲート、look-ahead ガードテスト、`pytest-socket` ネットワーク遮断、各 zoo ごとの LICENSE.md、コミュニティ PR 用の DCO 署名フローも同梱。Alpha Library 自動レンダリングは [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/)、Research Lab には [Which of the 191 GTJA alphas still work in 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html) を公開。
- **2026-05-16** 🧪 **リサーチ基盤アップデート**: backend Hypothesis Registry を追加し、`create_hypothesis`、`update_hypothesis`、`link_backtest`、`search_hypotheses` を提供します。外部コンテンツ reader は warning-only の `security_warnings` を付与し、Shadow Account scanner は旧 calendar-phase stub から決定的な OHLCV feature evaluation に移行しました。
- **2026-05-15** 🪪 Run 詳細ページが metrics と artifacts の隣に Trust Layer の run card を描画するようになり、2026-05-12 に入った `run_card.json` 側の UI 半分が揃いました。`PersistentMemory.add()` も #108/#109/#110 の triage を受け、長さ、空・空白だけの name、C0/C1 制御バイトの各経路で強化されました（[#112](https://github.com/HKUDS/Vibe-Trading/pull/112)、@Teerapat-Vatpitak に感謝）。
- **2026-05-14** 🌐 公開 Wiki が [vibetrading.wiki](https://vibetrading.wiki/) で公開され、docs、tutorials、Research Lab、Alpha Library セクションを Cloudflare Pages から配信します。永続メモリも CLI から `vibe-trading memory list/show/search/forget` で確認できるようになり（[#102](https://github.com/HKUDS/Vibe-Trading/pull/102)、@Teerapat-Vatpitak に感謝）、メモリの tokenization/slug はタイ語、アラビア語、ヘブライ語、キリル文字にも対応しました（[#104](https://github.com/HKUDS/Vibe-Trading/pull/104)）。

- **2026-05-13** 🧭 Swarm 実行では、取得済みの市場データでワーカーを grounding し、永続化レポートもより整理されました（[#93](https://github.com/HKUDS/Vibe-Trading/pull/93)、[#84](https://github.com/HKUDS/Vibe-Trading/pull/84)）。
- **2026-05-12** 🧾 バックテストは、再現可能なリサーチ実行のために artifacts と並んで `run_card.json` と `run_card.md` を出力するようになりました。
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
        • A/HK/US/カナダ/英国/インド/韓国株式、暗号資産、先物、FX<br>
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

研究、シミュレーション、バックテストのために設計されています——さらに、お望みであれば、ご自身が認可したブローカー（例: Robinhood Agentic Trading）を通じた自律取引も可能です。資金は一切保管せず、設定した制限を超える取引は決して行わず、いつでも即座に停止できます。

---

## ✨ できること

| タスク | 出力 |
|------|--------|
| **トレーディングの問いを投げる** | ツール、データ、ドキュメント、再利用可能なセッション文脈を使った市場リサーチ。 |
| **戦略アイデアをバックテストする** | 戦略コード、指標、ベンチマーク文脈、検証 artifacts、run cards。 |
| **自分の取引をレビューする** | ブローカー取引日誌の解析、行動診断、ルール抽出、Shadow Account 比較。 |
| **ドキュメントとチャートを読む** | PDF / DOCX / XLSX / PPTX / 画像を pluggable OCR（`read_document`）で解析し、チャートのスクリーンショットを vision モデル（`analyze_image`）で意味的に読み取る。 Web チャットではファイル選択・ドラッグ＆ドロップ・クリップボード貼り付けで一度に最大 5 ファイルを添付できます。 |
| **機関投資家の届出とファンドの中身を読む** | SEC 13F 保有（四半期比の増減付き）、市場をまたぐ ETF 構成銘柄、イベント契約の含意確率、arXiv / OpenAlex からの factor 抽出 —— すべて読み取り専用、無料の公開データ。 |
| **反復リサーチを改善する** | 永続メモリと編集可能な skills により、有用な手順を再利用可能なワークフローへ変換。 |
| **アナリストチームを走らせる** | 投資、クオンツ、暗号資産、マクロ、リスクのワークフロー向けマルチエージェント・リサーチレビュー。 |
| **リサーチを IM チャンネルへ接続する** | WebSocket、Telegram、Slack、Discord、Matrix、WhatsApp、Signal、QQ/NapCat、WeChat/WeCom、Feishu/Lark、DingTalk、Teams、email、Mochat から同じ session runtime を CLI、REST、Web UI で管理。 |
| **使える artifacts を出力する** | レポート、TradingView Pine Script、TDX、MetaTrader 5、MCP tools、後続リサーチセッション。 |
| **事前構築 alpha zoo をベンチ** | 462 個の alpha 因子（Qlib 158 + Kakushadze 101 + GTJA 191 + academic + PIT-safe fundamental）に対し、1 行 CLI で IC + IR + alive/reversed/dead 分類を実行 |
| **相関レジームを見抜く** | `/correlation` 面上のエッジ密度 + ヒステリシスのタイムライン。市場が 1 つのブロックに融合するタイミングを示す —— シグナルではなく記述的なリスクコンテキスト。 |

---

## ⚡ クイック例

```bash
pip install vibe-trading-ai

# 自然言語リサーチ
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# 事前構築 alpha zoo を 1 行でベンチ
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
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

## 💼 ローカル・マルチブローカー Portfolio

Web UI に、選んだブローカー接続の保有を横断してまとめる読み取り専用の **Portfolio** ページが加わりました。データソースは `account.read` と `positions.read` を宣言する読み取り専用 profile の接続インスタンスで、[詳細な機能](#-詳細な機能) の **ブローカー connectors** で設定します。IBKR の公式 MCP profile はまだデータソースとして使えません。

| 挙動 | 得られるもの |
|------|--------------|
| **ソースごとの出所** | すべての保有がどの接続由来かを示し、USD で評価して CNY 換算も表示します。 |
| **失敗したソースは除外** | エラーになったソースはエラーとして報告され、合計から除外されます（前回値の引き継ぎはしません）。スナップショットは incomplete として記録されます。 |
| **不変スナップショット** | 各 refresh は `~/.vibe-trading/portfolio/portfolio.sqlite3` に保存され、認証情報を含まない設定は `~/.vibe-trading/portfolio.json` と `connections.json` に置かれます。 |
| **エクスポートと分析** | CSV エクスポートに加え、サニタイズ済みの `portfolio_summary` エージェントツールを提供します。その `risk_xray_args` はそのまま `portfolio_risk_xray` に渡せます。同じスナップショットは `vibe-trading portfolio show` でターミナルにも表示できます（`refresh` / `sources` も同様）。 |

自分でインストールする読み取り専用 connector は checkout の外、`~/.vibe-trading/connectors/<name>/` に置かれます。`connector.json` manifest と、`check_status` / `get_account_snapshot` / `get_positions` を実装する `adapter.py` だけです。書き込み系の capability を宣言した manifest は拒否されます。

```bash
vibe-trading connector init my-broker --destination /tmp
vibe-trading connector validate /tmp/my-broker
vibe-trading connector install /tmp/my-broker
```

認証情報は `pip install "vibe-trading-ai[keyring]"` により OS の keyring（macOS Keychain、Windows Credential Manager、Linux Secret Service）へ保存され、設定ファイルには入りません。この経路からは注文の発注も取消もできません。

---

## 🧪 リサーチワークフロー

多くの実行は、同じ evidence path をたどります。リクエストを routing し、適切な市場文脈を読み込み、ツールを実行し、出力を検証し、artifacts を確認可能な形で残します。

| レイヤー | 何が起きるか |
|-------|--------------|
| **Plan** | 必要な finance skills、tools、data sources、必要に応じて swarm preset を選びます。 |
| **Ground** | A 株、HK/US/カナダ/英国株式、暗号資産、先物、FX、documents、Web context を利用可能な loaders から取得します。 |
| **Execute** | テスト可能な strategy code を生成し、tools を実行し、対応する backtest engine または analysis workflow を使います。 |
| **Validate** | metrics、benchmark comparison、Monte Carlo、Bootstrap、Walk-Forward、run cards、必要な warnings を追加します。 |
| **Deliver** | TradingView、TDX、MetaTrader 5、MCP clients、後続セッション向けの reports、artifacts、tool traces、exports を返します。 |

---

## 📡 データソースとスマートフォールバック

1 回の `get_market_data` 呼び出しで **23 の無料マーケットデータソース**（およびオプションの有料マーケットプレイス **QVeris**）にアクセスできます。`source: "auto"` を指定すれば、loader が銘柄に応じてソースを選び、**IP 規制リスク**の順に並んだ市場別チェーンをたどります。規制を受けない公開ソースを先に、スロットリングや key を要するソースを最後に試します。設定不要、単一障害点なし。

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share + HK | none | never IP-banned (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / HK / futures / fund / macro | token | richest A-share |
| `yahoo` | US / HK / カナダ / 英国 | none | direct chart/quotes/options；TSX `.TO` / TSXV `.V`；LSE `.L` は明示通貨で正規化 |
| `sina` · `stooq` | US | none | K-line to 1984 · EOD CSV |
| `yfinance` | US / HK / カナダ / 英国 | none | wrapper；TSX `.TO` / TSXV `.V`；LSE `.L` は同じ GBP/GBp 契約に従う |
| `longbridge` | US / HK | App Key + App Secret + Access Token | optional historical OHLCV source; install the optional SDK |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `qveris` | グローバル・マルチアセット | key · credits | **プレミアムマーケットプレイス** — 1つの key で 63+ providers（明示指定のみ、auto フォールバック対象外） |
| `okx` · `ccxt` · `binance` | crypto | none | OKX + 100+ exchanges + Binance historical / USD-M perps |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `mt5` | forex / metals | MT5 terminal | MetaTrader 5 (Exness-style) forex / metal bars, 1m–1D |
| `pykrx` | 韓国（KRX：KOSPI/KOSDAQ） | 不要 | `.KS` / `.KQ` の KOSPI / KOSDAQ 日足（任意の `krx` extra） |
| `india_broker` | インド（NSE/BSE） | ブローカーログイン | `.NS` / `.BO` 向けの読み取り専用 Shoonya / Dhan bars（フォールバックチェーン末尾） |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

**フォールバックチェーン（IP 規制リスク順）：**

- **A 株** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **米国株** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `longbridge` · `akshare` · `local`
- **香港株** → `tencent` · `eastmoney` · `yahoo` · `futu` · `akshare` · `yfinance` · `tushare` · `longbridge` · `local`
- **インド株（NSE/BSE）** → `yahoo` · `yfinance` · `india_broker` · `local`
- **韓国（KOSPI/KOSDAQ）** → `pykrx` · `yahoo` · `yfinance` · `local`
- **英国（LSE）** → `yahoo` · `yfinance` · `local` *（GBP/GBp と明示されたクォートのみ）*
- **暗号資産** → `okx` · `ccxt` · `binance` · `yfinance` · `local`
- **為替/貴金属** → `mt5` · `yfinance` · `akshare` · `local` &nbsp;·&nbsp; *(先物 / ファンド / マクロ → `tushare`/`akshare` → `local`)*

### Longbridge を明示的に使う

Longbridge は米国株/香港株のヒストリカル OHLCV を提供する任意の loader です。SDK のインストール：

```bash
pip install "vibe-trading-ai[longbridge]"
```

`.env` に 3 つの認証情報を設定します：

```dotenv
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
```

バックテストでは `config.json` の `source` を指定します：

```json
{
  "codes": ["QQQ.US"],
  "start_date": "2025-01-01",
  "end_date": "2025-01-10",
  "interval": "1D",
  "source": "longbridge"
}
```

Agent との対話では明示的に依頼してください：**「Longbridge を使って QQQ.US のヒストリカルデータを取得して」**。この明示指定は `source: "auto"` とは別物で、`auto` は市場ごとの通常のフォールバックチェーンをそのまま使います。

OHLCV にとどまらず、**22 の読み取り専用データツール**がファンダメンタルズと資金フローまで踏み込みます。資金フロー、龍虎榜、北向資金、信用取引、大口取引、株主数、ロックアップ、セクター、調査レポート、ニュース、SEC filings、財務諸表、オプションチェーン、銘柄プロファイル、市場スクリーニング、銘柄検索、マクロ、問財、機関投資家保有（13F）、ETF ルックスルー、予測市場、論文検索まで、すべて MCP 経由で公開されます。明示的な `local:` 銘柄が暗黙のうちにネットワークソースへフォールバックすることは決してありません。

<!-- QVERIS-START -->
### 💎 オプションのプレミアムデータ — QVeris

<img src="https://www.qveris.com/logo-color.png" alt="QVeris" height="36">

**データは無料ルーティングが標準、必要なときだけプレミアム。** 既定では 23 の内蔵ソースが自動フォールバックし、key も費用も不要です。QVeris を使うと、63+ providers と 10,000+ capabilities（per QVeris）で、オプション Greeks、高度なファンダメンタルズ、中国・香港・グローバルデータ、マクロ、暗号資産、ニュース、filings を補えます。失敗した call は課金されません。Settings → QVeris または `vibe-trading data mode paid` で有効化できます。

*QVeris disclosure: [Vibe-Trading の紹介リンク](https://qveris.ai/?ref=Vyjjo5G_1cAHJA) から登録すると **+1,000 クレジット** が追加付与され、プロジェクトの支援にもなります。*
<!-- QVERIS-END -->

---

## 🔩 詳細な機能

メイン README を読みやすく保つため、詳細な一覧は以下に折りたたんでいます。利用できる構成要素を確認したいときに開いてください。

<details>
<summary><b>Finance Skill Library</b> <sub>9カテゴリにわたる90 skills</sub></summary>

- 📊 90 の金融特化 skills を 9 カテゴリに整理
- 🌐 伝統的市場から crypto & DeFi まで完全カバー
- 🔬 データ取得からクオンツリサーチまでを横断する包括的能力

| Category | Skills | Examples |
|----------|--------|----------|
| Data Source | 10 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar`, `qveris` |
| Strategy | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 23 | `factor-research`, `correlation-regime`, `macro-analysis`, `global-macro`, `valuation-model`, `investor-lenses`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Research | 3 | `alpha-zoo`, `strategy-dev-manager`, `strategy-discovery` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>カスタムデータソース</b> <sub>独自の過去 OHLCV loader を登録</sub></summary>

loader を同梱していない市場やベンダーが必要ですか？独自の過去バー loader を追加し、
`source="<name>"` で選択できます。以下の手順はパッケージのソースを編集するため、
clone から実行してください（`pip install -e .`）。

1. **loader を書く** —— `agent/backtest/loaders/<name>_loader.py` を作成し、
   `DataLoaderProtocol` を満たすクラス（duck-typed、基底クラス不要）を定義して
   `@register` を付けます：

   ```python
   import pandas as pd
   from backtest.loaders.registry import register

   @register
   class DataLoader:
       name = "mysource"            # the value you pass as source=
       markets = {"us_equity"}      # a_share/us_equity/hk_equity/crypto/futures/fund/macro/forex
       requires_auth = False

       def is_available(self) -> bool:
           return True              # token present? network reachable?

       def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
           # return {symbol: DataFrame indexed by trade_date,
           #         columns: open, high, low, close, volume}
           ...
   ```

2. **モジュールを登録** して `@register` を発火させる —— `agent/backtest/loaders/registry.py`
   の `_loader_modules` に `"backtest.loaders.<name>_loader"` を追加します。
3. **名前を許可** して設定バリデーションを通す —— `agent/backtest/runner.py` の
   `_VALID_SOURCES` に `"mysource"` を追加します。
4. *（任意）* `registry.py` のある市場の `FALLBACK_CHAINS` に組み込むと、
   `source="auto"` からも到達できます。
5. **使う** —— バックテスト設定で `source="mysource"`、または CLI / agent 経由で。

> **リアルタイムの ticks / 板情報（depth）は loader の対象外です** —— loader 層は
> point-in-time の過去バーのみを扱います。リアルタイム市場データは broker connector
> を通します：暗号資産は `okx` / `binance` / `ccxt`、株式は `futu` / `tiger`。

</details>

<details>
<summary><b>ブローカー connectors</b> <sub>13 ブローカー — read + paper、対応先では bounded-live</sub></summary>

connector-first のプロファイル。多くは read + ペーパー口座での発注に対応します —— IBKR は読み取り専用、Robinhood はライブのみ（ペーパー口座なし）、Trading 212 はペーパーを含め発注を一切拒否します。ライブ発注はユーザーが定義した mandate（銘柄許可リスト、発注サイズ / エクスポージャー上限、1 日の取引回数上限、即時 kill switch）で制限され、資金を預かることは一切ありません —— 執行するのはブローカーです。発注系ツールは MCP に公開されません（agent + CLI のみ）。リサーチ / バックテスト経路は構造的にあらゆるライブ endpoint から遮断されています。

| Broker | Markets | Capabilities |
|--------|---------|--------------|
| **IBKR** | global | local TWS / Gateway, read-only |
| **Robinhood** | US | Agentic MCP (desktop OAuth) — read + bounded live |
| **Tiger** | US / HK / A | read + paper + bounded live |
| **Alpaca** | US | read + paper + bounded live (+ TAP credential-isolation mode) |
| **OKX** · **Binance** | crypto | read + paper + bounded live |
| **Futu** | HK / US / A | read + paper + bounded live |
| **eToro** | global | read + paper + bounded live（Public API；demo キーは構造上 `/demo` パスにしか到達せず、コピートレードのワークフローにも対応） |
| **MetaTrader 5** | forex / CFD | read + paper + bounded live (Exness-style; demo ⇔ paper identity guard) |
| **Longbridge** · **Dhan** · **Shoonya** | US / HK · India (NSE/BSE) | read + paper only — no runtime paper/live discriminator, so live order placement is hard-refused |
| **Trading 212** | UK / EU | fully read-only — `place_order` / `cancel_order` hard-refuse even paper |

Paper-vs-live is a **structural per-broker runtime guard** (account-id format, host separation, demo flag, or trade environment), never a config flag the agent can flip. A broker exposing no such discriminator is capped at paper + read-only.

</details>

<details>
<summary><b>Preset Trading Teams</b> <sub>30 swarm presets</sub></summary>

- 🏢 すぐ使える 30 の agent teams
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

<details>
<summary><b>Alpha Zoo</b> <sub>5 つのファミリーに渡る 462 個の事前構築 quant alpha</sub></summary>

- 🧬 462 個のクロスセクショナル alpha、オペレーター層でルックアヘッドを禁止
- 📈 IC + IR + alive/reversed/dead 分類を 1 つの CLI コマンドで
- 🔬 AST 純関数ゲート + 300 行のルックアヘッド sentinel テスト + `pytest-socket` によるネットワーク遮断
- 📦 Qlib には Apache-2 帰属表示、各 zoo ごとに `LICENSE.md` で formula を数学的内容として宣言
- 🤝 コミュニティ PR 向け Developer Certificate of Origin (DCO) 署名フロー

| Zoo | 件数 | 出典 | ライセンス |
|-----|-------|--------|---------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158`（Apache-2.0、コミット固定） | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015)、"101 Formulaic Alphas"、arXiv:1601.00991 | Formula は数学的内容 |
| **gtja191** | 191 | 国泰君安 (2014)、「191 短周期取引型 alpha 因子」 | Formula は数学的内容 |
| **academic** | 12 | Fama-French 5 + Carhart momentum（価格ベースの proxy） + Jegadeesh reversal + George-Hwang 52-week-high + Amihud illiquidity + Harvey-Siddique skew + Frazzini-Pedersen betting-against-beta + correlation-rewiring stability | 公開された学術文献 |
| **fundamental** | 4 | PIT セーフな SEC company facts — earnings yield、ROE、gross profitability、asset growth（filed-date 基準） | 公開財務データ |

`vibe-trading alpha list` で閲覧、`vibe-trading alpha show <id>` で formula + ソース、`vibe-trading alpha bench --zoo X --universe Y --period Z` で zoo 全体をスコアリング、`vibe-trading alpha compare --all` で zoo 同士を並べてランク付けできます。

</details>

<details>
<summary><b>Backtest Engines</b> <sub>10 engines + options portfolio, cross-market composite</sub></summary>

| Engine | Market | Notes |
|--------|--------|-------|
| **ChinaA** | A-share | T+1, price limits, pre-ST filter |
| **GlobalEquity** | US / HK / カナダ / 英国 | 同一セッション売買、市場別のロット・呼値・決済通貨・コスト |
| **IndiaEquity** | India (NSE/BSE) | T+1, circuit bands, config-driven STT / stamp / SEBI / GST cost stack |
| **KoreaEquity** | 韓国（KRX：KOSPI/KOSDAQ） | ロングオンリー、統一呼値グリッド上で ±30% 制限値幅を約定時点に判定、2026 年 0.20% の証券取引税 |
| **VietnamEquity** | ベトナム（HOSE） | ロングオンリー、T+2 決済ホールド、10/50/100 ドンの呼値グリッド上で ±7% 制限値幅、100 株単元、売却側 0.1% 課税 |
| **Crypto** | crypto spot / USD-M perps | funding settlements, execution/mark split |
| **ChinaFutures** · **GlobalFutures** | futures | margin, contract multipliers |
| **Forex** | FX / metals | via the `mt5` loader |
| **Composite** | cross-market | one shared capital pool across markets (`source="auto"`) |
| **options_portfolio** | options | multi-leg, Greeks, payoff/scenario |

Intraday bars: 1m / 5m / 15m / 30m / 1H / 4H / 1D. 15 metrics + benchmark comparison, **5 portfolio optimizers** (equal-volatility / risk-parity / mean-variance / max-diversification / turnover-aware), and 3 validation tools (Monte Carlo / Bootstrap / Walk-Forward).

</details>

<details>
<summary><b>Quant Library</b> <sub>23 モジュール・306 個のテスト済み関数、すべての経路から呼び出し可能</sub></summary>

`src/quantlib` は、agent が必要とする金融数学のそれぞれについて、テスト済みの実装を
**1 つだけ**保持します。skill はこれらを **import** するようになり、markdown コード
ブロックの中に数式を抱え込むことはなくなりました —— `SKILL.md` の中に価格式が住んで
いたら、それはパターンではなくバグです。

| モジュール | カバー範囲 |
|-----------|-----------|
| `options` | Black-Scholes 価格 + greeks、インプライドボラティリティの逆算 |
| `fixedincome` | 債券数学、Nelson-Siegel / Svensson カーブフィッティング |
| `credit` | Altman Z-score、Merton / KMV デフォルト距離 |
| `timeseries` | 定常性、共和分、GARCH、bootstrap |
| `risk` · `var_backtest` | VaR / CVaR / EVT とそのバックテスト |
| `attribution` | Brinson-Fachler 要因分解 |
| `performance` · `fundmath` | TWR / MWR / Modified Dietz、XIRR / MOIC / DPI / TVPI |
| `factormodel` · `eventstudy` | ファクター回帰、イベントスタディ |
| `multipletesting` · `crossvalidation` | 多重検定調整、purged CV |
| `impact` | マーケットインパクトモデル |
| `volatility` | Heston (1993) 確率的ボラティリティ価格付け |
| `portfolio` | 階層的リスクパリティ（HRP）配分 |
| `copula` | ガウス・アルキメデス型コピュラ |
| `microstructure` | VPIN、Roll スプレッド、Amihud 非流動性、Kyle ラムダ |

読み取り専用の `quantlib_call` ツールが 1 つの契約で全体に到達するため、`bash` が
無効化されている CLI・Web UI・REST API・MCP でも金融数学が使えます。構造的に shell では
**ありません** —— モジュール許可リスト、`__all__` のみのディスパッチ、`export_*` は拒否。
計量経済学の関数は `stats` エクストラ（`pip install "vibe-trading-ai[stats]"`）が必要で、
遅延インポートして不足しているものを名指しします。

</details>

<details>
<summary><b>バリュエーションと機関投資家向けリサーチ</b> <sub>DCF・コンプス・三表連動、および六つのリサーチコマンド</sub></summary>

入力を自分で捏造することを拒むバリュエーションエンジンです。`contracts.py` の唯一の
ルール：**入力が欠けているモデルは実行不能（NOT RUNNABLE）であり、黙ってデフォルト値
を埋めることはない** —— バリュエーションモデルにおけるあらゆるデフォルト値は、定数の
衣をまとった意見だからです。

| モデル | 押さえておくべき挙動 |
|--------|---------------------|
| `run_dcf` | FCFF ブリッジ、WACC 構築、期央割引、ネットデット・ブリッジ、WACC×g 感応度グリッド。デュアル・ターミナルバリュー：各手法を相手方の含意マルチプルと含意 g で相互検証 |
| `run_comps` | EV ブリッジ、LTM + 暦年カレンダリゼーション、マルチプル行列。分母が非正のピアは**除外して報告**し、負のマルチプルとして平均に混ぜません |
| `threestatement` | 連動予測。厳格なバランス検証、明示的なリボルバー・プラグ、収束しなければ raise する金利↔負債の循環反復 |

成果物は入力ハッシュ付きでバージョン管理され、xlsx / pptx にエクスポートできます。

6 つのスラッシュコマンドがワークフローを駆動します —— `/comps` `/dcf` `/attrib`
`/memo` `/earnings` `/screen` —— それぞれが手順スケルトンと**算術的に整合した**
ワークトサンプルを備えています（Brinson 分解はアクティブリターンに厳密に合算され、
業績ブリッジは EPS 差分に厳密に合算されます）。`investor-lenses` skill は著名投資家の
思考フレームワークを分析オーバーレイとして重ねます：各レンズは優先シグナル・失格条件・
典型的な誤用からなる運用手順であり、人物伝ではなく、ツール名も指定しません。

バー以外に、`src/entities` が不規則な日付のキャッシュフロー（NAV、キャピタルコール、
クーポン）を取り込み、`cashflow_performance` が XIRR / MOIC / DPI / TVPI / TWR /
Modified Dietz / MWR を返します。この経路はバーエンジンとあえて**並行**に設計されており、
`nav` 列がバーエンジンに届いて終値として値付けされることは決してありません。

</details>

<details>
<summary><b>ガバナンスと監査証跡</b> <sub>「その数字はどの方法論が生んだのか？」に答える</sub></summary>

すべての実行は、プロンプト・skill の内容・ツールレジストリ・パッケージバージョンを
ハッシュした **manifest** を書き出します。1 か月前に出た数字も、それを生んだ正確な
方法論まで遡れます。

**監査台帳**は各レコードを直前のハッシュに連鎖させて fsync するため、レコードの改変や
削除は検出可能です —— 自分のハッシュを再計算した改変であっても、次のレコードで
`prev_hash_mismatch` として捕捉されます。タイムスタンプは常に呼び出し側が供給し、
このモジュールは `datetime.now()` を呼びません。

トレースの秘匿は **sink 単位**です：ツール呼び出しの引数とライブ監査台帳は
fail-closed sink を使い `content` を秘匿したまま、ツール結果の sink だけが `content` を
解放し、その文字列リーフをパターン洗浄します。`env` はどちらでも解放されません。

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

> **古いバージョンからのアップグレード？** 0.1.10 で LangChain 1.x に移行しました。0.1.10 より前のインストールに対して `pip install -U vibe-trading-ai` を実行した後にインポートが壊れる場合（例: langgraph のインポート失敗）、venv を作り直すか `pip install --force-reinstall vibe-trading-ai` を実行してください。新規インストールは影響を受けません。

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

> **Supported LLM providers:** OpenRouter、Requesty、OpenAI、Anthropic（ネイティブ Messages API）、DeepSeek、Gemini、Groq、DashScope/Qwen、Zhipu、Moonshot/Kimi、MiniMax、SiliconFlow（CN + Global）、Xiaomi MIMO、Novita AI、iFlytek Spark、Z.ai、NVIDIA NIM、ModelScope、GitHub Copilot、Ollama（local）。`*_BASE_URL` が未設定の場合、各プロバイダーは canonical なエンドポイントにフォールバックするため、key だけで十分です。設定は `.env.example` を参照してください。

> **Tip:** 自動フォールバックにより、すべての市場は API key なしで利用できます。yfinance/Yahoo（HK/US/カナダ/英国）、OKX（crypto）、mootdx（A 株、TCP 直結で IP 制限なし）、AKShare（A-shares、US、HK、futures、forex）はすべて無料です。LSE `.L` クォートは GBP または GBp の明示が必要で、GBP 会計の前にペンスを正規化します。Tushare token は任意で、A 株は mootdx が推奨の no-token fallback、AKShare がより広いカバレッジのバックアップになります。

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
# .venv\Scripts\activate.bat       # Windows CMD
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # Edit — set your LLM provider API key
vibe-trading                       # Launch interactive TUI
```

> [!NOTE]
> **Windows の場合:** `cp` は PowerShell では `Copy-Item` のエイリアスなので、上記のコマンドは PowerShell ならそのまま動きます。CMD には `cp` がないため、代わりに `copy agent\.env.example agent\.env` を使ってください（上の Docker のコマンドも同様です）。PowerShell が `Activate.ps1` の実行を拒否する場合は、先に `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` を実行してください。この設定は現在のシェルセッションにのみ適用されます。

<details>
<summary><b>Web UI を起動（任意）</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev  # Node >= 22.22 が必要
```

`http://localhost:5899` を開きます。frontend は API calls を `localhost:8899` へ proxy します。

**Production mode（single server）:**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> `vibe-trading serve` は `0.0.0.0` にバインドしますが、デフォルトではループバックのみを信頼します。**同じマシン**で UI を開く場合（`http://localhost:8899`）は設定不要で動作します。**別のマシン・VM ホスト・LAN 上のスマートフォン**からアクセスすると、機微なエンドポイントは `403` を返し、チャットに “Remote API access requires an API key” と表示されます。`agent/.env` に強力な `API_AUTH_KEY` を設定して再起動し、**Settings** で同じキーを入力してください。（Docker Desktop のホストゲートウェイの場合: デフォルトの `127.0.0.1` ポートバインドのまま `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` を設定。）

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
| `VIBE_TW_STOCK_DB` | No | 台湾市場の SQLite スナップショットのパス。読み取り専用 `taiwan_stock_data` ツールはスキーマ妥当な場合のみ登録されます |
| `VIBE_TRADING_EXTRA_CORS_ORIGINS` | No | ループバックの CORS 既定値に**追加**するオリジン（カンマ区切り。`CORS_ORIGINS` は置き換え） |
| `CONTENT_FILTER_WARNING_THRESHOLD` | No | コンテンツフィルタ警告の比率しきい値（既定 0.05 = 5%）。コンテンツモデレーションでブロックされた LLM 応答の割合がこれを超えると、run card がプロバイダーの変更を促します。 |

<sub>* Ollama は API key 不要です。OpenAI Codex は ChatGPT OAuth を使い、tokens は `agent/.env` ではなく `oauth-cli-kit` 経由で保存します。</sub>

**無料データ（key 不要）:** AKShare による A-shares、Yahoo/yfinance による HK/US/カナダ/英国 equities、OKX による crypto、CCXT による 100+ crypto exchanges。システムは各市場に最適な利用可能 source を自動選択します。

### 🎯 推奨モデル

Vibe-Trading は tool-heavy agent です。skills、backtests、memory、swarms はすべて tool calls を通じて流れます。モデル選択は、agent が実際に *tools を使う* か、training data から作り話をするかを直接左右します。

| Tier | Examples | When to use |
|------|----------|-------------|
| **Best** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | 複雑な swarms（3+ agents）、長い research sessions、paper-grade analysis |
| **Sweet spot** (default) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | 日常使い。信頼できる tool-calling を約 1/10 の cost で |
| **agent 用途では避ける** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | Tool-calling が不安定です。agent は skills 読み込みや backtests 実行ではなく「記憶から答えている」ように見えます |

既定の `agent/.env.example` は DeepSeek official API + `deepseek-v4-pro` で出荷されています。OpenRouter users は `deepseek/deepseek-v4-pro` を利用できます。

---

## 🖥 CLI リファレンス

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # 462 個の事前構築 alpha を閲覧；show / bench / compare / export-manifest サブコマンド利用可
vibe-trading playbook list # 定期リサーチのテンプレート 5 本；show / create サブコマンド利用可
vibe-trading channels status --local  # IM チャンネル設定と install hints を確認
vibe-trading provider doctor  # 秘匿処理済みの provider/proxy/package 診断を出力
```

<details>
<summary><b>TUI 内の slash commands</b></summary>

| Command | Description |
|---------|-------------|
| `/help` | キーボードショートカットとコマンド一覧を表示 |
| `/model` | LLM provider とモデルを切り替え |
| `/memory` | 永続メモリの表示 / 管理 |
| `/history` | 過去セッションの閲覧と再開 |
| `/goal` | 金融リサーチ goal の開始 / 確認 |
| `/search` | 全セッション横断の全文検索 |
| `/swarm` | マルチエージェント preset（委員会 / クオンツ / リスク） |
| `/skill` | skills の一覧 / 読み込み / 解除 |
| `/show` | 過去の run を id で表示 |
| `/clear` | 現在の会話をクリア |
| `/pine` | 現在の戦略を Pine Script として書き出し |
| `/journal` | 取引履歴 CSV を分析 |
| `/shadow` | シャドーアカウントの学習 / 表示 |
| `/export` | 現在のセッションを書き出し（md / json） |
| `/debug` | デバッグパネル切り替え（token 使用量 / レイテンシ） |
| `/comps` | 類似企業分析（ピア倍率 → 含意レンジ） |
| `/dcf` | DCF 評価と感応度グリッド |
| `/attrib` | Brinson-Fachler 要因分解（アロケーション vs 銘柄選択） |
| `/memo` | 投資メモ — 論点、コンセンサスと異なる見立て、シナリオ、撤退条件 |
| `/earnings` | 決算レビュー — 売上から EPS までのサプライズ分解 |
| `/screen` | 体系的アイデアスクリーン — 仮説、ファネル、残存キュー |
| `/playbook` | 定期リサーチのテンプレート（一覧 / 実行 / スケジュール） |
| `/connector` | 取引 connector profile（状態 / 開始 / 停止） |
| `/halt` | キルスイッチ — すべてのライブ取引を即時停止 |
| `/resume` | キルスイッチを解除（ライブ取引を再開） |
| `/data` | データルーティングモード |
| `/quit` | 終了（q、exit、:q も可） |

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
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

<details>
<summary><b>IM チャンネル</b></summary>

IM channel adapters は外部チャットアプリを Web UI / CLI と同じ session runtime へ接続します。有効化する adapter は `~/.vibe-trading/agent.json` の `channels` 配下に設定します。SDK-backed adapters は optional extras で、SDK が足りない場合も runtime を落とさず recovery hints を返します。

```bash
vibe-trading channels status --local   # API なしで config と missing SDK hints を確認
vibe-trading channels status           # 稼働中の API runtime を問い合わせ
vibe-trading channels start            # API 経由で enabled adapters を開始
vibe-trading channels stop             # API 経由で enabled adapters を停止
vibe-trading channels login weixin     # 必要な adapter login hook を実行
vibe-trading channels pairing --channel telegram list
```

`vibe-trading channels login feishu` は、ログイン成功を報告する前に、QR 認可で取得したアプリ資格情報を `~/.vibe-trading/agent.json` に保存します（ファイル権限は所有者のみ）。

Built-in adapters は `websocket`、`telegram`、`slack`、`discord`、`matrix`、`whatsapp`、`signal`、`qq`、`napcat`、`weixin`、`wecom`、`feishu`、`dingtalk`、`msteams`、`email`、`mochat` です。個別に `pip install "vibe-trading-ai[telegram]"` を使うか、全チャンネル分を `pip install "vibe-trading-ai[channels]"` で入れられます。

**チャット内スラッシュコマンド**（チャンネル非依存、全 16 adapter で共通）：

| コマンド | 説明 |
|---------|------|
| `/new` | 現在のセッションをリセット——次のメッセージで新しい会話を開始 |
| `/reset` | `/new` のエイリアス |
| `/newsession` | `/new` のエイリアス |
| `/pairing list` | 保留中の sender pairing リクエストを表示 |

コマンドは大文字小文字を区別せず、メッセージ全体として送信する必要があります（例：`hello /new` はリセットではなく通常メッセージとして処理されます）。

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

**事前構築 alpha zoo を 1 行でベンチ**:
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**カタログを閲覧**して個別の alpha を確認:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**zoo からマルチファクターシグナルを構成**（Python）:
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
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
| `POST` | `/upload` | ドキュメント・データファイル・画像をアップロード |
| `GET` | `/swarm/presets` | swarm presets を一覧表示 |
| `POST` | `/swarm/runs` | swarm run を開始 |
| `GET` | `/swarm/runs/{id}/events` | Swarm SSE stream |
| `GET` | `/alpha/list` | zoo/theme/universe でフィルタした alpha リスト |
| `GET` | `/alpha/{alpha_id}` | Alpha のメタデータ + ソースコード |
| `POST` | `/alpha/bench` | Bench ジョブを開始（`job_id` を返す） |
| `GET` | `/alpha/bench/{job_id}/stream` | SSE 進捗ストリーム |
| `GET` | `/settings/llm` | Web UI LLM settings を読み取り |
| `PUT` | `/settings/llm` | local LLM settings を更新 |
| `GET` | `/settings/data-sources` | local data source settings を読み取り |
| `PUT` | `/settings/data-sources` | local data source settings を更新 |
| `GET` | `/channels/status` | IM channel runtime と adapter status を読み取り |
| `POST` | `/channels/start` | 設定済み IM channel adapters を開始 |
| `POST` | `/channels/stop` | 設定済み IM channel adapters を停止 |
| `POST` | `/channels/pairing/command` | shared store に対して sender-pairing command を実行 |
| `POST` | `/scheduled-runs` | 定期リサーチジョブを作成（interval-ms または cron） |
| `GET` | `/scheduled-runs` | スケジュール済みジョブを一覧 |
| `GET` | `/scheduled-runs/status` | 実行器の状態と設定済み配信ターゲット |
| `GET` | `/scheduled-runs/{job_id}` | スケジュール済みジョブを 1 件取得 |
| `DELETE` | `/scheduled-runs/{job_id}` | スケジュール済みジョブをキャンセル |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/commit` | エージェント提案の作成/キャンセルを確定 |
| `POST` | `/scheduled-runs/proposals/{proposal_id}/discard` | エージェント提案を破棄 |
| `GET` | `/scheduled-runs/playbooks` | リサーチテンプレートを一覧 |
| `GET` | `/scheduled-runs/playbooks/{slug}` | テンプレート 1 件と宣言済み変数を表示 |
| `POST` | `/scheduled-runs/playbooks/{slug}` | テンプレートからジョブをスケジュール |
| `POST` | `/sessions/{id}/cancel` | 進行中の実行を停止（失敗ではなくキャンセルとして記録） |
| `POST` | `/sessions/{id}/title/auto` | 最初のやり取りからセッション名を生成（手動リネームは上書きしない） |
| `GET` | `/correlation/regime` | 相関エッジ密度のレジームタイムライン |
| `GET` | `/agents.json` · `POST` `/v1/query` | OpenBB Workspace ブリッジ — 任意の `openbb` extra 導入時のみ登録、`/v1/query` は認証必須 |

Interactive docs: `http://localhost:8899/docs`

### Security defaults

localhost 開発では、`vibe-trading serve` は browser workflow を簡単に保ちます。非ローカル client では、sensitive API endpoints に `API_AUTH_KEY` が必要です。JSON/upload requests には `Authorization: Bearer <key>` を使ってください。Browser EventSource streams は、Settings で同じ key を一度入力した後、Web UI が処理します。

Shell-capable process tools（`bash` / `background_run` / `cancel_background`）はインタラクティブな local CLI でのみ有効です。それ以外のすべての面 — HTTP/SSE API と MCP server の**すべての** transport（stdio を含む）— は、`VIBE_TRADING_ENABLE_SHELL_TOOLS=1` を明示的に設定する（または `vibe-trading-mcp` に `--enable-shell-tools` を渡す）まで無効のままです。transport の種類が暗黙に shell アクセスを許可することはありません。Document と journal readers は既定で upload/import roots に制限されます。ファイルは `~/.vibe-trading/uploads`、`~/.vibe-trading/runs`、`./uploads`、`./data`（または旧来の `agent/uploads` / `agent/runs`）の下に置くか、`VIBE_TRADING_ALLOWED_FILE_ROOTS` で専用 directory を追加してください。セッション、実行成果物、swarm 実行、アップロード、`sessions.db` インデックスは `~/.vibe-trading` 配下に統一されています（shell 環境変数 `VIBE_TRADING_HOME` で丸ごと移動可能）。旧位置の履歴は初回起動時に自動で移行されます。

### Web UI Settings

Web UI Settings page では、local users が LLM provider/model、base URL、generation parameters、reasoning effort、Tushare token など任意の market data credentials を更新できます。Settings は `agent/.env` に永続化され、provider defaults は `agent/src/providers/llm_providers.json` から読み込まれます。

Settings reads は side-effect free です。`GET /settings/llm` と `GET /settings/data-sources` は `agent/.env` を作成せず、project-relative paths だけを返します。Settings の読み書きは credential state の公開や credentials/runtime environment の更新を伴うため、設定済みの場合は `API_AUTH_KEY` が必要です。dev mode で `API_AUTH_KEY` が未設定の場合、settings access は loopback clients からのみ受け付けます。

同じ Settings page には local operator 向けの **IM チャンネル**パネルもあります。`/channels/status` を polling し、configured/enabled/available/loaded/running 状態、adapter recovery hints、runtime の start/stop 操作を terminal に戻らず扱えます。

### Scheduled research（定期リサーチ）

リサーチ prompt や backtest を繰り返しスケジュールで実行します。Web UI の**スケジュール**ページからも REST からも操作できます。バックグラウンド executor は**既定でオフ**です。`VIBE_TRADING_ENABLE_SCHEDULER=1` を付けて server を起動すると有効になります:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

その後、REST でジョブを作成します。`schedule` は単なる整数（interval は**ミリ秒**）か、5 フィールドの cron 式（`分 時 日 月 曜日`。各フィールドは `*`、`*/n`、数値、カンマ区切りリスト、`1-5` のような範囲に対応）です。cron はジョブの任意の `timezone`（IANA キー）の壁時計で評価され、夏時間の切り替え後もリズムは変わりません——存在しない時刻（春の進み）はスキップされ、重複する時刻（秋の戻り）は最初の 1 回だけ実行されます。`timezone` のないジョブは従来どおり UTC で動作します:

```bash
# 6 時間ごと（cron）
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan CSI300 for momentum breakouts and backtest the top 5","schedule":"0 */6 * * *"}'

# 平日 23:30（オークランドの壁時計、夏時間でもずれない）
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Pre-open scan of NZX names","schedule":"30 23 * * 1-5","timezone":"Pacific/Auckland"}'

# 一覧 / キャンセル
curl http://localhost:8899/scheduled-runs
curl -X DELETE http://localhost:8899/scheduled-runs/<job_id>
```

各実行は新しい agent session で `prompt` を実行し（任意の backtest パラメータは `config` に入れます）、ジョブは `~/.vibe-trading/` に永続化されるため再起動後も残ります。このフラグがない場合、`/scheduled-runs` endpoints はジョブを記録しますが実行はされません。`API_AUTH_KEY` を設定している場合は各呼び出しに `-H "Authorization: Bearer <key>"` を付けてください。

エージェントに見えるスケジューリングツールは `scheduled_research` の 1 つだけです。読み取り系アクションは状態/ジョブ/テンプレートを照会し、`propose_create` と `propose_cancel` は短時間で失効する確認プロポーザルを保存するだけで、ジョブストアを直接変更することはありません。Web は決定的な確認カードを表示し、CLI は `y/N` を尋ね、IM 会話では正確に `confirm`（`确认`）または `cancel`（`取消`）と返信する必要があります——commit エンドポイントを呼ぶのはこれらの操作だけです。`end_at` を過ぎたジョブは `expired` になり、再実行されません。配信はチャネル非依存です。`channels.deliveryTargets` に再利用可能な不透明ターゲット参照を設定すると、エージェントと確認 UI には ref/label/channel のみが見え、プロバイダの生の chat/user id は渡りません。アダプタが受領証なしで成功した場合の配信状態は `accepted`、プロバイダのメッセージ id が返ったときだけ `sent` になります（現在は Feishu がエンドツーエンド対応）。

スケジューラには**すぐ使えるリサーチテンプレートが 5 本**同梱されています —— `premarket-brief`、`earnings-season-tracker`、`portfolio-checkup`、`a-share-money-flow`、`institutional-holdings-diff`。各テンプレートはツール名を挙げず、必要なデータを自然言語で宣言するため、ツール面が広がってもそのまま機能します。また、欠けている入力は記憶で埋めず**明示する**ことが求められます。CLI、REST、TUI の `/playbook` から利用できます：

```bash
vibe-trading playbook list                     # 5 本のテンプレート
vibe-trading playbook show premarket-brief     # 本文・宣言済み変数・推奨頻度
vibe-trading playbook create premarket-brief \
  --var home_market="US equities" --var watchlist="AAPL, MSFT, NVDA" \
  --timezone America/New_York

curl http://localhost:8899/scheduled-runs/playbooks
curl http://localhost:8899/scheduled-runs/playbooks/premarket-brief
curl -X POST http://localhost:8899/scheduled-runs/playbooks/premarket-brief \
  -H "Content-Type: application/json" \
  -d '{"variables":{"home_market":"US equities","watchlist":"AAPL, MSFT, NVDA"}}'
```

`{}` を POST すると、テンプレート自身の推奨頻度と既定変数でスケジュールされます。描画された本文はそのままジョブの prompt になり、宣言されていない変数は黙って無視されず拒否されます。

---

## 🔌 MCP Plugin

Vibe-Trading は MCP-compatible client 向けに 74 MCP tools を公開します。stdio subprocess として動作し、server setup は不要です。Core research tools は HK/US/crypto で API key なしに動作し、trading connector tools は選択中の connector profile を使います。LLM key が必要なのは `run_swarm` のみです。

**環境変数:** server は client 自身が spawn するため、shell の `export` は届きません —— client の `env` block に設定してください。生成された backtest code は allowed run roots 内に制限されるので、結果を自分の作業 directory に書き出すには `VIBE_TRADING_ALLOWED_RUN_ROOTS` が必要です:

```json
{
  "mcpServers": {
    "vibe-trading": {
      "command": "vibe-trading-mcp",
      "env": { "VIBE_TRADING_ALLOWED_RUN_ROOTS": "C:\\Users\\me\\research" }
    }
  }
}
```

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
vibe-trading-mcp                   # stdio (default)
vibe-trading-mcp --transport http  # Streamable HTTP (spec default) at /mcp
vibe-trading-mcp --transport sse   # legacy SSE (deprecated)
```

</details>

**公開される MCP tools（74）:** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `alpha_zoo`, `alpha_bench`, `analyze_options`, `analyze_options_payoff`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `list_strategies`, `query_strategies`, `get_strategy_evidence`, `refresh_strategy_evidence`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `qveris_search`, `qveris_inspect`, `qveris_execute`, `get_institutional_holdings`, `etf_holdings`, `prediction_market`, `research_papers`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `quantlib_call`, `cashflow_performance`, `orderbook_depth`, `sentiment`, `technical_indicators`, `get_fundamentals`.

### SWARM の外部 MCP tools

`run_swarm` の worker は、運用者が承認した外部 MCP server のツールを呼び出せます。サーバー側の allowlist を `VIBE_TRADING_SWARM_AGENT_CONFIG`、`~/.vibe-trading/swarm-agent.json`、またはフォールバックの `~/.vibe-trading/agent.json` に設定し、swarm preset ではローカル MCP のラッパー名（例：`mcp_internal_kb_search`）でリモートツールを列挙します。呼び出し側が渡す `variables` はテンプレートのデータに留まり、MCP URL・コマンド・環境変数・allowlist の上書きを注入することはできません。

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

90 の finance skills はすべて [open-space.cloud](https://open-space.cloud) に公開され、OpenSpace の self-evolution engine を通じて自律的に進化します。

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

OpenSpace は 90 skills を自動検出し、auto-fix、auto-improve、community sharing を可能にします。OpenSpace-connected agent では `search_skills("finance backtest")` から Vibe-Trading skills を検索できます。

</details>

### MetaTrader 5（Exness などの MT5 ブローカー）

公式の `MetaTrader5` パッケージ経由で、**ローカルで稼働中の MT5 terminal** に接続します（**Windows 専用**）:

```bash
pip install "vibe-trading-ai[mt5]"
```

`~/.vibe-trading/mt5.json` を設定します（手動で作成し、対応環境では chmod 600 を設定）:

```json
{
  "login": 12345678,
  "password": "...",
  "server": "Exness-MT5Trial8",
  "symbol_suffix": "m",
  "max_order_volume": 1.0,
  "max_order_notional_usd": 10000
}
```

続いて:

```bash
vibe-trading connector use mt5-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector quote EURUSD
vibe-trading connector history EURUSD
```

| Profile | 口座 | 注文 |
|---------|------|------|
| `mt5-paper-sdk` | デモ | 読み取り専用 |
| `mt5-live-sdk-readonly` | リアル | 読み取り専用 |
| `mt5-paper-trade` | デモ | 直接発注（connector のサイズガードが適用されます） |
| `mt5-live-trade` | リアル | mandate + kill-switch によるゲート |

安全境界: **「paper」はブローカーのデモ口座**を指し、毎回の呼び出しで検証されます — terminal が `account_info().trade_mode` と login を返すため、リアルマネー口座に接続された paper profile（またはその逆）は強制的に拒否されます。MT5 の注文サイズは**ロット**単位です（1 lot EURUSD = 100,000 EUR）。live の mandate ゲートは connector の USD サイジングフックを通じてロットを USD 換算し、connector 自身の `max_order_volume` / `max_order_notional_usd` ガードはデモと live の**両方**に適用され、名目額を価格換算できない場合は fail-closed になります。ヘッジ口座（Exness の既定）での注意: 反対サイドの注文は**ヘッジを新規に建てます** — ポジションは ticket 指定でクローズしてください（position ticket を指定した `trading_cancel_order`）。これにより deal がそのポジションに固定され、エクスポージャーの削減のみが行われます。ロールバック / 停止経路: kill switch は新規の live 注文をブロックし、キャンセルは引き続き利用可能で監査ログに記録されます。Mandate の上限は USD 建てです。USD 以外の口座通貨の場合は、ブローカー側で口座通貨建ての証拠金として強制されます。

`mt5` マーケットデータ loader（為替フォールバックチェーンの先頭）は同じ `mt5.json` を共有します — ファイルがない場合は、最後に使用されたログイン済み terminal に読み取り専用で接続します。

---

## 🔌 eToro Public API コネクタ

API キーペア（`x-api-key` + `x-user-key`）で [eToro Public API](https://builders.etoro.com/) のデモ口座・リアル口座に接続します。デモとリアルは**構造的に**分離されており、デモキーは `/demo` API パスにしか到達しません。

`~/.vibe-trading/etoro.json` を設定します（自分で作成してください。対応環境では `chmod 600`）：

```json
{
  "api_key": "YOUR_PUBLIC_API_KEY",
  "user_key": "YOUR_USER_KEY",
  "profile": "paper"
}
```

代わりに `~/.vibe-trading/.env` で `ETORO_API_KEY` と `ETORO_USER_KEY` を設定することもできます。

その後：

```bash
vibe-trading connector use etoro-paper-sdk
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector quote BTC
```

| プロファイル | 口座 | 発注 |
|-------------|------|------|
| `etoro-paper-sdk` | デモ | 読み取り専用 |
| `etoro-live-sdk-readonly` | リアル | 読み取り専用 |
| `etoro-paper-trade` | デモ | デモパスへの直接発注 |
| `etoro-live-trade` | リアル | mandate + kill switch によるゲート |

銘柄検索は eToro の `internalSymbolFull` 検索を使います（例：`BTC` → instrument id `100000`）。取引前に `etoro_search_instruments` エージェントツールでティッカーを解決してください。

安全境界：デモとリアルはパス分離かつキー束縛です（`paper_guard: path_separated_key_bound`）。リアルでリスクを増やす操作（新規建て、コピー開始/増額）には、認可された mandate、停止していない明確な状態、そしてコピー名目額を制限するための検証済み USD 口座が必要です。検証済みの全決済・部分決済、未約定注文のキャンセル、コピー終了は停止中でも利用でき、すべて監査ログに記録されます。保留中の決済のキャンセルとポジションのストップ編集は**デモ専用**です。これらはエクスポージャーを増やしたり追加証拠金を移動させたりし得る一方、増分の USD リスクを定量化できるだけの API データがないため、リアル経路は fail-closed になります。コピー金額は eToro 口座通貨建てで、コピーの開始・調整のたびに呼び出し側が 1〜35 文字の URL-safe な参照 id を指定する必要があります。eToro 固有の書き込み系ツール（`etoro_close_position`、`etoro_copy_*` など）は**エージェントツール専用**で、MCP や CLI には公開されません。ロールバック：該当コネクタのコミットを revert するかプロファイルを無効化します。halt は新規のリアル・リスク増加操作をブロックします。

---

## 🔌 外部 MCP Server からツールを読み込む（MCP Client モード）

> **これは上の MCP Plugin とは逆方向です。**
> MCP Plugin は*他の* agent に Vibe-Trading のツールを呼ばせるものです。
> 本節は*組み込みの* Vibe-Trading agent が*あなたの*外部 MCP server のツールを呼ぶためのものです。

### クイックスタート

`~/.vibe-trading/agent.json` を作成します：

```json
{
  "mcpServers": {
    "my-server": {
      "command": "uvx",
      "args": ["my-mcp-server"]
    }
  }
}
```

あとは任意の CLI コマンドを実行するだけです。通常の外部 server のツールは、ローカルツールの後に
agent のレジストリへ自動的に注入されます：

```bash
vibe-trading run "use my-server to do X"
```

### IBKR 公式 MCP の読み取り専用プローブ

Vibe-Trading は Interactive Brokers の公式リモート MCP endpoint に読み取り専用で直接接続できます。
`~/.vibe-trading/agent.json` に次を追加します：

```json
{
  "mcpServers": {
    "ibkr": {
      "type": "streamableHttp",
      "url": "https://api.ibkr.com/v1/api/mcp-public",
      "auth": {
        "type": "oauth",
        "scopes": ["mcp.read"],
        "clientName": "Vibe-Trading",
        "cacheDir": "~/.vibe-trading/live/ibkr/oauth"
      },
      "enabledTools": ["*"]
    }
  }
}
```

続いてブラウザでの OAuth フローを開始します：

```bash
vibe-trading connector authorize ibkr-live-official-mcp-readonly
```

ワイルドカードが認められるのは IBKR の `mcp.read` プローブに限られます。この profile を認可しても
確認できるのは IBKR 公式の読み取り scope へのアクセスまでで、IBKR が安全にマッピングできる安定した
読み取りツール名を公開するまで、汎用の `trading_account` と `trading_positions` の呼び出しは無効の
ままです。`mcp.write` を加える設定では、ツールの allowlist を明示的に固定する必要があり、それでも
ライブ発注ガードを通過します。

IBKR から事前登録済みの OAuth client が発行されている場合は、`auth` の中に `clientId` と
`clientSecret` を追加してください。

### 取引 connectors：最短ルート

IBKR の OAuth client 承認を待てない場合は、ローカルの TWS または IB Gateway セッションに接続します。
認証情報は IBKR のデスクトップアプリ内に留まり、Vibe-Trading は `127.0.0.1` に接続して connector
profile として公開するだけです。

オプションの SDK をインストールします：

```bash
pip install "vibe-trading-ai[ibkr]"
```

TWS のペーパートレードまたは IB Gateway のペーパーを開き、API socket clients を有効にしてから実行します：

```bash
vibe-trading connector list
vibe-trading connector use ibkr-paper-local
vibe-trading connector configure ibkr-paper-local --yes
vibe-trading connector check
vibe-trading connector account
vibe-trading connector positions
vibe-trading connector orders
vibe-trading connector quote AAPL
vibe-trading connector history AAPL --duration "30 D" --bar-size "1 day"
```

ローカルの既定ポート：

| アプリ | ペーパー | ライブ読み取り専用 |
|--------|----------|--------------------|
| TWS | `7497` | `7496` |
| IB Gateway | `4002` | `4001` |

agent が公開する connector スコープのツールは `trading_connections`、
`trading_select_connection`、`trading_check`、`trading_account`、`trading_positions`、
`trading_orders`、`trading_quote`、`trading_history` です。ライブブローカーの生の MCP ツールが
`mcp_<broker>_*` として直接登録されることはありません。IBKR の発注ツールは一つも登録されません。

### 🔐 TAP モード — 認証情報の完全分離と人間による書き込み承認

**オプトイン、既定はオフ。** 下記の `TAP_*` 変数が未設定なら、connector の挙動はこれまでと完全に
同じ（ブローカー SDK 直結）で、何も変わりません。

[TAP](https://tap.human.tech)（Tool Authorization Protocol）は認証情報のプロキシです。agent が
ブローカー API の生のシークレットを持つことはなく、影響のある書き込みは**人間の承認**で gate されます。
TAP モードを有効にすると、**すべての** Alpaca 呼び出し（発注・キャンセル・および
account / positions / orders / quote / bars の読み取り）が、ブローカー SDK ではなく TAP プロキシの
`/forward` endpoint へ送られます。TAP がサーバー側で本物のキーを注入してから上流へ転送します。

- agent プロセスは **Alpaca のキーを一切保持しません**。`alpaca-py` すら不要です。egress 全体が
  TAP を通るためで、シークレットは名前（`<CREDENTIAL:alpaca.key_id>`）で参照され、TAP が置換します。
- **書き込みは人間の承認でブロックされます。** 発注もキャンセルも、人が承認しない限りブローカーには
  届きません。prompt インジェクションによる「今すぐ買え」も保留され、拒否すれば Alpaca に届くことは
  ありません。注文には決定的な `client_order_id` が付くため、承認レースでの再試行は重複発注ではなく
  重複排除されます。
- **読み取りは自動承認。** account / positions / orders / quote / bars は GET であり、TAP は人間の
  ステップなしに転送します。これは認証情報の*分離*（プロセス内にキーがない）であって gate ではないので、
  追加の摩擦はほぼゼロです。
- TAP 認証情報の `allowed_hosts` がキーの送信先を固定するため、改ざんされた宛先は注入前に拒否されます（403）。

**有効化の手順：**

1. TAP ダッシュボードで `alpaca` という名前の**マルチシークレット**認証情報を作成し、Alpaca のキーペアを
   `key_id` と `secret_key` のフィールドに格納して agent に割り当て、allowed hosts に
   `paper-api.alpaca.markets`（またはライブの `api.alpaca.markets`）**および** `data.alpaca.markets`
   （quote / bars が使う市場データホスト）を指定します。**ペーパーとライブには別々の TAP 認証情報**を
   使ってください（例：`alpaca-paper` / `alpaca-live`、`TAP_ALPACA_CREDENTIAL` で選択）。それぞれの
   `allowed_hosts` を自分の API ホストに固定すれば、TAP は構造的にペーパーのキーをライブホストへ送ることを
   拒否し、逆も同様で、ペーパー／ライブの分離が端から端まで明確に保たれます。
2. `agent/.env` に追加します：

| 変数 | 必須 | 説明 |
|------|:----:|------|
| `TAP_PROXY_URL` | はい | TAP プロキシのベース URL（例：`https://proxy.tap.human.tech`） |
| `TAP_AGENT_KEY` | はい | あなたの TAP agent API キー（シークレット） |
| `TAP_ALPACA_CREDENTIAL` | いいえ | Alpaca 用の TAP 認証情報名（既定は `alpaca`） |
| `TAP_APPROVAL_TIMEOUT` | いいえ | 人間の判断を待つ秒数（既定は `300`） |

書き込みが発生したら、TAP のチャンネル（Telegram / ダッシュボード）で承認または拒否します。承認された
発注・キャンセルは Alpaca へ転送され、拒否またはタイムアウトしたものはエラーを返し、**決して送信されません**。

> **既知の制限 — 承認レース。** ちょうど `TAP_APPROVAL_TIMEOUT` の境界で人が承認した場合、ポーリング側が
> 既に諦めている一方で TAP が注文を転送してしまうことがあります。この場合、注文はブローカーに届いている
> のに gate はエラーを報告し、`max_trades_per_day` のカウンタが 1 件少なく数えます。決定的な
> `client_order_id` により再試行がその注文を二重に出すことは防げますが、1 日の取引回数上限を厳密に運用
> している場合は、TAP のタイムアウトエラーの後に再試行する前に未約定注文を確認してください。

**スコープ：** Alpaca の**発注・キャンセルと 5 つの読み取りすべて** — つまり connector の egress 全体を
カバーするため、どの経路でもプロセスはキーを保持しません。HMAC 署名型のブローカー（Binance / OKX）は
今後の課題です（クライアント側署名は純粋な egress 注入に馴染みません）。これらのフックは追加的で、
Alpaca connector の内部に閉じており、ライブ mandate ゲートは変更しません。

### 設定リファレンス

| フィールド | 型 | 既定値 | 説明 |
|------------|----|--------|------|
| `type` | string | stdio では推論、HTTP では必須 | stdio では省略、URL ベースの server では `sse` / `streamableHttp` を指定。 |
| `command` | string | stdio では必須 | stdio server で起動する実行ファイル。`sse` / `streamableHttp` では無効。 |
| `args` | array | `[]` | stdio server 専用のコマンドライン引数。 |
| `env` | object | `{}` | stdio server 専用。サブプロセスの環境にマージされる追加の環境変数。 |
| `url` | string | `sse` / `streamableHttp` では必須 | リモート SSE / streamable HTTP endpoint の URL。stdio では未使用。 |
| `headers` | object | `{}` | `sse` / `streamableHttp` server 専用の追加 HTTP ヘッダー。 |
| `toolTimeout` | number | `30` | ツール呼び出し 1 回あたりのタイムアウト（秒） |
| `initTimeout` | number | 未設定（`max(toolTimeout, 30)`） | MCP initialize / OAuth 認可のタイムアウト（秒）。通常のツール呼び出しを広げずに、遅いブラウザ認可に対応するために使います。 |
| `enabledTools` | array | `["*"]` | ツールの allowlist。`["*"]` でその server の全ツールを公開 |

設定ファイルの場所：`~/.vibe-trading/agent.json`（JSON または YAML）。

URL ベースの transport では `type` が必須です。agent は URL の接尾辞から SSE と streamable HTTP を
推測しなくなりました。

### セッション単位の上書き（API）

API で session を作成する際、`session.config` の中に `mcpServers` を渡すと、そのセッションに限って
グローバル設定を拡張・上書きできます：

```json
{
  "config": {
    "mcpServers": {
      "research-server": {
        "command": "uvx",
        "args": ["research-mcp"],
        "enabledTools": ["search", "fetch"]
      }
    }
  }
}
```

### ツールの命名

通常のリモートツールは安定した名前 `mcp_<server>_<tool>` で公開されます。
ライブブローカーの MCP server は `trading_*` connector の表面の背後に留まります。

2 つの server 名がローカル名の正規化後に同じ ASCII セーフな接頭辞になる場合（例：`foo-bar` と
`foo_bar` がどちらも `foo_bar` になる）、名前の一意性を保つために server セグメントへ決定的なハッシュ
接尾辞が付加され、運用者に警告が出ます：

```
WARNING: Configured MCP server 'foo-bar' collides with another server after local name
normalization. Using local tool prefix 'mcp_foo_bar_<hash>_<tool>' to keep generated
tool names unique. Rename the server in agent config if you want a different prefix.
```

### v1 の制限

| 制限 | 詳細 |
|------|------|
| Transport | stdio、SSE、streamable HTTP |
| 実行 | 直列のみ — MCP ツールが並列 readonly 経路に入ることはありません |
| 対象面 | tools のみ（v1 では resources と prompts は対象外） |
| ホットリロード | 非対応 — 設定変更の反映にはプロセス再起動が必要 |
| Swarm 経路 | v1 では Swarm worker のレジストリに MCP ツールは入りません |

---

## 📁 プロジェクト構成

<details>
<summary><b>クリックして展開</b></summary>

```
Vibe-Trading/
├── agent/                          # バックエンド (Python)
│   ├── cli/                        # CLI パッケージ — インタラクティブ TUI + サブコマンド
│   ├── api_server.py               # FastAPI サーバー — runs、sessions、upload、swarm、SSE
│   ├── mcp_server.py               # MCP サーバー — OpenClaw / Claude Desktop 向け 74 tools
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct エージェントコア
│   │   │   ├── loop.py             #   5 層コンテキスト圧縮 + read/write ツールバッチング
│   │   │   ├── context.py          #   システムプロンプト + 永続メモリからの自動 recall
│   │   │   ├── skills.py           #   skill ローダー（90 個同梱 + CRUD でユーザー作成）
│   │   │   ├── tools.py            #   ツール基底クラス + レジストリ
│   │   │   ├── memory.py           #   run ごとの軽量ワークスペース状態
│   │   │   ├── frontmatter.py      #   共有 YAML frontmatter パーサー
│   │   │   └── trace.py            #   実行トレースライター
│   │   │
│   │   ├── memory/                 # クロスセッション永続メモリ
│   │   │   └── persistent.py       #   ファイルベースメモリ (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 107 個の自動検出エージェントツール
│   │   │   ├── backtest_tool.py    #   バックテスト実行
│   │   │   ├── remember_tool.py    #   クロスセッションメモリ (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 クロスセッション検索
│   │   │   ├── swarm_tool.py       #   swarm チームを起動
│   │   │   ├── web_search_tool.py  #   DuckDuckGo Web 検索
│   │   │   └── ...                 #   bash、file I/O、factor analysis、options、alpha browser + bench など
│   │   │
│   │   ├── factors/                # Alpha Zoo — 5 つのファミリーにまたがる 462 個の alpha
│   │   │   ├── base.py             #   19 個のオペレーター (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   AST 限定のメタデータ読み込み + 遅延計算 + sanity gate
│   │   │   ├── bench_runner.py     #   IC + alive/reversed/dead 分類
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (12) + fundamental (4)
│   │   │
│   │   ├── api/                    # FastAPI ルートモジュール
│   │   │   └── alpha_routes.py     #   /alpha/list、/alpha/{id}、/alpha/bench、SSE ストリーム
│   │   │
│   │   ├── skills/                 # 9 カテゴリ 90 個の finance skills（各 SKILL.md）
│   │   ├── swarm/                  # Swarm DAG 実行エンジン
│   │   │   └── presets/            #   30 個の swarm preset YAML 定義
│   │   ├── session/                # マルチターンチャット + FTS5 セッション検索
│   │   └── providers/              # LLM プロバイダー抽象化
│   │
│   └── backtest/                   # バックテストエンジン
│       ├── engines/                #   8 エンジン + クロスマーケット composite engine + options_portfolio
│       ├── loaders/                #   24 ソース: tushare、okx、binance、yfinance、akshare、baostock、tencent、mootdx、ccxt、futu、pykrx、local、eastmoney、sina、stooq、yahoo、finnhub、alphavantage、tiingo、fmp、longbridge、mt5、qveris、india_broker
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + 自動フォールバックチェーン
│       └── optimizers/             #   MVO、equal vol、max div、risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home、Agent、AlphaZoo、RunDetail、Compare、Correlation、Settings
│       ├── components/             #   chat、charts、layout
│       └── stores/                 #   Zustand 状態管理
│
├── Dockerfile                      # マルチステージビルド
├── docker-compose.yml              # 1 コマンドデプロイ
├── pyproject.toml                  # パッケージ設定 + CLI エントリポイント
├── tools/                          # リポジトリレベルの CI ヘルパー
│   └── ci_grep_gates.sh            # yaml.load / 商標 / 銘柄データ漏洩を拒否
└── LICENSE                         # MIT
```

</details>

---

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
  </tr>
</table>

---

## 🗺 ロードマップ

> 段階的に出荷します。作業が始まった項目は [Issues](https://github.com/HKUDS/Vibe-Trading/issues) に移動します。

| Phase | Feature | Status |
|-------|---------|--------|
| **Trust Layer** | 再現可能な run cards は出力・Run Detail 表示まで完了。v1 では tool traces と citations を追加 | v0 出荷済み |
| **Hypothesis Registry** | lifecycle status、data sources、skills、run-card links、invalidation notes を持つ永続リサーチ仮説 | Backend MVP 出荷済み |
| **Research Autopilot** | 手動実行から始める research loop: hypothesis → deterministic backtest → evidence report | フェーズ1–3 出荷済み |
| **Data Bridge** | Bring-your-own data: local CSV/Parquet/SQL connectors with schema mapping | ローカルローダー出荷済み |
| **Options Lab** | Vol surface, Greeks dashboard, payoff/scenario explorer | Planned |
| **Portfolio Studio** | Risk x-ray, constraints, turnover-aware optimizer, rebalance notes | Turnover を考慮したオプティマイザは **0.1.11 でリリース済み**；残りは Planned |
| **Alpha Zoo** | 462 個の事前構築 alpha 因子（Qlib 158 + Kakushadze 101 + GTJA 191 + academic + fundamental）、1 行 CLI でベンチ、agent 統合、Web UI | **0.1.8 でリリース済み**、0.1.12 まで拡張 |
| **Strategy Development Manager** | Register papers / broker research as factors & strategies with a persistent store + automated IC/Sharpe decay lifecycle | **0.1.11 でリリース済み** |
| **Correlation Regime** | Edge-density + hysteresis regime timeline layered on `/correlation` — spot when markets fuse into one bloc | **0.1.12 でリリース済み** |
| **Research Delivery** | Slack / Telegram / email-style IM channels 経由の scheduled briefs と live research sessions | スケジューラ + IM Runtime 出荷済み |
| **Community** | Shareable skills, presets, and strategy cards | Exploring |

---

## Contributing

Contributions を歓迎します。ガイドラインは [CONTRIBUTING.md](CONTRIBUTING.md) を参照してください。

**Good first issues** は [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) でタグ付けされています。気になるものから始めてください。

より大きな貢献を検討している場合は、上の [Roadmap](#-ロードマップ) を確認し、着手前に issue を開いて相談してください。

---

## Contributors

Vibe-Trading に貢献してくださった皆さまに感謝します。

最近の v0.1.14 サイクルの貢献者とクレジット：

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

<details>
<summary>v0.1.12 サイクルの貢献者</summary>

- @santhreal — a 30-PR correctness sweep: strict-JSON / finite-number hardening across metrics, factors, pattern, and options (#764/#765/#766/#767/#739/#740/#744), loader correctness (#761 yahoo 1m bars), and session / journal robustness (#762/#763/#768/#769/#770)
- @xkam7ar — broad reliability across packaging, web, scheduler, swarm, and CLI (#584), cancellation before the first AgentLoop iteration (#641, closes #638), QVeris session budget + atomic credit accounting (#685/#686), CI / OOS gates (#630/#632), and journal month-filter / side-parse fixes (#626/#628)
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
- @warren618 / Haozhe Wu — the fundamental factor layer (PIT-safe SEC panels), the QVeris premium track, the IM channel runtime, India-equity integration review, CN search fallbacks, and release integration

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

---

## Disclaimer

Vibe-Trading は研究・取引ソフトウェアです。投資助言ではなく、資金を一切保管せず、取引所も運営しません。取引はご自身が明示的に認可したブローカーチャネル（例: Robinhood Agentic Trading）を通じてのみ行われ、設定した制限の範囲内で、いつでも停止できます。このブローカー取引機能は実験的であり、当方が実際のブローカー口座で検証したものではありません——自己責任でご利用ください。過去の成績は将来の結果を保証しません。

## License

MIT License — see [LICENSE](LICENSE)

---

<p align="center">
  ⭐ <b>Vibe-Trading</b> が研究の役に立ったら、Star を付けると他の人にも見つけてもらえます。
</p>

---

<p align="center">
  <b>Vibe-Trading</b> をご覧いただきありがとうございます ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
