<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <b>العربية</b>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="شعار Vibe-Trading"/>
</p>

<h1 align="center">Vibe-Trading: وكيل التداول الشخصي الخاص بك</h1>

<p align="center">
  <b>أمر واحد يمنح وكيلك قدرات تداول شاملة</b>
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
  <a href="https://vibetrading.wiki/">الموقع</a> &nbsp;&middot;&nbsp;
  <a href="https://vibetrading.wiki/docs/">الوثائق</a> &nbsp;&middot;&nbsp;
  <a href="#-الأخبار">الأخبار</a> &nbsp;&middot;&nbsp;
  <a href="#-الميزات-الرئيسية">الميزات</a> &nbsp;&middot;&nbsp;
  <a href="#-حساب-الظل">حساب الظل</a> &nbsp;&middot;&nbsp;
  <a href="#-العرض-التوضيحي">العرض التوضيحي</a> &nbsp;&middot;&nbsp;
  <a href="#-البدء-السريع">البدء السريع</a> &nbsp;&middot;&nbsp;
  <a href="#-أمثلة">أمثلة</a> &nbsp;&middot;&nbsp;
  <a href="#-خادم-api">API / MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-خارطة-الطريق">خارطة الطريق</a> &nbsp;&middot;&nbsp;
  <a href="#المساهمة">المساهمة</a>
</p>

<p align="center">
  <a href="#-البدء-السريع"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 الأخبار

> ⚠️ **تحذير أمني:** حساب X باسم `VibeTrading_HKU`، ومشروع Virtuals رقم `101845`، وعقد التوكن `0x640BDBF77b6447E8b7DB7894cED84BD1c40571f4` كلّها غير رسمية ولا تتبع Vibe-Trading. لم نُطلق أو نؤيد مطلقًا أي توكن أو عملة ميم. لا تشترِ هذا التوكن، ولا تربط محفظتك، ولا توقّع أي شيء. [التفاصيل](SECURITY.md#official-channels--impersonation).

- **2026-07-12** 🧪 **مدير تطوير الاستراتيجيات + دفعة إصلاحات المساهمين**: مهارة `strategy-dev-manager` الجديدة (رقم 87) تحوّل الأوراق الأكاديمية وتقارير الوسطاء إلى عوامل/استراتيجيات مسجلة مع مخزن artifacts دائم ومراقبة تلقائية لاضمحلال IC/Sharpe — تقود أدوات `sdm_register` / `sdm_status` / `sdm_decay_scan` دورة الحياة active → monitoring → decayed → disabled فوق `~/.vibe-trading/` ([#457](https://github.com/HKUDS/Vibe-Trading/pull/457)، يغلق [#455](https://github.com/HKUDS/Vibe-Trading/issues/455)، شكراً @shadowinlife). كما دُمج: يقبل تبويب Correlation رموزاً مجردة (`AAPL,SPY`) ويمشي سلسلة loader fallback كاملة ([#472](https://github.com/HKUDS/Vibe-Trading/pull/472)، يغلق [#471](https://github.com/HKUDS/Vibe-Trading/issues/471)، شكراً @yxhuang)، ويحترم `local` loader الفاصل الزمني المطلوب عبر إعادة تجميع OHLCV ([#467](https://github.com/HKUDS/Vibe-Trading/pull/467)، شكراً @Shizoqua)، ووصل تاريخ عقود Binance USD-M الدائمة مع توجيه صريح `BTC-USDT-PERP` وفصل سعر التنفيذ عن سعر العلامة كأول شريحة من [#462](https://github.com/HKUDS/Vibe-Trading/issues/462) ([#470](https://github.com/HKUDS/Vibe-Trading/pull/470)، شكراً @honginp)، وتعمل استيرادات FastMCP transport عبر كلا تخطيطي الوحدات ([#469](https://github.com/HKUDS/Vibe-Trading/pull/469)، شكراً @roberttidball)، وأصبح Requesty متاحاً كمزوّد بوابة LLM متوافقة مع OpenAI ([#474](https://github.com/HKUDS/Vibe-Trading/pull/474)، شكراً @Thibaultjaigu).

- **2026-07-11** 🚀 **صدر الإصدار v0.1.11** (`pip install -U vibe-trading-ai`): يجمع ثلاثة أسابيع من العمل منذ 0.1.10 — اختبار رجعي من الدرجة الأولى للأسهم الهندية (NSE/BSE)، وطبقة العوامل الأساسية الآمنة زمنياً (PIT-safe) (Alpha Zoo → 460)، وبيئة تشغيل قنوات IM بـ16 محوّلاً، والأبحاث المجدولة من طرف إلى طرف، وبيانات QVeris المدفوعة الاختيارية، ودفعة مساهمي اليوم: محسّن يراعي الدوران ([#466](https://github.com/HKUDS/Vibe-Trading/pull/466)، شكراً @Robin1987China)، وأداة رؤية `analyze_image` + إقران NapCat DM + إصلاح قراءة وسائط IM ([#464](https://github.com/HKUDS/Vibe-Trading/pull/464)/[#463](https://github.com/HKUDS/Vibe-Trading/pull/463)/[#465](https://github.com/HKUDS/Vibe-Trading/issues/465)، شكراً @fei-moss)، وتسلسل Longbridge Decimal ([#459](https://github.com/HKUDS/Vibe-Trading/pull/459)، شكراً @fanfpy)، وحُرّاس عدّ المانيفست المحزوم ([#461](https://github.com/HKUDS/Vibe-Trading/pull/461)، شكراً @asahikiko). التفاصيل الكاملة: [CHANGELOG](CHANGELOG.md) · [ملاحظات الإصدار](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.11).

- **2026-07-10** 🇮🇳 **دعم الأسهم الهندية (NSE/BSE) + مركزية متغيرات البيئة**: محرك مخصص `IndiaEquityEngine` — تسوية T+1، ونطاقات حدود السعر، وحزمة تكاليف STT/الدمغة/البورصة/SEBI/GST قابلة للتهيئة — مع توجيه رموز `.NS`/`.BO`، وجسر بيانات Shoonya/Dhan للقراءة فقط (اختياري)، وانضمام 255 عاملاً من alpha101/qlib158 إلى الكون الجديد `equity_in` ([#305](https://github.com/HKUDS/Vibe-Trading/pull/305)، شكرًا @muku314115). تتدفق متغيرات البيئة الآن عبر مخطط Pydantic واحد `EnvConfig` مع بوابة CI تعتمد على AST لمنع انتشار `os.getenv` مستقبلاً ([#440](https://github.com/HKUDS/Vibe-Trading/pull/440)، يغلق [#438](https://github.com/HKUDS/Vibe-Trading/issues/438)، شكرًا @shadowinlife). أيضًا: مربع تأكيد ثانٍ قبل اعتماد تفويض تداول حقيقي مع توحيد رسائل الأخطاء ([#453](https://github.com/HKUDS/Vibe-Trading/pull/453)، شكرًا @wison1717-maker)، واختبارات مسارات scheduled-research ([#452](https://github.com/HKUDS/Vibe-Trading/pull/452)، شكرًا @Robin1987China)، ولم تعد نماذج GLM التفكيرية تفقد تدفق الاستدلال على مزود zhipu ([#458](https://github.com/HKUDS/Vibe-Trading/issues/458)).

<details>
<summary>أخبار سابقة</summary>

- **2026-07-09** 🧯 **إزالة عائق بدء Docker + دفعة مساهمين لـ provider/CLI**: لم يعد بدء Docker/server ينهار عندما يمرّ FastAPI route iteration على عنصر included-router-like لا يملك `path` ([#450](https://github.com/HKUDS/Vibe-Trading/issues/450)، شكراً @Penn-Live). كما دُمجت دفعة quick-win من إصلاحات المساهمين: توحّدت تواقيع `fetch()` في loaders الخاصة بـ OKX / Tushare / yfinance مع البروتوكول ([#437](https://github.com/HKUDS/Vibe-Trading/pull/437)، شكراً @shadowinlife)، ويحفظ CLI resume prompt أول رسالة يكتبها المستخدم ([#448](https://github.com/HKUDS/Vibe-Trading/pull/448)، يغلق [#447](https://github.com/HKUDS/Vibe-Trading/issues/447)، شكراً @morluto)، وتحوّل default في Codex OAuth إلى `openai-codex/gpt-5.4` ([#446](https://github.com/HKUDS/Vibe-Trading/pull/446)، شكراً @morluto)، وأصبح Kimi for Coding مزوداً مستقلاً ([#435](https://github.com/HKUDS/Vibe-Trading/pull/435)، شكراً @yxhuang)، ووُصلت opencode provider mappings ([#444](https://github.com/HKUDS/Vibe-Trading/pull/444)، شكراً @imsankz)، كما صُححت code fences في مراجع Tushare من `pyhton` إلى `python` ([#449](https://github.com/HKUDS/Vibe-Trading/pull/449)، شكراً @flash1234pku). شمل التحقق focused server/CLI/provider/loader tests وDocker build و`/health` smoke.

- **2026-07-08** 💎 **طبقة العوامل الأساسية (المرحلة 1) + بيانات QVeris المدفوعة الاختيارية + يوم صيانة**: بيانات SEC المالية الآمنة زمنياً (PIT-safe) تتدفق الآن مباشرة إلى panels العوامل اليومية —— أعمدة `fund:*`، وتثبيت على تاريخ `filed` (مع حماية من إعادة البيانات وإطارات YTD)، و4 عوامل جودة/قيمة جديدة (يضم zoo الآن 460 alphas). اكتسب توجيه البيانات مساراً مدفوعاً اختيارياً: تبقى المصادر المجانية الـ18 هي الافتراضية، بينما يفتح QVeris أكثر من 63 مزوداً عبر Settings → QVeris أو `vibe-trading data mode paid` (انظر قسم QVeris أدناه). أيضاً: اكتملت وحدات `api_server` (من 1,103 إلى 371 سطراً، [#424](https://github.com/HKUDS/Vibe-Trading/pull/424) يغلق [#331](https://github.com/HKUDS/Vibe-Trading/issues/331)، شكراً @shadowinlife)، ولم يعد `validation.json` في الاختبار الخلفي يتطلب وجود دليل artifacts مسبقاً ([#429](https://github.com/HKUDS/Vibe-Trading/pull/429)، شكراً @isaveall)، وأصبحت أخطاء `--swarm-run` أوضح ([#428](https://github.com/HKUDS/Vibe-Trading/issues/428)، شكراً @isaveall)، وقمنا بالتراجع عن governance stack الذي عطّل محادثات الجلسات ([#433](https://github.com/HKUDS/Vibe-Trading/issues/433)، شكراً @yxhuang على التشخيص الدقيق).

- **2026-07-07** ✅ **دفعة PR للمساهمين**: دُمجت أعمال المساهمين المنتظرة: إعداد IM channel timeout ([#413](https://github.com/HKUDS/Vibe-Trading/pull/413)، شكراً @SyntaxSawdust)، وAlpha Library social previews ودليل المبتدئين ([#396](https://github.com/HKUDS/Vibe-Trading/pull/396)، [#393](https://github.com/HKUDS/Vibe-Trading/pull/393)، شكراً @kadaliao)، وvalue-investing skills / tools / committee presets ([#407](https://github.com/HKUDS/Vibe-Trading/pull/407)، شكراً @sambazhu)، ومعالجة حقول order sizing ذات القيمة الصفرية في `trading_place_order` ([#417](https://github.com/HKUDS/Vibe-Trading/pull/417)، شكراً @irfanallana-oss)، وtimezone-aware UTC timestamps عبر session/API paths ([#397](https://github.com/HKUDS/Vibe-Trading/pull/397)، شكراً @mustafakamal88).

- **2026-07-06** 🧭 **تقوية preflight وشرائح API وCN search fallback**: لم يعد provider preflight يتبع redirect ([#404](https://github.com/HKUDS/Vibe-Trading/pull/404)، يغلق [#402](https://github.com/HKUDS/Vibe-Trading/issues/402)، شكراً @SyntaxSawdust)، وانتقلت بقية API routes إلى focused modules ([#387](https://github.com/HKUDS/Vibe-Trading/pull/387)، supersedes [#383](https://github.com/HKUDS/Vibe-Trading/pull/383)-[#386](https://github.com/HKUDS/Vibe-Trading/pull/386)، شكراً @shadowinlife). يشمل CN web-search fallback الآن Alibaba Cloud IQS ([#408](https://github.com/HKUDS/Vibe-Trading/pull/408)، شكراً @sambazhu). وأضافت cleanup من الصيانة اختبارات no-network fallback وتنظيف EOF whitespace ([fbac74f](https://github.com/HKUDS/Vibe-Trading/commit/fbac74f77bfed58dd7fc23d0f001c29190b4b2b6))؛ وأصبح main CI أخضر ([run 28780619018](https://github.com/HKUDS/Vibe-Trading/actions/runs/28780619018)).

- **2026-07-05** ✅ **إغلاق دفعة PR للمساهمين ونجاح Windows baseline**: دُمجت اليوم أربعة PR غير draft اختيرت للمراجعة. لم تعد عمليات A-share mootdx batch pull تبتلع `KeyboardInterrupt` / `SystemExit` عبر bare `except`، ويمكن الآن إيقاف السحب الطويل بـ `Ctrl+C` بشكل صحيح ([#399](https://github.com/HKUDS/Vibe-Trading/pull/399)، يغلق [#398](https://github.com/HKUDS/Vibe-Trading/issues/398)، شكراً @shadowinlife). دُمجت أيضاً Settings route slice وحدود التبعيات المصححة عبر PR الأصلية مع حفظ credit للمساهمين ([#382](https://github.com/HKUDS/Vibe-Trading/pull/382)، [#390](https://github.com/HKUDS/Vibe-Trading/pull/390)، شكراً @shadowinlife و@aeonframework). أصبحت Windows baseline compatibility تعزل loader caches، وتجعل OAuth cache assertions واعية بالمنصة، وتتخطى اختبار fork-only mock واحداً على Windows، وتتجاوز proxy في MCP loopback fixtures ([#401](https://github.com/HKUDS/Vibe-Trading/pull/401)، شكراً @Elfsa-Miranda). Validation: `4701 passed, 47 skipped`.

- **2026-07-04** 🧩 **شرائح API routes، ودليل صيني للمبتدئين، وحدود تبعيات أكثر أماناً**: انتقلت IM channel وSettings routes من `api_server.py` إلى `src/api/channels_routes.py` / `src/api/settings_routes.py` متابعةً لمسار [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) الضيق للتقسيم المعياري ([#379](https://github.com/HKUDS/Vibe-Trading/pull/379)، [#382](https://github.com/HKUDS/Vibe-Trading/pull/382)، شكراً @shadowinlife). أضيف إلى Wiki دليل صيني للمبتدئين غير المتخصصين في المالية ([#393](https://github.com/HKUDS/Vibe-Trading/pull/393)، شكراً @kadaliao)، وتحدّثت حدود Pillow / LangChain / LangGraph إلى مسار patched قابل للتثبيت ([#390](https://github.com/HKUDS/Vibe-Trading/pull/390)، شكراً @aeonframework).

- **2026-07-04** 🧹 **تنظيف طوابع UTC الزمنية لمسارات الجلسات وAPI**: تم إحكام إصلاح الطوابع الزمنية #395 بحيث تُصدر طوابع session وgoal وchannel وAPI قيم UTC واعية بالمنطقة الزمنية بصيغة ISO صريحة.

- **2026-07-03** 🛡️ **Robinhood MCP refresh + API modularization + SSRF guard**: يستخدم Robinhood Agentic Trading الآن أسماء MCP الحالية عبر generic reads وlive-runner plumbing وdefault read-only seeds واختبارات mandate-gate، كما يحترم interactive startup ترتيب البحث نفسه عن `.env` الذي يستخدمه provider loader (`~/.vibe-trading/.env` → `agent/.env` → `$CWD/.env`) ([#391](https://github.com/HKUDS/Vibe-Trading/pull/391)، يغلق [#381](https://github.com/HKUDS/Vibe-Trading/issues/381) و[#380](https://github.com/HKUDS/Vibe-Trading/issues/380)). انتقلت System routes (`/health` و`/correlation` و`/system/shutdown` و`/skills` و`/api`) إلى `src/api/system_routes.py` كـ narrow API modularization slice تالية ([#378](https://github.com/HKUDS/Vibe-Trading/pull/378)، شكراً @shadowinlife). ترفض channel media SSRF defenses الآن أهداف CGNAT/mesh/non-global وQQ media redirect-to-internal قبل fetch ([#389](https://github.com/HKUDS/Vibe-Trading/pull/389)، شكراً @hobostay).

- **2026-07-02** ⚡ **Factor acceleration + safer runtime boundaries**: تستخدم مسارات rolling factor الساخنة الآن fast paths عبر `bottleneck`/NumPy، وتتجنب موازاة alpha bench تمرير panel payload ضخم لكل worker مراراً، وأضيفت regression coverage لحسابات base equity ([#376](https://github.com/HKUDS/Vibe-Trading/pull/376)، يغلق [#339](https://github.com/HKUDS/Vibe-Trading/issues/339)، والعمل الأصلي من [#342](https://github.com/HKUDS/Vibe-Trading/pull/342) بواسطة @shadowinlife). نُقلت Upload وShadow report routes من `api_server.py` الضخم كأول slice ضيق من API modularization، مع إبقاء [#331](https://github.com/HKUDS/Vibe-Trading/issues/331) مفتوحاً ([#375](https://github.com/HKUDS/Vibe-Trading/pull/375)، مبني على [#358](https://github.com/HKUDS/Vibe-Trading/pull/358)، شكراً @shadowinlife). ترث عمليات generated backtest الفرعية الآن بيئة allowlist فقط بدلاً من parent secrets surface الكامل ([#374](https://github.com/HKUDS/Vibe-Trading/pull/374)، يغلق [#332](https://github.com/HKUDS/Vibe-Trading/issues/332))، وحصلت IM channels على `/new` session reset وأوامر pairing غير حساسة لحالة الأحرف ([#372](https://github.com/HKUDS/Vibe-Trading/pull/372)، يغلق [#371](https://github.com/HKUDS/Vibe-Trading/issues/371)، شكراً @shadowinlife).

- **2026-07-01** 🧹 **Security polish + tracker cleanup**: شُدِّدت defaults الخاصة بـ API/Docker/frontend dev، واستقرت Settings channel و`zh-CN` edges، وأُزيلت frontend dependency/CSP alerts، ونُظِّفت عناصر WhatsApp + paper-trading القديمة من tracker ([#338](https://github.com/HKUDS/Vibe-Trading/pull/338)، [#351](https://github.com/HKUDS/Vibe-Trading/pull/351)، [#349](https://github.com/HKUDS/Vibe-Trading/pull/349)، [#365](https://github.com/HKUDS/Vibe-Trading/pull/365)، [#367](https://github.com/HKUDS/Vibe-Trading/pull/367)، [#350](https://github.com/HKUDS/Vibe-Trading/pull/350)، [#335](https://github.com/HKUDS/Vibe-Trading/pull/335)، [#283](https://github.com/HKUDS/Vibe-Trading/issues/283)).

- **2026-06-30** 💬 **بيئة تشغيل قنوات IM لتسليم الأبحاث**: يستطيع Vibe-Trading الآن وصل بيئة تشغيل جلسة agent نفسها بـ 16 محوّلاً مدمجاً للرسائل — WebSocket وTelegram وSlack وDiscord وMatrix وWhatsApp وSignal وQQ/NapCat وWeChat/WeCom وFeishu/Lark وDingTalk وTeams وemail وMochat. تغطي CLI (`vibe-trading channels status/start/stop/login/pairing`) وREST (`/channels/status` و`/channels/start` و`/channels/stop` و`/channels/pairing/command`) ولوحة Web UI Settings الحالة وتلميحات الاسترداد والبدء/الإيقاف وsender pairing؛ وتبقى المحولات المعتمدة على SDK خلف extras مثل `vibe-trading-ai[telegram]` أو `vibe-trading-ai[channels]` ([#341](https://github.com/HKUDS/Vibe-Trading/pull/341)).

- **2026-06-29** 🛡️ **Live advisory safety + Trading 212 read-only connector + Windows/Gemini fixes**: live order guards now have an opt-in, broker-agnostic `PreTradeAdvisoryInterface` that records advisory reviews without bypassing the mandate gate, kill switch, or audit trail ([#328](https://github.com/HKUDS/Vibe-Trading/pull/328), closes [#317](https://github.com/HKUDS/Vibe-Trading/issues/317), thanks @shadowinlife). Trading 212 joins the connector layer with read-only account, positions, orders, history, and instrument-metadata support; `place_order` / `cancel_order` still hard-refuse until a structural paper/live boundary exists ([#321](https://github.com/HKUDS/Vibe-Trading/pull/321), closes [#309](https://github.com/HKUDS/Vibe-Trading/issues/309), thanks @mvanhorn). Windows startup avoids the pandas 3.0 `Timestamp` crash via the `<3.0.0` constraint ([#329](https://github.com/HKUDS/Vibe-Trading/pull/329), closes [#324](https://github.com/HKUDS/Vibe-Trading/issues/324), thanks @hannibal-lee); Gemini `thought_signature` dict-history replay was verified/fixed on `main` ([#318](https://github.com/HKUDS/Vibe-Trading/issues/318)); `.US` financial statements now route to SEC EDGAR instead of Eastmoney ([#325](https://github.com/HKUDS/Vibe-Trading/issues/325)); and the Alpha Library landing page got cache/date/selector/noscript/DNS-prefetch hardening while heavier CSP and social-card follow-ups stay tracked ([#323](https://github.com/HKUDS/Vibe-Trading/issues/323)).

- **2026-06-28** 🧰 **أوامر setup/dev عبر المنصات + تقوية runtime وأدوات الملفات**: يتعامل `vibe-trading setup` و`vibe-trading dev` الآن مع بناء TypeScript على Windows، وتشغيل backend من cwd الصحيح، واستخدام منفذ Vite 5899، وإغلاق العمليات الفرعية بنظافة عند الخروج ([#292](https://github.com/HKUDS/Vibe-Trading/pull/292)، شكراً @digger-yu). كما أصبح polling لحالة Runtime يتدهور بأمان بدل الانهيار ([#322](https://github.com/HKUDS/Vibe-Trading/issues/322))، وتُنظَّف مفاتيح cache الخاصة بـ MCP OAuth ([#313](https://github.com/HKUDS/Vibe-Trading/issues/313))، وشُدِّدت defaults الخاصة بـ OpenAI والتحقق من Robinhood `agent.json` ([#319](https://github.com/HKUDS/Vibe-Trading/pull/319)، [#320](https://github.com/HKUDS/Vibe-Trading/pull/320)، شكراً @mvanhorn)، وحصلت أدوات الملفات على read/write roots منفصلة واختبارات sandbox أوسع ([#299](https://github.com/HKUDS/Vibe-Trading/pull/299)، شكراً @skloxo).
- **2026-06-27** 🧯 **مرونة content-filter + تنظيف عقد features في Shadow Account**: أصبحت تشغيلات event-driven وswarm تتجاوز إصابات content-moderation الفردية من LLM، وتعرض تحذيراً في run cards عندما ترتفع معدلات الفلترة، وتتعرف على أسباب Gemini safety finish بدلاً من إيقاف التحليل كاملاً ([#308](https://github.com/HKUDS/Vibe-Trading/pull/308)، يغلق [#307](https://github.com/HKUDS/Vibe-Trading/issues/307)، شكراً @shadowinlife). كما تشترك مراحل استخراج Shadow Account وتوليد الكود في عقد `PRICE_FEATURES` واحد وتحافظ على حدود العوائد بأربع منازل عشرية، ما يمنع drift بين القاعدة والكود وفقدان دقة `prior_5d_return` ([#316](https://github.com/HKUDS/Vibe-Trading/pull/316)، شكراً @Robin1987China).
- **2026-06-26** 🎯 **دخول مشروط لـ Shadow Account + توجيه tushare لـ ETF/المؤشرات/هونغ كونغ**: أصبحت قواعد Shadow Account المستخرجة تحمل نطاقات RSI / العائد السابق، فيدخل SignalEngine المُولَّد بناءً على شروط حقيقية (RSI ضمن النطاق، والعائد السابق ضمن النطاق) بدلاً من تكرار وتيرة الاحتفاظ بشكل أعمى ([#314](https://github.com/HKUDS/Vibe-Trading/pull/314)، متابعة لـ [#302](https://github.com/HKUDS/Vibe-Trading/pull/302)، شكراً @Robin1987China). كما يوجّه loader الخاص بـ tushare صناديق ETF/LOF إلى `fund_daily()`، والمؤشرات إلى `index_daily()`، وأسهم هونغ كونغ إلى `hk_daily()` بدلاً من استدعاء `daily()` الذي يعيد فراغاً بصمت لغير الأسهم، مع تحذيرات لكل رمز عن النتائج الفارغة والجلب الجزئي ([#315](https://github.com/HKUDS/Vibe-Trading/pull/315)، يغلق [#310](https://github.com/HKUDS/Vibe-Trading/issues/310)، شكراً @shadowinlife).
- **2026-06-25** 🧪 **JSON صارم للتحقق + سياق agent أهدأ**: أصبح مسار التحقق المستقل للاختبار الخلفي يطبّع قيم `NaN` / `Infinity` المتداخلة قبل كتابة `artifacts/validation.json` أو stdout في CLI، فلا تتعطل parsers الصارمة أمام payload التحقق ([#306](https://github.com/HKUDS/Vibe-Trading/pull/306)، شكراً @gyx09212214-prog). كما صار prompt الخاص بالـ agent يستنتج عدد مصادر البيانات الحالي من loader registry، ولا تعمل `_microcompact()` إلا عند وجود ضغط tokens حقيقي، فلا تُمسح نتائج الأدوات القديمة مبكرًا في التشغيلات القصيرة ([#296](https://github.com/HKUDS/Vibe-Trading/pull/296)، يغلق [#282](https://github.com/HKUDS/Vibe-Trading/issues/282)، شكراً @MarkfuGod).
- **2026-06-24** 🎯 **سياق سعري لـ Shadow Account + واجهة صينية تفاعلية + إصلاح auth على LAN**: أصبح استخراج قواعد Shadow Account يرى سياق الدخول الآمن point-in-time — `entry_rsi14` و`prior_5d_return` عبر loader registry عند `buy_dt` — مع تدهور graceful عند عدم توفر الشبكة أو البيانات ([#302](https://github.com/HKUDS/Vibe-Trading/pull/302)، متابعة لـ [#295](https://github.com/HKUDS/Vibe-Trading/issues/295)، شكراً @Robin1987China). كما انتقلت اللوحات الرئيسية في Web UI إلى ترجمات English / zh-CN تفاعلية عبر charts وchat وAlpha Library وCorrelation وRun Detail ([#301](https://github.com/HKUDS/Vibe-Trading/pull/301)، شكراً @skloxo). وبعد تحصين CSRF، عادت deployments البعيدة same-origin التي تضبط `API_AUTH_KEY` إلى دعم POST / upload، بينما تبقى origins المتقاطعة غير المطابقة محظورة ([#304](https://github.com/HKUDS/Vibe-Trading/pull/304)، شكراً @Hinotoi-agent).
- **2026-06-23** 🛡️ **تحصين CSRF لواجهة API المحلية**: لم يعد بإمكان صفحة ويب خبيثة إرسال طلبات cross-site غير آمنة (POST/PUT/DELETE) إلى واجهة loopback — فـ CORS يمنع قراءة الاستجابة لكنه لا يمنع الأثر الجانبي، لذا أصبحت ثقة dev-mode الخاصة بـ loopback تطبّق حارس cross-site الحالي على الطرق غير الآمنة **قبل** منحها الثقة. الطرق الآمنة ورفع الملفات عبر CLI المحلي / غير المتصفح غير متأثرة ([#293](https://github.com/HKUDS/Vibe-Trading/pull/293)، شكراً @Hinotoi-agent).
- **2026-06-22** 🔧 **إصلاح OAuth لتفويض التداول الحي + إصلاح عنوان Alpha Zoo**: يُبقي `connector authorize` الآن مصافحة OAuth مفتوحة طوال تسجيل دخول الوسيط الذي قد يستغرق دقائق (قابل للضبط عبر `VIBE_LIVE_AUTHORIZE_TIMEOUT_SECONDS`)، ولم يَعُد يُشغِّل خادم callback منافسًا عند إعادة المحاولة، فأصبح الرمز يُحفَظ فعلاً ([#281](https://github.com/HKUDS/Vibe-Trading/pull/281)، يغلق [#259](https://github.com/HKUDS/Vibe-Trading/issues/259)، شكراً @Robin1987China). ولم تَعُد صفحة Alpha Zoo تعرض عدد الـ alpha مرتين ([#287](https://github.com/HKUDS/Vibe-Trading/pull/287)، يغلق [#286](https://github.com/HKUDS/Vibe-Trading/issues/286)، شكراً @digger-yu). كما حصلت الأبحاث المجدولة على وثائق استخدام شاملة ([#288](https://github.com/HKUDS/Vibe-Trading/pull/288)).
- **2026-06-21** ⏰ **مُنفِّذ الأبحاث المجدولة + مكتبة التقارير + إسناد ما بعد الاختبار الخلفي**: تعمل الأبحاث المجدولة الآن **من طرف إلى طرف** — مُنفِّذ خلفي مُعطَّل افتراضيًا (`VIBE_TRADING_ENABLE_SCHEDULER`) يُشغِّل المهام المستحقة وفق interval/cron عبر بيئة تشغيل الجلسة ([#278](https://github.com/HKUDS/Vibe-Trading/pull/278)، شكراً @mvanhorn، يغلق [#254](https://github.com/HKUDS/Vibe-Trading/issues/254)). وتَسرُد صفحة **مكتبة التشغيل `/reports`** الجديدة عمليات التشغيل ذات التقارير وتبحث فيها وتُرشِّحها، مع روابط إلى Run Detail + Compare ([#224](https://github.com/HKUDS/Vibe-Trading/pull/224)، شكراً @LemonCANDY42). وبعد كل اختبار خلفي يُجري الوكيل الآن **إسنادًا متعدّد الطبقات** — الرابحون/الخاسرون على مستوى الصفقة، وانحدار بيتا، وتحليل أنظمة السوق (regime)، واختبار مونت كارلو للتباديل — مشروطًا بتوفّر البيانات والتوجيه ([#280](https://github.com/HKUDS/Vibe-Trading/pull/280)، شكراً @shadowinlife).
- **2026-06-20** 🔬 **اكتمال حلقة Research Autopilot (المرحلة 3) + حارس سلامة OHLC على حدود المُحمِّل + 4 عوامل ألفا أكاديمية**: أصبح **Research Autopilot** ينفّذ **الفرضية → محرّك الإشارة → الاختبار الخلفي** من طرف إلى طرف — حيث يكتب `scaffold_signal_engine` محرّكًا مطابقًا لعقد runner، ويعيد `link_autopilot_backtest` مقاييس التشغيل تلقائيًا إلى الفرضية (**68 أداة**) ([#267](https://github.com/HKUDS/Vibe-Trading/pull/267)). ويُسقط **فحص سلامة OHLC** البنيوي الأشرطة المعيبة (`high < low`، الأسعار غير الموجبة، وعدم إحاطة high/low بـ open/close) مركزيًا عند حدود المُحمِّل، بما يحمي كل مصادر البيانات ([#274](https://github.com/HKUDS/Vibe-Trading/pull/274)، شكراً @Shizoqua). كما تتوسّع **عائلة عوامل ألفا الأكاديمية من 6 إلى 10** — انعكاس Jegadeesh، وقمة 52 أسبوعًا لـ George-Hwang، وانعدام سيولة Amihud، والتواء Harvey-Siddique (**456 عاملًا**) ([#277](https://github.com/HKUDS/Vibe-Trading/pull/277)، شكراً @Robin1987China).
- **2026-06-19** 🚀 **v0.1.10 — طبقة بيانات عالمية**: تنمو مصادر بيانات السوق من 10 إلى 18 (مجانية **Eastmoney / Sina / Stooq / Yahoo** + محكومة بمفتاح **Finnhub / Alpha Vantage / Tiingo / FMP**، مع fallback مرتّب حسب خطر حظر الـ IP)، إضافةً إلى **18 أداة بيانات للقراءة فقط** (تدفق الأموال، لوحة التنين والنمر، التدفق الشمالي، التداول بالهامش، الصفقات الكتلية، SEC EDGAR + XBRL، القوائم المالية، سلاسل الخيارات، فرز كامل السوق…) عبر الأسهم الصينية / الأمريكية / هونغ كونغ، وكلّها مكشوفة عبر MCP. تتضمّن هذه الإصدارة أيضًا كل تحديثات ما بعد 0.1.9 —— 10 موصّلات وسطاء، و`alpha compare`، وإصلاح موثوقية المزوّدين، وذاكرة تخزين بيانات اختيارية. `pip install -U vibe-trading-ai`
- **2026-06-18** 🔬 **المرحلة الأولى من Research Autopilot + محمّل Data Bridge محلي، إضافةً إلى تنبيه أمني بشأن Discord**: تربط أداتا `run_research_autopilot` و`generate_backtest_config` الجديدتان مسار **Hypothesis → Research Goal → backtest** من طرف إلى طرف (الآن **50 أداة**)، ويقرأ محمّل **`local`** الجديد بيانات OHLCV مباشرةً من ملفاتك **CSV / Parquet / DuckDB** ([#260](https://github.com/HKUDS/Vibe-Trading/pull/260)، [#252](https://github.com/HKUDS/Vibe-Trading/pull/252)، شكراً @Robin1987China)، إضافةً إلى تحليل استدعاءات أدوات DeepSeek `DSML` ودفعة لتقوية احتواء المعرّفات. ⚠️ **تنبيه أمني**: دعوة المجتمع القديمة على Discord تشير الآن إلى خادم لا نتحكم به (تصيّد بانتحال "تحقّق" محفظة Collab.Land) — أُزيلت بالكامل، وخادم HKUDS ([discord.gg/6TdQnT5xcF](https://discord.gg/6TdQnT5xcF)) هو Discord الرسمي **الوحيد**. لن نطلب منك أبداً ربط محفظة.
- **2026-06-17** 🧩 **توافق التثبيت + إصلاحات مزوّدي Opus/Kimi**: لم يعد التثبيت الأساسي `pip install vibe-trading-ai` يجلب سلسلة الاعتماد الاختيارية `pyharmonics` / `ta`؛ أصبح كشف الأنماط التوافقية خلف extra باسم `vibe-trading-ai[harmonic]` مع بقاء detector المضمّن متاحاً ([#250](https://github.com/HKUDS/Vibe-Trading/pull/250)، يغلق [#249](https://github.com/HKUDS/Vibe-Trading/issues/249)). ولم يعد Agent loop يرسل رسائل assistant-prefill handoff التي يرفضها Opus 4.8+، كما يمكن لـ Kimi/Moonshot تجاوز `User-Agent` عبر `MOONSHOT_USER_AGENT` ([#248](https://github.com/HKUDS/Vibe-Trading/pull/248)، يغلق [#246](https://github.com/HKUDS/Vibe-Trading/issues/246) و[#204](https://github.com/HKUDS/Vibe-Trading/issues/204))؛ وتغطي اختبارات المتابعة مساري background-result وauto-compact handoff مباشرة ([#251](https://github.com/HKUDS/Vibe-Trading/pull/251)).
- **2026-06-16** 🛡️ **تعزيز الأمان/API + alias لـ GLM/Zhipu**: تتطلب كتابات Settings المصادقة عند تفعيلها ([#245](https://github.com/HKUDS/Vibe-Trading/pull/245))؛ وتتطلب أدوات shell-capable في جلسات API تفعيلًا صريحًا عبر `VIBE_TRADING_ENABLE_SHELL_TOOLS=1` ([#243](https://github.com/HKUDS/Vibe-Trading/pull/243))؛ ويتطلب local shutdown المصادقة عند ضبط API key ([#241](https://github.com/HKUDS/Vibe-Trading/pull/241))؛ وتُرفض Host التي تبدو كـ loopback لكنها غير موثوقة بدل معاملتها كمحلية ([#242](https://github.com/HKUDS/Vibe-Trading/pull/242)). كما صُقلت تفاصيل التشغيل: يتزامن Web chat مع المحاولات المكتملة ([#236](https://github.com/HKUDS/Vibe-Trading/pull/236))، وتُصدر run cards صيغة strict JSON للمقاييس غير المنتهية ([#238](https://github.com/HKUDS/Vibe-Trading/pull/238))، وتتراجع قيم `RSSHUB_TIMEOUT_S` / `RSSHUB_FETCH_BUDGET_S` المشوهة بأمان ([#240](https://github.com/HKUDS/Vibe-Trading/pull/240))، وثُبّت fallback إعادة المحاولة في ddgs باختبار انحدار ([#239](https://github.com/HKUDS/Vibe-Trading/pull/239)). وأصبح GLM/Zhipu alias من الدرجة الأولى مع استنتاج اسم النموذج ([#247](https://github.com/HKUDS/Vibe-Trading/pull/247)، يغلق [#237](https://github.com/HKUDS/Vibe-Trading/issues/237)).

- **2026-06-15** 🧭 **متانة بحث الويب + إصلاحات استمرارية التشغيل في واجهة الويب**: لم يعد `web_search` يفشل عند تقييد مزوّد بحث واحد——إذ يستعلم الآن عدة محركات مجانية بلا مفاتيح بالترتيب (DuckDuckGo، Google، Bing، Brave، Mojeek، Yahoo) مع إعادة محاولة/تراجع، ويعامل "لا نتائج" كإجابة فارغة لا كخطأ، ويعيد رسالة قابلة للتنفيذ بدل ❌ مجرّدة عندما تُقيَّد كل المحركات (يمكن تجاوز قائمة المحركات عبر `VIBE_TRADING_SEARCH_BACKENDS`) ([#232](https://github.com/HKUDS/Vibe-Trading/pull/232)، يغلق [#231](https://github.com/HKUDS/Vibe-Trading/issues/231)، شكراً @Ethan-sun01). وفي واجهة الويب، لم يعد تبديل الصفحات أثناء التشغيل يُجمِّده——إذ تعيد المحادثة الاشتراك في البث الحي وتعيد تشغيل التقدّم الفائت عند العودة ([#234](https://github.com/HKUDS/Vibe-Trading/pull/234))——وأصبح زر الإيقاف يسري أثناء البث وبين الأدوات لا عند حدود التكرار فقط ([#235](https://github.com/HKUDS/Vibe-Trading/pull/235))، ما يغلق شِقَّي [#229](https://github.com/HKUDS/Vibe-Trading/issues/229) (شكراً @kalkinj). كما أصبح محمّل baostock يقبل الرموز الأصلية `sh.601398` / `sz.000001` إلى جانب صيغة tushare `601398.SH` ([#230](https://github.com/HKUDS/Vibe-Trading/pull/230)، شكراً @bhlt).

- **2026-06-14** 📊 **استهلاك التوكنات لكل تشغيل + تحميل رسوم Run Detail عند الطلب**: أصبح كل تشغيل agent يحفظ استهلاك التوكنات المُبلَّغ من المزوّد كملف `llm_usage.json` على مستوى التشغيل——المزوّد/النموذج، والإجماليات التراكمية، والعدّ لكل تكرار——ويُعرَض إضافيًا على `/runs/{id}`، بحيث تبقى تكلفة التوكنات قابلة للتدقيق بعد انتهاء التشغيل واختفاء البث الحي (قيم المزوّد فقط؛ بلا التقاط prompt/محتوى ولا تقدير سعر) ([#223](https://github.com/HKUDS/Vibe-Trading/pull/223)، شكراً @LemonCANDY42). كما لم تعد صفحة Run Detail تُحمّل شموع كل الرموز مقدمًا: تبقى استجابة `/runs/{id}` الافتراضية دون تغيير، لكن الواجهة الآن تعرض ملخّص التشغيل أولًا ثم تُحمّل رسم كل رمز عند الطلب عبر وضعَي `?chart_payload=summary` / `?chart_symbol=` الاختياريين، مع حالة تحميل لكل رمز وزر "تحميل الكل مع شريط تقدّم" ([#225](https://github.com/HKUDS/Vibe-Trading/pull/225)، شكراً @LemonCANDY42). ويُختتم ذلك بإصلاحين في الـ loader: لم تعد حدود `end` الحصرية في yfinance تُسقِط آخر يوم تداول في النطاق المطلوب——إذ يمرّر الاستدعاء الآن `end + يوم واحد` بينما تحتفظ مفاتيح الكاش بالنطاق الأصلي ([#226](https://github.com/HKUDS/Vibe-Trading/pull/226)، شكراً @gyx09212214-prog)——وأصبحت القيمة المُشوَّهة لـ `CCXT_TIMEOUT_MS` / `OKX_TIMEOUT_S` تُصدر تحذيرًا وتعود إلى قيمتها الافتراضية بدل أن ترفع استثناءً عند الـ import وتعطّل الإقلاع ([#227](https://github.com/HKUDS/Vibe-Trading/pull/227)، شكراً @gyx09212214-prog).
- **2026-06-13** ↩️ **استئناف جلسة سابقة بالمعرّف من سطر الأوامر**: أصبحت واجهة CLI التفاعلية تطبع session-id عند الخروج، مع تلميح قابل للنسخ `vibe-trading resume <session-id>`——فلم يعد العثور على trace لتشغيل منتهٍ يتطلّب تخمين أي مجلد تحت `agent/sessions/` هو الأحدث زمنياً. الأمر الفرعي الجديد `vibe-trading resume <session-id>` يعيد فتح تلك الجلسة بالذات ويعيد تشغيل أحدث أدوارها في الـ loop؛ والمعرّف غير الموجود يفشل فوراً بدل بدء جلسة فارغة بصمت ([#218](https://github.com/HKUDS/Vibe-Trading/pull/218)، شكراً @zwrong).
- **2026-06-12** 🩺 **إصلاح شامل لموثوقية المزوّدين——تعليق DeepSeek، الوصول إلى Kimi، حيوية البث**: مجموعة من البلاغات——تشغيلات DeepSeek عالقة عند "Agent is working…" ([#208](https://github.com/HKUDS/Vibe-Trading/issues/208)، شكرًا @XYWOX)، رسالة `reached max iterations` تخفي استجابات نموذج فارغة ([#203](https://github.com/HKUDS/Vibe-Trading/issues/203)، شكرًا @mojianliang)، واجهة لا تتعافى بعد التوقف ([#195](https://github.com/HKUDS/Vibe-Trading/issues/195)، شكرًا @mafia23)، وKimi يرفض العميل ([#204](https://github.com/HKUDS/Vibe-Trading/issues/204)، شكرًا @liao497)——تشترك في جذر واحد: كل مزوّد متوافق مع OpenAI كان يمر عبر طبقة واحدة تطبّق خصوصيات DeepSeek/Kimi/Gemini عالميًا وتبتلع أخطاء البث بصمت. أصبح السلوك الخاص بكل مزوّد الآن في **طبقة قدرات** صريحة——التقاط/إعادة إرسال reasoning، وتوقيعات Gemini الفكرية، و`User-Agent` الخاص بـ Kimi، وجسم reasoning في OpenRouter، كلٌّ مقيّد بمزوّده ولا يلوّث غيره. تُظهر تدفقات reasoning مؤشر **"Reasoning…"** حيًّا بدل الصمت؛ ويرفع فشلُ البث خطأ `provider_stream_error` سياقيًا مع إعادة محاولة واحدة للانقطاعات العابرة (أخطاء 4xx الحتمية تفشل فورًا) بدل التراجع الصامت إلى استدعاء غير متدفق بطيء؛ وتُشخَّص الاستجابة الفارغة كـ `empty_model_response` بدل "max iterations"؛ ولم تعد نبضات SSE تكسر إعادة التشغيل عند إعادة الاتصال؛ وتنتهي مهلة الأداة القارئة العالقة بدل الاختباء خلف النبضات للأبد. الأمر الجديد **`vibe-trading provider doctor`** يطبع لقطة مموَّهة للمزوّد/النموذج/الحزم/الوكيل لتشخيص التعليق البيئي بأمر واحد. يمكن لمستخدمي DeepSeek تفعيل المحوّل الأصلي الرسمي عبر `pip install "vibe-trading-ai[deepseek]"`، ويُطبَّق متطلب `temperature=1` لنماذج kimi-k2.x تلقائيًا——مسار Kimi مُتحقَّق منه نهايةً إلى نهاية مقابل الـ API الحقيقي (استدعاء أدوات + إعادة إرسال reasoning متعدد الأدوار الصارم على `kimi-k2.6`).

- **2026-06-11** 🐝 **أصبح عمّال swarm يجلبون بيانات السوق عبر طبقة الـ loader**: كشف تشغيل للجنة الاستثمار على NVDA سلسلة من الثغرات——كان العمّال يكتبون سكربتات yfinance مرتجلة، ويثقون بشمعة أخيرة معطوبة (حجم تداول موجود لكن OHLC فارغة)، وتسرّب `NaN` إلى JSON غير صارم، وأعاد prompt المتابعة الفاقد للسياق التوجيه إلى preset خاطئ ([#198](https://github.com/HKUDS/Vibe-Trading/issues/198)، شكراً @BillDin على التشخيص الممتاز والإصلاحين). أصبح لدى عمّال swarm الآن أداة `get_market_data` محلية مدعومة بنفس سجلّ الـ loaders المُطبَّع الذي يستخدمه MCP——JSON صارم، والأعداد غير المنتهية تُسلسَل كـ `null`——موصولة بـ**كل preset لبيانات السوق** (21 عاملاً عبر 13 preset) مع سياسة prompt توجّه أعمال OHLCV نحو الأداة أولاً ([#199](https://github.com/HKUDS/Vibe-Trading/pull/199))؛ ويقبل `run_swarm` معامل `preset_name` صريحاً ويرفض مقاطع المتابعة الغامضة بدلاً من السقوط بصمت إلى `equity_research_team` ([#200](https://github.com/HKUDS/Vibe-Trading/pull/200)). وصار التأريض أذكى أيضاً: رمز سهم أمريكي مجرّد مثل `NVDA` في prompt السرب يُرقّى إلى `NVDA.US` (بحماية كلمات استبعاد)، فيبدأ العمّال من أسعار مرجعية مُسبقة الجلب. وتنضم الأداة إلى سجلّ الـ agent الرئيسي أيضاً——**48 أداة** الآن. إضافة إلى ذلك: **بيانات Docker تبقى الآن بعد التحديثات**——الذاكرة الدائمة وفهرس بحث الجلسات والمهارات التي أنشأها المستخدم وحسابات الظل وإعدادات الوسيط كلها في وحدات تخزين مسماة، فلم يعد `docker compose up --build` يمسحها ([#197](https://github.com/HKUDS/Vibe-Trading/issues/197)، شكراً @FlyerJ).
- **2026-06-10** 🐳 **يصل Docker إلى Ollama على المضيف مباشرة دون إعداد**: داخل الحاوية يشير `localhost` إلى الحاوية نفسها، لذا كان `OLLAMA_BASE_URL=http://localhost:11434` الافتراضي يُفشِل الفحص المسبق للـ LLM في كل تركيبة Docker + Ollama. أصبح `docker-compose.yml` يشير افتراضياً إلى `http://host.docker.internal:11434` (يمكن التجاوز بتصدير `OLLAMA_BASE_URL`) ويضيف تحويل `host-gateway` في `extra_hosts` بحيث يعمل الملف نفسه على Linux كما على Docker Desktop ([#196](https://github.com/HKUDS/Vibe-Trading/pull/196)، شكراً @ShahNewazKhan).
- **2026-06-09** 🔑 **رسالة خطأ أوضح عند فتح واجهة الويب من جهاز آخر**: عند الوصول إلى المحادثة من عميل غير loopback (جهاز آخر، أو مضيف جهاز افتراضي، أو هاتف على شبكتك المحلية) دون ضبط `API_AUTH_KEY`، كانت كل النقاط الحساسة——إرسال رسالة، قائمة الجلسات، حالة live——تُعيد `403`، لكن المحادثة كانت تعرض فقط رسالة عامة «Failed to send message, please retry.». أصبح مسار الإرسال الآن يُظهر السبب الحقيقي——*«Remote API access requires an API key. Add it in Settings, or run the backend on localhost for local-only use.»*——كما يوضّح إعداد واجهة الويب في README الفرق بين localhost والشبكة المحلية والحلول الثلاثة (التصفّح عبر `localhost` على نفس الجهاز؛ ضبط `API_AUTH_KEY` وإدخاله مرة في Settings؛ أو `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` لبوابة مضيف Docker Desktop) ([#191](https://github.com/HKUDS/Vibe-Trading/issues/191)، شكراً @mafia23).
- **2026-06-08** 🔧 **إصلاح استدعاء الأدوات متعدد الأدوار في Gemini 3.x**: يكتمل بهذا إصلاح نماذج التفكير Gemini 3.x. غطّى تبادل 6/05 ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176)) السجلّ في الذاكرة فقط، لكن حلقة الـ agent الفعلية تعيد تشغيل السجل على هيئة dict بصيغة OpenAI حيث كانت LangChain تُسقِط `thought_signature` لكل استدعاء أداة قبل بناء الطلب——فظلّت استدعاءات الأدوات متعددة الأدوار تفشل بـ `missing thought_signature` (خطأ 400). أصبح يُعاد إرفاقه الآن عند نقطة الاختناق الوحيدة `_convert_input` التي يمر بها كل من `invoke` و`stream` (بما في ذلك الاستدعاءات المتوازية، حيث يُوقّع الأول فقط من بين N) ([#184](https://github.com/HKUDS/Vibe-Trading/pull/184)، شكراً @ngoanpv).
- **2026-06-07** 🐝 **حالة swarm حيّة في مسار المحادثة**: عندما يُطلق الـ agent سربًا متعدد الوكلاء (لجنة الاستثمار، مكتب الكَمّ، لجنة المخاطر، …)، تعرض المحادثة الآن **بطاقة حالة** مضمّنة تبث حالة كل worker——انتظار / تشغيل / اكتمال / فشل / محظور / إعادة محاولة——في الوقت الفعلي، بنفس وضوح كل وكيل الذي توفّره لوحة swarm المستقلة. تُجسّر أحداث وقت التشغيل إلى تدفّق SSE للجلسة دون تغيير واجهة `/swarm/runs` القائمة، وتُستعاد البطاقة المنتهية من نتيجة `run_swarm` النهائية عند إعادة الاتصال أو إعادة تشغيل السجل ([#188](https://github.com/HKUDS/Vibe-Trading/pull/188)، شكراً @BillDin). وصار توجيه الـ preset أدقّ: إذ يتقدّم الـ preset المُسمّى صراحةً (مثل `investment_committee`، بشرطة سفلية أو بدونها) على ترتيب الكلمات المفتاحية، ولم تعد الكلمة `IV` للمشتقات تُطابِق خطأً داخل كلمات عادية مثل «g**iv**en» ([#189](https://github.com/HKUDS/Vibe-Trading/pull/189)، شكراً @BillDin).
- **2026-06-06** ⚖️ **مقارنة Alpha — عبر CLI وWeb UI وREST وagent**: يقارن `alpha compare` الجديد قائمة مختارة يدويًا من عوامل Alpha Zoo بعضها ببعض على نفس universe والفترة، ثم يرتّبها حسب متوسط/انحراف IC وIR ونسبة IC>0 أو عدد العينات — مع إظهار فجوة كل عامل عن المتصدّر. وخلافًا لـ bench لكامل الـ zoo، فإنه يقيّم **العوامل التي تسمّيها فقط** (مرشّح المجموعة الجزئية الجديد `run_bench(only=…)`)، فمقارنة ثلاثة عوامل لم تعد تُشغّل كل الـ 191 في الـ zoo. نواة مشتركة واحدة تشغّل كل الواجهات: `vibe-trading alpha compare <id1> <id2> … --sort ir` (CLI)، و**عرض Compare** في واجهة Alpha Zoo على الويب (حدّد العوامل في الكتالوج → مقارنة بنقرة واحدة مع جدول ترتيب متدفّق)، و`POST /alpha/compare` + SSE (REST)، وأداة `alpha_compare` للـ agent للقراءة فقط (**47 أداة** الآن).
- **2026-06-05** 🇮🇳 **connectors لـ Dhan + Shoonya (الهند) — 10 وسطاء إجمالاً**: تضيف طبقة التداول التي تعتمد أولاً على connectors وسيطين هنديين هما **Dhan** و**Shoonya** (أسهم NSE/BSE + المشتقات F&O)، ليصبح الإجمالي عشرة وسطاء. كلاهما **paper + قراءة فقط** — كما هي حال Longbridge، لا تكشف واجهتاهما عن مميِّز زمن تشغيل بين paper وlive، لذا يرفض `place_order` / `cancel_order` أي إعداد غير paper من السطر الأول (القاعدة: أي وسيط بلا حارس بنيوي paper/live يُقيَّد إلى paper + قراءة فقط) ([#181](https://github.com/HKUDS/Vibe-Trading/pull/181)، يغلق [#174](https://github.com/HKUDS/Vibe-Trading/issues/174)). كما تُصلح هذه الدورة **نماذج التفكير Gemini 2.5 / 3.x**: صار `thoughtSignature` لكل استدعاء أداة يُعاد تمريره عبر المسار المتوافق مع OpenAI، فلم تعد استدعاءات الدوال متعددة الأدوار تفشل بـ `INVALID_ARGUMENT` ([#176](https://github.com/HKUDS/Vibe-Trading/pull/176)، يغلق [#170](https://github.com/HKUDS/Vibe-Trading/issues/170)، شكراً @mvanhorn و@jliu6789). وأُضيفت docstrings صينية إلى جميع عوامل **Alpha Zoo البالغة 452** ([#180](https://github.com/HKUDS/Vibe-Trading/pull/180)، شكراً @LeeCQiang)، وانضمت إلى CI **حزمة اختبارات للواجهة الأمامية (197 اختبار vitest)** إضافة إلى اختبارات أمان للواجهة الخلفية تغطي المصادقة / اجتياز المسارات / CORS ([#175](https://github.com/HKUDS/Vibe-Trading/pull/175)، شكراً @sambazhu).
- **2026-06-04** 🗃️ **تخزين مؤقت محلي اختياري لجميع مصادر البيانات السبعة**: مفتاح جديد `VIBE_TRADING_DATA_CACHE` يتيح لكل loader للاختبار الخلفي——tushare وokx وccxt وakshare وmootdx وyfinance وfutu——تخزين الأشرطة التاريخية المستقرة مؤقتاً ضمن `~/.vibe-trading/cache` (المجلد الرئيسي للمستخدم، ولا يُكتب أبداً داخل المستودع)، بحيث تتخطى عمليات الاختبار الخلفي المتكررة والطويلة المدى / عبر الأسواق الشبكة وتتجنب حدود معدّل المزوّد. معطّل افتراضياً. تتخطى محمّلات الدُّفعات والاتصال (yfinance، futu) التنزيل المجمّع / اتصال FutuOpenD بالكامل عند إصابة المخزن المؤقت كلياً، ولا يخزّن حارس القِدَم أبداً نطاقاً ينتهي اليوم (شريطه الأخير ما زال قيد التكوين)، وتعود الإطارات المخزّنة مطابِقة بايتاً ببايت لما يُجلب حديثاً ([#177](https://github.com/HKUDS/Vibe-Trading/pull/177)، شكراً @mvanhorn). كما وصل دليل مساهمين جديد للـ PRs المدعومة بالذكاء الاصطناعي / الأتمتة، يوضّح الفحوص المحلية الآمنة والأسطح عالية الخطورة لـ broker/MCP/بيانات الاعتماد ([#173](https://github.com/HKUDS/Vibe-Trading/pull/173)).
- **2026-06-03** 🧹 **فرز المجتمع + ربط التتبع**: تحمل الآن إدخالات تتبع استدعاء الأدوات `call_id` الأصلي، بحيث يمكن مطابقة `tool_result` مع `tool_call` المقابل عند إعادة تشغيل تتبع التشغيل — وتبقى معاينات الوسائط مقتطعة للحفاظ على صغر حجم ملفات التتبع ([#168](https://github.com/HKUDS/Vibe-Trading/pull/168)، شكراً @zwrong). لم تعد تعليقات الكود المصدري تشير إلى مسار وثائق داخلي لا يستطيع المساهمون الخارجيون العثور عليه ([#166](https://github.com/HKUDS/Vibe-Trading/issues/166)، شكراً @jaleelpersonal). كما تم توضيح أن تحذير محلّل تبعيات `langchain-community` أثناء التثبيت هو مجرد إشعار غير ضار عن حزمة متبقية وليس فشلاً ([#167](https://github.com/HKUDS/Vibe-Trading/issues/167))، وتم تنظيم معالجة ذهاب وإياب `thoughtSignature` لاستدعاءات الدوال في Gemini 2.5/3.0 كمهمة `help wanted` مع خطة إصلاح كاملة ([#170](https://github.com/HKUDS/Vibe-Trading/issues/170)، شكراً @jliu6789).
- **2026-06-02** 🔌 **ستة connectors وسطاء جديدة (Tiger / Longbridge / Alpaca / OKX / Binance / Futu)**: تكتسب طبقة التداول التي تعتمد أولاً على connectors ناقلاً مباشراً عبر SDK إلى جانب IBKR (محلي) وRobinhood (MCP). يكشف كل connector عن حساب / مراكز / أوامر / quote / تاريخ للقراءة فقط، بالإضافة إلى وضع أوامر على حساب PAPER — اختبر استراتيجياتك عبر حسابات paper الخاصة بهؤلاء الوسطاء. كما يدعم خمسة منها (Tiger وAlpaca وOKX وBinance وFutu) وضع أوامر محدوداً ومحكوماً بـ mandate خلف نفس نموذج السلامة المطبّق على Robinhood: mandate يلتزم به المستخدم (نطاق الرموز / حجم الأمر / التعرّض / الرافعة / الحد اليومي)، وkill switch على مستوى الملفات، وبوّابة استباقية قبل التداول تُغلَق عند الفشل، وسجل تدقيق كامل. أما Longbridge فهو للقراءة فقط + paper حصراً (لا تكشف واجهته عن مميِّز زمن تشغيل بين paper وlive). كل تمييز بين paper وlive هو حارس بنيوي خاص بكل وسيط. أدوات جديدة `trading_place_order` / `trading_cancel_order`؛ وأُضيفت فئتا الأصول HK وأسهم A إلى universe الخاص بـ mandate. تجريبي / الاستخدام على مسؤوليتك.
- **2026-06-01** 🚀 **إصدار v0.1.9** (`pip install -U vibe-trading-ai`): يجمع كل ما استُجد منذ 0.1.8. ملفات وسطاء تعتمد أولاً على connectors (IBKR محلي للقراءة فقط من TWS / IB Gateway + Robinhood Agentic Trading خلف OAuth وmandate مُلتزم وorder guard وسجل تدقيق وhalt فوري). زمن تشغيل Research Goal عبر CLI / REST / MCP / Web. تحديث swarm — reconcile حيّ + إبقاء MCP حياً، وأدوات MCP لعمّال swarm يضبطها المشغّل، وتحكم عشوائي صارم في alpha-bench، و`retry_run` جديد لإعادة تشغيل runs الفاشلة/القديمة (الآن **36 أداة MCP**). إعادة هيكلة حزمة `agent/cli/` مع واجهة طرفية محدّثة، ومحمّل `mootdx` لأسهم A بدون توكن، وجولة متانة عبر backtest / agent loop / sessions. أصبح `--version` يطابق دائماً الحزمة المثبّتة، مصلحاً انحراف 0.1.8 ([#156](https://github.com/HKUDS/Vibe-Trading/issues/156)).
- **2026-05-31** 🔌 **بنية وسطاء تعتمد أولاً على connectors (IBKR + Robinhood)**: يبدأ الوصول إلى التداول الآن من connector profile قابل للاختيار، لا من مداخل منفصلة للوسيط أو live. أوامر `vibe-trading connector list/use/check/account/positions/orders/quote/history` وأدوات MCP `trading_*` تشترك في نفس profile المحدد، حيث تكون paper/live مجرد خاصية ضمن connector. يمكن استخدام IBKR فوراً عبر profile محلي للقراءة فقط من TWS / IB Gateway، بينما يُزرع مسار MCP الرسمي البعيد لـ IBKR كتحقق OAuth بنطاق `mcp.read` إلى أن تتوفر أسماء أدوات قراءة مستقرة. يظل Robinhood Agentic Trading هو connector MCP حيّاً ومحدوداً خلف OAuth وmandate مُلتزم وorder guard وسجل تدقيق وhalt فوري.
- **2026-05-30** 🧰 **جولة متانة — backtest وagent loop وsession**: تمرّ الآن signal engines المولّدة بواسطة LLM بتحقق مسبق من الواجهة قبل الإنشاء، فتلتقط مبكراً الأخطاء الشائعة مثل self-import الدائري، وغياب `generate()`، ووسائط `__init__` بلا قيم افتراضية، ونوع الإرجاع الخاطئ، وتُرجِع أخطاء JSON قابلة للتنفيذ بدل traceback خام ([#149](https://github.com/HKUDS/Vibe-Trading/pull/149))؛ ومتابعةٌ لاحقة توجّه أخطاء تحقق AST على مستوى المصدر عبر نفس مغلّف JSON النظيف. لم يعد agent loop يستنزف الخمسين تكراراً ليصل إلى حالة `failed` بلا أي مخرجات — فهو يحاكي أسلوب swarm worker المُجرَّب: يحقن wrap-up nudge عند 80% من ميزانية التكرار ويُسقط تعريفات الأدوات في التكرار الأخير لفرض إجابة نصية ([#148](https://github.com/HKUDS/Vibe-Trading/pull/148))، مع حارس يجعله يُطلَق في المنتصف فقط كي لا يزيح سياق research-goal. كتابة رسائل الجلسة تجري الآن `flush + fsync` بعد كل append حتى تنجو ردود الـ AI الباهظة من تعطّل أثناء الكتابة، ويتخطّى مسار القراءة أسطر JSONL التالفة (مع تسجيل أول 200 حرف للاسترداد) بدل إعطاء 500 لنقطة `/messages` كاملة ([#147](https://github.com/HKUDS/Vibe-Trading/pull/147)). كما أصلح محرّر الإدخال في الويب معالجة Enter مع IME بحيث لا يؤدي Enter لتأكيد التركيب إلى إرسال في منتصف الكلمة ([#146](https://github.com/HKUDS/Vibe-Trading/pull/146)).
- **2026-05-29** 🔐 **دعم Robinhood Agentic Trading (اختياري، استقلالية محدودة)**: أُضيف دعم Robinhood Agentic Trading (MCP عن بُعد، OAuth). مُعطَّل وللقراءة فقط افتراضياً؛ ويتداول الوكيل تلقائياً فقط ضمن mandate يلتزم به المستخدم (الرموز / حجم الأمر / التعرّض / الرافعة / الحد اليومي)، مع kill switch فوري على مستوى الملفات، وتصفية استباقية للمراكز، وانتهاء صلاحية تلقائي لـ mandate، وسجل تدقيق كامل، و runner مستقل دائم. لا حفظ للأموال ولا تشغيل لمنصة تداول — الوسيط يحتفظ بالأموال وينفّذ، ونحن ننقل النية فقط. تجريبي / الاستخدام على مسؤوليتك.
- **2026-05-28** 🧪 **سلامة Swarm + بوّابة alpha صارمة + MCP لعمّال swarm**: يحجب Swarm DAG الآن المهام المتفرعة عندما تفشل المهمة الأعلى ([#145](https://github.com/HKUDS/Vibe-Trading/pull/145)). دالة `run_bench_strict()` الجديدة تضيف فوق بوّابة IC تحكماً عشوائياً بنفس universe + قسمة train/test OOS لاصطياد العوامل التي تتبع beta السوق فقط ([#143](https://github.com/HKUDS/Vibe-Trading/pull/143)، شكراً @Soli22de). يستطيع عمّال Swarm الآن استدعاء أدوات من خوادم MCP خارجية يضبطها المشغل، مع تثبيت حدود الثقة باختبارات مخصصة ([#142](https://github.com/HKUDS/Vibe-Trading/pull/142)، شكراً @shadowinlife).
- **2026-05-27** 📊 **مصدر بيانات A-share عبر mootdx + تحسين الإخراج**: محمّل `mootdx` الجديد يتحدث بروتوكول 通达信 TCP الأصلي لبيانات OHLCV لأسهم A (بدون مصادقة، بدون قيود معدل لكل IP، يومي + intraday مع pagination تراجع بـ 25 صفحة)، ويُدرج بين tushare وakshare في سلسلة fallback ([#107](https://github.com/HKUDS/Vibe-Trading/issues/107)). محمّل CCXT يقرأ الآن `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` ليعمل جلب بيانات Binance/OKX العامة من الشبكات المقيدة ([#126](https://github.com/HKUDS/Vibe-Trading/pull/126)، شكراً @ruok808). عرض الإجابة النهائية أزال أيضاً فواصل `---` الأفقية القبيحة بعرض كامل على CLI وWeb: يحث system prompt الآن agent على استخدام جداول markdown وعناوين `##`، يجرّد CLI renderer أسطر HR المستقلة كدفاع متعمق، ويخفي chat bubble أي `<hr>` ينفذ عبر ([#139](https://github.com/HKUDS/Vibe-Trading/issues/139)، شكراً @sdwxm188).
- **2026-05-26** ✅ **إغلاق دورة حياة Research Goal**: أصبح Goal mode يعمل كمنفّذ مهام حقيقي: إنشاء goal من Web UI ينشئ الجلسة أو يربطها ويرسل kickoff turn فوراً؛ يمكن متابعة active goals وتعديلها وإلغاؤها وإكمالها عبر Web/API/CLI/MCP؛ ويتقدم agent loop من لقطة goal الحالية (criteria وevidence وclaims وopen items) بدلاً من الاعتماد على prompt الأصلي فقط. عندما تكون criteria covered لكن goal لا يزال active، ينتقل النظام إلى audit/status update بدلاً من التوقف الصامت، مع تغطية انحدارية عبر backend وCLI وMCP وfrontend events.

- **2026-05-25** 🧼 **واجهة Chat أنظف + سير composer**: أصبحت واجهة Web UI تترك التركيز للمدخل التالي: انتقلت أوضاع upload وswarm وresearch-goal إلى قائمة `+` في composer بدلاً من لوحات عائمة تقاطع المحادثة. يظهر السياق النشط فوق حقل الإدخال كشرائح compact، ولا تتوسع تفاصيل goal إلا inline عند النقر على الشريحة. أزيلت طبقة i18n المخصصة القديمة لصالح نصوص إنجليزية مباشرة، وتظهر بطاقة Full Report فقط للتشغيلات ذات تقرير فعلي، كما أصبح تشغيل التطوير المحلي وتقارير الحالة أكثر ثباتاً لاختبارات browser smoke.
- **2026-05-24** 🎯 **Research Goal runtime**: أضيفت طبقة Research Goal مرتبطة بالجلسة عبر backend وCLI وAPI/MCP وSSE وWeb UI. تحفظ الأهداف claims وacceptance criteria وevidence rows وbudgets وcompletion policy؛ تستطيع agent tools إنشاء الأهداف وإضافة evidence؛ أصبح `/goal` مدخل CLI؛ تعرض REST/MCP لقطات goal وكتابات evidence؛ وتحافظ SSE على حداثة حالة chat clients. أغلقت إصلاحات audit اللاحقة مسارات verified evidence، ومنعت live-trading risk tiers عبر agent tools، وربطت goals المنشأة من CLI بالمنعطفات اللاحقة، ونظفت goal ledger عند حذف الجلسة، ووصلت replay-all، وأصلحت race في frontend snapshot بين الجلسات.
- **2026-05-23** 🖥️ **تحديث CLI التفاعلي**: تفتح واجهة الطرفية الآن ببانر Vibe-Trading أكبر، وفاصل prompt أوضح، وملخص للدورة السابقة، وتوقيت بعد التشغيل، ومسار نشاط بأسلوب Claude Code لعمل الوكيل الحي. تُعرض استدعاءات الأدوات، وجلب الويب/البيانات، وأفعال نمط shell، وإجابات Markdown، وجداول pipe كسجل أكثر قابلية للقراءة، بينما تحافظ تشغيلات pipe أو non-TTY على إخراج نصي مناسب للأتمتة. أصبحت لقطات CLI المولدة artifacts محلية بدلاً من ملفات docs ملتزم بها، مما يبقي المستودع أخف.
- **2026-05-22** 🧭 **استعادة Swarm + إبقاء MCP حياً**: أصبحت حالة Swarm تُصالح من ملفات المهام الحية عند كل قراءة، لذلك تستعيد عروض API/MCP/SSE/list التشغيلات التي تعطلت أو صارت stale بدلاً من عرض لقطة `running` للأبد. يرسل `run_swarm` نبضات MCP progress أثناء polling، مع إطار أول ثابت `swarm_started run_id=<id>` كي يستطيع العملاء استعادة المقبض بعد سقوط النقل؛ كما يصدر worker نبضات خلال LLM streaming وgrounding fetch وتنفيذ الأدوات. يستخدم stale-run reaper عتبات خاصة بكل run ويستنتج الحالة النهائية من حالات المهام. لم يعد `SwarmTool` يلغي team ما زال يعمل لمجرد انتهاء wait budget، ويمكن لعملاء MCP استدعاء `reap_stale_runs()` للتنظيف الصريح. حدّثت دفعة DX اليوم أيضاً النماذج الافتراضية للمزودين، وواءمت فحص CI syntax مع حزمة `agent/cli/` الجديدة. تغطي 22 اختباراً انحدارياً جديداً hydration، واستعادة الحالات النهائية، وجمع التشغيلات stale، وإيقاع keepalive، وتحمل env parsing، وربط heartbeat؛ ومجموعة swarm/MCP الكاملة عند 169 passed و4 skipped.
- **2026-05-21** 🧱 **إعادة هيكلة حزمة CLI**: تقسيم `agent/cli.py` (3216 سطراً) إلى حزمة `agent/cli/` — واجهة تفاعلية، موجّه slash، مكوّنات Rich، وطبقة `_legacy.py` تحافظ على كل الأوامر الفرعية وتعيد تصدير كل الرموز العامة فتبقى `cli.cmd_*` / `cli._INIT_ENV_PATH` / `cli.Confirm` كما هي. Middleware جديد في FastAPI يخدم قشرة SPA عند فتح `/runs/{id}` أو `/correlation` مباشرة من المتصفح، مع نفس التضييق في بروكسي Vite للتطوير. توحيد سلسلة الإصدار عبر `cli/_version.py` (إنهاء الانحراف بين `--version` والبانر)، استعادة `python -m cli` عبر `__main__.py`، وتضييق بوابة chat بحيث تصل `chat --help` / `chat extra` إلى argparse القديم بدلاً من ابتلاع REPL لها.
- **2026-05-20** 🔬 **Hypothesis Registry CLI**: استكمال جانب CLI لـ Hypothesis Registry الذي شُحن backend فقط في 2026-05-16. يُخرج `vibe-trading hypothesis list` جدول Rich أو JSON (مع فلتر `--status` و`--limit`)؛ يعرض `show <id>` لوحة تفاصيل تتضمن run cards المرتبطة؛ يقلب `invalidate <id> --note "..."` الحالة إلى `rejected` ويُبقي ملاحظات الإبطال السابقة عند حذف `--note`. متغير البيئة `VIBE_TRADING_HYPOTHESES_PATH` ما زال مدعوماً، مع إضافة `--path` لكل استدعاء. تغطي 22 اختباراً جديداً الربط، إخراج JSON، فلتر الحالة، الحد، أخطاء معرّف مفقود، وثبات الملاحظات.
- **2026-05-19** ✨ **تغذية راجعة حيّة للأدوات + إلغاء سلس**: لم تعد الأدوات الطويلة (backtests، PDF كبيرة، عمّال swarm) تبدو متجمدة. كل استدعاء أداة يُصدر الآن نبضة قلب كل 3 ثوانٍ، بالإضافة إلى تقدّم مرحلي مهيكل — يُظهر `run_backtest` علامات الأطوار (`validate` / `simulate` / `finalize`)، ويُحدّث `read_document` عدّاد كل صفحة على PDF أو كل ورقة على Excel، ويُعلِم `read_url` بمرحلتي `fetch` / `parse`. تعرض لوحة Rich Live في CLI دوّاراً Unicode وشريط تقدّم ASCII وETA، وتُكدّس حتى 3 أدوات متوازية مفهرسة بالاسم. تضيف الواجهة الأمامية مكوّن `ToolProgressIndicator` جديد مع تجميع rAF، وARIA `role="status"` + `<progress>` أصلي مخفي لقارئات الشاشة، وSVG `ProgressRing` حتمي عندما يكون المجموع معروفاً. أول `Ctrl+C` أثناء تشغيل CLI يستدعي الآن `agent.cancel()` للخروج السلس (تكتمل الخطوة الحالية وتُغلق التتبعات بنظافة)، والثاني خلال ثانيتين يفرض الإنهاء. تم استخراج عناصر أساسية قابلة لإعادة الاستخدام: `ProgressBar.tsx` و`lib/tools.ts` (تعيين i18n لأسماء الأدوات المشترك).
- **2026-05-18** 🧹 **تنظيف + إصلاح 3 أخطاء كامنة**: لم يعد `CompositeEngine` يوجّه رموز العقود الآجلة الصينية بدون لاحقة (مثل `RB2410`) إلى `GlobalFuturesEngine` بشكل خاطئ — انتقل `_is_china_futures` إلى وحدة `_market_hooks` المشتركة مع تطبيع حالة جدول المنتجات + حارس لبورصة غير صينية، وأُضيفت 9 حالات اختبار انحدار. تحفظ فهارس FTS5 للجلسات الآن الطوابع الزمنية، فيمكن لبحث الجلسات الفرز بالتاريخ، ونفس التغيير أصلح مسار إعادة الإدراج الذي كان يستبدل `started_at` بساعة الحائط في كل مرة. أُضيف `/alpha` المفقود إلى بروكسي تطوير Vite، فتُحلّ صفحة AlphaZoo الآن على `npm run dev`. تم تقييد `tests/test_e2e_harness_v2.py` (مجموعة e2e بـ LLM حقيقي) خلف `VIBE_TRADING_RUN_LIVE_E2E=1` كي لا تغيّر CI شكلها بناءً على وجود مفتاح البيئة. أُضيفت إلى ruff قاعدة `per-file-ignores` لمكتبة المعاملات (الضوضاء F401 من 3783 إلى 0)، وفُعِّلت `noUnusedLocals` / `noUnusedParameters` في tsconfig الواجهة كحواجز انحدار، وحُذف 76 سطراً من نموذج `vw = vwap(...)` غير المستخدم في ملفات `gtja191`. الصافي **-918 سطراً**.
- **2026-05-17** 🧬 **Alpha Zoo v1 (0.1.8)**: 452 ألفا كمّي جاهز عبر 4 zoos — `qlib158` (ميزات Alpha158 من Microsoft Qlib، إسناد Apache-2.0)، `alpha101` (إعادة تنفيذ "101 Formulaic Alphas" من Kakushadze بناءً على ورقة arXiv:1601.00991)، `gtja191` (تقرير بحث Guotai Junan 2014 لعوامل تداول قصيرة الأجل)، `academic` (Fama-French 5 + Carhart momentum كـ proxy قائم على الأسعار). سطر أوامر واحد للـ bench على أي universe: `vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025`. تتضمن بوابة AST للنقاء، اختبار حماية lookahead، عزل الشبكة عبر `pytest-socket`، LICENSE.md لكل zoo، وسير عمل توقيع DCO لمساهمات المجتمع. تقديم Alpha Library تلقائياً على [vibetrading.wiki/alpha-library/](https://vibetrading.wiki/alpha-library/)، مع منشور Research Lab [Which of the 191 GTJA alphas still work in 2026?](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).
- **2026-05-16** 🧪 **تحديث عمود البحث**: أضيف backend Hypothesis Registry مع `create_hypothesis` و`update_hypothesis` و`link_backtest` و`search_hypotheses`. تضيف قارئات المحتوى الخارجي الآن `security_warnings` تحذيرية فقط، وانتقل ماسح Shadow Account من calendar-phase stub القديم إلى تقييم حتمي لميزات OHLCV.
- **2026-05-15** 🪪 تعرض صفحة تفاصيل الـ run الآن بطاقة Trust Layer run card إلى جانب المقاييس والمخرجات، لتكمل الجانب الواجهي من عمل `run_card.json` الذي هبط في 2026-05-12. كما تم تعزيز `PersistentMemory.add()` على مسارات الطول والأسماء الفارغة أو التي تحتوي على فراغات فقط وبايتات التحكم C0/C1 ضمن فرز #108/#109/#110 ([#112](https://github.com/HKUDS/Vibe-Trading/pull/112)، شكراً @Teerapat-Vatpitak).
- **2026-05-14** 🌐 أصبح الويكي العام متاحاً على [vibetrading.wiki](https://vibetrading.wiki/) مع أقسام docs وtutorials وResearch Lab وAlpha Library، ويُنشر عبر Cloudflare Pages. أصبحت الذاكرة الدائمة أيضاً قابلة للفحص من سطر الأوامر عبر `vibe-trading memory list/show/search/forget` ([#102](https://github.com/HKUDS/Vibe-Trading/pull/102)، شكراً @Teerapat-Vatpitak)، كما يدعم توليد الرموز وslugs للذاكرة الآن التايلاندية والعربية والعبرية والنص السيريلي ([#104](https://github.com/HKUDS/Vibe-Trading/pull/104)).

- **2026-05-13** 🧭 أصبحت تشغيلات السرب تؤسس عمل الوكلاء على بيانات سوق مجلوبة مسبقاً، مع تقارير محفوظة أنظف ([#93](https://github.com/HKUDS/Vibe-Trading/pull/93)، [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).
- **2026-05-12** 🧾 أصبحت الاختبارات الرجعية تنتج `run_card.json` و`run_card.md` إلى جانب المخرجات لدعم تشغيلات بحثية قابلة لإعادة الإنتاج.
- **2026-05-11** 🧭 **Memory slugs، ومحاسبة السرب، وفحص CLI المسبق**: أصبحت الذاكرة الدائمة تحفظ أحرف CJK عند توليد slugs للملفات، مما يمنع اصطدامات أسماء صامتة لملاحظات الصينية/اليابانية/الكورية ([#95](https://github.com/HKUDS/Vibe-Trading/pull/95)، شكراً @voidborne-d). تفضل مجاميع تشغيل السرب الآن استخدام استهلاك الرموز المبلغ من المزود مع الإبقاء على التقدير الاحتياطي الحالي ([#94](https://github.com/HKUDS/Vibe-Trading/pull/94)، شكراً @Teerapat-Vatpitak)، كما حصلت واجهة تشغيل CLI على فحص بدء مبكر للمشكلات البيئية الشائعة ([#96](https://github.com/HKUDS/Vibe-Trading/pull/96)، شكراً @ykykj).
- **2026-05-10** 🧱 **حواجز انحدار وبيانات تشغيل وصفية**: أصبح استدعاء الذاكرة يتعامل مع الشرطات السفلية كحدود رموز، لذلك تطابق ذكريات `snake_case` مثل `mcp_wiring_test` استعلامات طبيعية مثل "mcp wiring" ([#87](https://github.com/HKUDS/Vibe-Trading/pull/87)، شكراً @hp083625). يملك خادم MCP الآن اختبار smoke عبر subprocess يغطي initialize → `tools/list` → `tools/call` لحماية مسار التعطل في أول استدعاء ([#86](https://github.com/HKUDS/Vibe-Trading/pull/86))، كما وصلت تحسينات منخفضة المخاطر لاختبارات مسارات Windows، ومعالجة استثناءات API best-effort، والتحقق من allowed-root في `run_dir` للاختبار الرجعي، وبيانات provider/model في SwarmRun ([#88](https://github.com/HKUDS/Vibe-Trading/pull/88)، [#90](https://github.com/HKUDS/Vibe-Trading/pull/90)، [#91](https://github.com/HKUDS/Vibe-Trading/pull/91)، [#92](https://github.com/HKUDS/Vibe-Trading/pull/92)، شكراً @Teerapat-Vatpitak).
- **2026-05-09** 🛡️ **تعزيز مسارات API واستقرار خادم MCP**: تتحقق مسارات run/session في API الآن من معرفات المسار قبل البحث، وترفض المعاملات المشوهة التي تحتوي على أسطر جديدة مع تثبيت السلوك في مجموعة اختبارات auth/security ([#80](https://github.com/HKUDS/Vibe-Trading/pull/80)، شكراً @SJoon99). يسخن خادم MCP سجل الأدوات على الخيط الرئيسي قبل خدمة `tools/call` لتجنب تعطل أول استدعاء في اكتشاف الأدوات الكسول ([#85](https://github.com/HKUDS/Vibe-Trading/pull/85)، شكراً @Teerapat-Vatpitak). كما يحترم Vite dev proxy المتغير `VITE_API_URL` لأهداف الخلفية غير الافتراضية ([#82](https://github.com/HKUDS/Vibe-Trading/pull/82)، شكراً @voidborne-d).
- **2026-05-08** 🧾 **حقول قوائم Tushare داخل المرشحات**: تستطيع اختبارات أسهم A اليومية الآن طلب حقول قوائم مالية آمنة زمنياً عبر `fundamental_fields`، بحيث يمكن لمحركات الإشارات الفرز على أعمدة مثل `income_total_revenue` و`income_n_income` و`balancesheet_total_hldr_eqy_exc_min_int` و`fina_indicator_roe` بعد تواريخ الإعلان/الإفصاح ([#76](https://github.com/HKUDS/Vibe-Trading/pull/76)، شكراً @mrbob-git). ويجعل التعزيز اللاحق طلب حقول القوائم الصريح يفشل سريعاً إذا تعذر تشغيل إثراء Tushare، بدلاً من الرجوع بصمت إلى أشرطة الأسعار الخام ([#77](https://github.com/HKUDS/Vibe-Trading/pull/77)).
- **2026-05-07** 📈 **أساسيات Tushare وفرز المجتمع**: أضيف عقد `TushareFundamentalProvider` بنمط point-in-time لتدفقات البحث الأساسي، مع تغطية انحدار لمسار متغير البيئة `TUSHARE_TOKEN` في المشروع ([#74](https://github.com/HKUDS/Vibe-Trading/pull/74)). كما أوضح فرز المجتمع أن Vibe-Trading يركز حالياً على لغة واجهة واحدة لتسريع التكرار، ويتجنب تبعيات بحث زائدة ما دام `web_search` المدعوم من DuckDuckGo مضمناً، ويتعامل مع النشر المستضاف غير الرسمي كمكان غير موثوق لمفاتيح API أو رموز مصادر البيانات.
- **2026-05-06** 🚀 **إصدار v0.1.7** ([Release notes](https://github.com/HKUDS/Vibe-Trading/releases/tag/v0.1.7)، `pip install -U vibe-trading-ai`): نُشر تعزيز حدود الأمان على PyPI وClawHub، ويغطي افتراضات أكثر أماناً للـ API/القراءة/الرفع/الملفات/URL/الكود المولد/أدوات shell/Docker مع إبقاء تدفقات CLI/Web UI المحلية سهلة. تشمل الدورة أيضاً Web UI Settings، وخريطة ارتباط حرارية، وOpenAI Codex OAuth، ومرشح A-share pre-ST، وتحسين CLI التفاعلي، وفحص swarm presets، وتحليل التوزيعات، وصقل سير التطوير، ورفع حدود أمان تبعيات بناء الواجهة. شكراً لمساهمي 0.1.7 وlemi9090 (S2W) على التحقق الأمني المنسق.
- **2026-05-05** 🛡️ **متابعة حدود الأمان**: استكمال تعزيز الأمان حول CORS origins الصريحة، ومؤشرات بيانات الاعتماد في Settings، وقراءة عناوين الويب، وتوليد كود Shadow Account، مع اختبارات انحدار لكل مسار. تبقى تدفقات CLI/Web UI على localhost كما هي؛ وعلى عمليات النشر البعيدة استخدام `API_AUTH_KEY` وorigins موثوقة صريحة.
- **2026-05-04** 🖥️ **تجربة CLI تفاعلية وتنظيف CI**: يعرض الوضع التفاعلي الآن شريط حالة سفلياً مباشراً يبين provider/model ومدة الجلسة وكمون آخر تشغيل وإحصاءات استدعاءات الأدوات، مع تصفح سجل الأوامر وتحرير المؤشر بمفاتيح الأسهم عبر `prompt_toolkit` ([#69](https://github.com/HKUDS/Vibe-Trading/pull/69)). يعود CLI إلى Rich prompts عند غياب `prompt_toolkit` أو TTY. كما وُئمت توقعات مسارات CI مع صندوق استيراد الملفات المعزز وحل `/tmp` عبر المنصات، فعاد main إلى الأخضر ([`bb67dc7`](https://github.com/HKUDS/Vibe-Trading/commit/bb67dc7cfcc11553c57d8962bee56381dca43758)).
- **2026-05-03** 🛡️ **تصحيح تعزيز الأمان**: يشدد مصادقة API الافتراضية للنشر غير المحلي، ويحمي قراءات run/session/swarm الحساسة، ويقيد حدود الرفع وقراءة الملفات المحلية، ويقيد أدوات shell بحسب نقطة الدخول، ويتحقق من تحميل الاستراتيجيات المولدة قبل الاستيراد، ويشغل صورة Docker كمستخدم غير root مع منفذ localhost فقط افتراضياً. تبقى تدفقات CLI وWeb UI المحلية سهلة؛ وعلى نشر API/Web البعيد ضبط `API_AUTH_KEY`.
- **2026-05-02** 🧭 **تحليل التوزيعات وخارطة طريق أوضح**: أضيفت مهارة `dividend-analysis` لأسهم الدخل، واستدامة التوزيعات، ونموها، وعائد المساهمين، وآليات ex-dividend، وفحص مصائد العائد، مع تثبيتها باختبارات انحدار للمهارات المضمنة. تركز خارطة الطريق العامة الآن على Research Autopilot وData Bridge وOptions Lab وPortfolio Studio وAlpha Zoo وResearch Delivery وTrust Layer ومشاركة Community.
- **2026-05-01** 🔥 **خريطة ارتباط حرارية وOpenAI Codex OAuth ومرشح A-share pre-ST**: لوحة/API ارتباط جديدة تحسب ارتباطات العوائد المتحركة وتعرض خريطة حرارية ECharts لتحليل المحافظ والرموز ([#64](https://github.com/HKUDS/Vibe-Trading/pull/64)). يدعم مزود OpenAI Codex الآن ChatGPT OAuth عبر `vibe-trading provider login openai-codex` مع بيانات Settings واختبارات انحدار للمحول ([#65](https://github.com/HKUDS/Vibe-Trading/pull/65)). أضيفت وعُززت مهارة `ashare-pre-st-filter` لفحص مخاطر ST/*ST في أسهم A، مع فلترة صلة عقوبات Sina حتى لا تضخم إشارات حسابات الأوراق المالية عدادات E2 ([#63](https://github.com/HKUDS/Vibe-Trading/pull/63)).
- **2026-04-30** ⚙️ **Web UI Settings وتعزيز validation CLI**: صفحة Settings جديدة لمزود/نموذج LLM، وbase URL، وreasoning effort، وبيانات اعتماد مصادر البيانات، مدعومة بواجهات settings API محلية/محمية وببيانات مزودين قابلة للتكوين ([#57](https://github.com/HKUDS/Vibe-Trading/pull/57)). كما تعزز `python -m backtest.validation <run_dir>` حتى تفشل المدخلات الناقصة أو الفارغة أو المشوهة أو غير الموجودة أو غير الدليل برسائل واضحة قبل بدء التحقق ([#60](https://github.com/HKUDS/Vibe-Trading/pull/60)).
- **2026-04-28** 🚀 **إصدار v0.1.6** (`pip install -U vibe-trading-ai`): إصلاح إرجاع `vibe-trading --swarm-presets` فارغاً بعد `pip install` / `uv tool install` ([#55](https://github.com/HKUDS/Vibe-Trading/issues/55))، حيث أصبحت ملفات preset YAML مضمنة داخل حزمة `src.swarm` ومثبتة بستة اختبارات انحدار. كما أصبح محمل AKShare يوجه ETFs مثل `510300.SH` والفوركس مثل `USDCNH` إلى النقاط الصحيحة مع fallback registry معزز. يجمع الإصدار كل ما بعد v0.1.5: لوحة مقارنة معيارية، بث `/upload` وحدود الحجم، محمل Futu (HK + A-share)، مهارة تصدير vnpy، تعزيز أمني، وتحميل واجهة كسول من 688KB إلى 262KB.
- **2026-04-27** 📊 **لوحة مقارنة معيارية وأمان الرفع**: مخرجات الاختبار الرجعي تتضمن الآن لوحة مقارنة معيارية (ticker / benchmark return / excess return / information ratio) مع حل عبر yfinance لـ SPY وCSI 300 وغيرها ([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). كما تبث `/upload` جسم الطلب في أجزاء 1 MB وتتوقف بعد `MAX_UPLOAD_SIZE`، مما يحد الذاكرة تحت العملاء الضخمين/المشوهين ([#53](https://github.com/HKUDS/Vibe-Trading/pull/53))، ومثبتة بأربعة اختبارات انحدار.
- **2026-04-22** 🛡️ **تعزيز وتكاملات جديدة**: فرض احتواء المسارات في `safe_path` وصندوق أدوات journal/shadow، وإرسال `.env.example` / الاختبارات / ملفات Docker في sdist عبر `MANIFEST.in`، وتصغير الحزمة الأولية للواجهة من 688KB إلى 262KB عبر التحميل الكسول على مستوى المسارات. إضافة محمل Futu لأسهم HK وA-share ([#47](https://github.com/HKUDS/Vibe-Trading/pull/47)) ومهارة تصدير vnpy CtaTemplate ([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)).
- **2026-04-21** 🛡️ **مساحة العمل والوثائق**: تطبيع `run_dir` النسبي إلى دليل التشغيل النشط ([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). أمثلة استخدام README ([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **Reasoning وSwarm**: الحفاظ على `reasoning_content` عبر جميع مسارات `ChatOpenAI`، لتعمل أفكار Kimi / DeepSeek / Qwen من البداية للنهاية ([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). بث Swarm وإيقاف Ctrl+C نظيف ([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: النشر إلى PyPI وClawHub. رفع حد `python-multipart` لسد CVE، وربط 5 أدوات MCP جديدة (`analyze_trade_journal` + 4 أدوات shadow-account)، وإصلاح سجل `pattern_recognition` → `pattern`، ومطابقة تبعيات Docker، ومزامنة بيان SKILL (22 أداة MCP / 71 مهارة).
- **2026-04-18** 👥 **Shadow Account**: استخرج قواعد استراتيجيتك من سجل وسيط → اختبر الظل عبر الأسواق → تقرير HTML/PDF من 8 أقسام يوضح ما تتركه على الطاولة (خرق القواعد، الخروج المبكر، الإشارات الفائتة، الصفقات المضادة). 4 أدوات جديدة، ومهارة واحدة، و32 أداة إجمالاً. أمثلة Trade Journal + Shadow Account موجودة الآن في شاشة ترحيب Web UI.
- **2026-04-17** 📊 **محلل سجل التداول وقارئ ملفات شامل**: ارفع صادرات الوسطاء (同花顺/东财/富途/generic CSV) → ملف تداول تلقائي (أيام الاحتفاظ، معدل الربح، نسبة PnL، التراجع) + 4 تشخيصات سلوكية (disposition effect، الإفراط في التداول، مطاردة الزخم، anchoring). أصبح `read_document` يوجه PDF وWord وExcel وPowerPoint والصور (OCR) و40+ صيغة نصية خلف استدعاء موحد.
- **2026-04-16** 🧠 **Agent Harness**: ذاكرة دائمة عبر الجلسات، بحث جلسات FTS5، مهارات ذاتية التطور (CRUD كامل)، ضغط سياق بخمس طبقات، وتجميع أدوات القراءة/الكتابة. 27 أداة، و107 اختبارات جديدة.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: مزود Z.ai ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35))، وإصلاح temperature في MiniMax وتحديث النموذج ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13 مزوداً.
- **2026-04-14** 🔧 **استقرار MCP**: إصلاح خطأ `Connection closed` في أداة الاختبار الرجعي على نقل stdio ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **اختبار رجعي مركب عبر الأسواق**: محرك `CompositeEngine` جديد يختبر محافظ مختلطة الأسواق (مثل أسهم A + crypto) بمجمع رأس مال مشترك وقواعد لكل سوق. كما أصلح fallback لمتغيرات قالب السرب ومهلة الواجهة.
- **2026-04-12** 🌍 **تصدير متعدد المنصات**: يصدر `/pine` الاستراتيجيات إلى TradingView (Pine Script v6)، وTDX (通达信/同花顺/东方财富)، وMetaTrader 5 (MQL5) بأمر واحد.
- **2026-04-11** 🛡️ **الموثوقية وتجربة المطور**: إعداد `.env` عبر `vibe-trading init` ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19))، وفحوصات مسبقة، وfallback لمصادر البيانات وقت التشغيل، ومحرك اختبار رجعي معزز. README متعدد اللغات ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: إصلاح Docker ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8))، وأداة MCP `web_search`، و12 مزود LLM، وتبعيات `akshare`/`ccxt`. النشر إلى PyPI وClawHub.
- **2026-04-09** 📊 **الموجة الثانية للاختبار الرجعي**: محركات ChinaFutures وGlobalFutures وForex وOptions v2. تحقق Monte Carlo وBootstrap CI وWalk-Forward.
- **2026-04-08** 🔧 **اختبار رجعي متعدد الأسواق** مع قواعد لكل سوق، وتصدير Pine Script v6، و5 مصادر بيانات مع fallback تلقائي.

</details>

---

## ✨ الميزات الرئيسية

<div align="center">
<table align="center" width="94%" style="width:94%; margin-left:auto; margin-right:auto;">
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-self-improving-trading-agent.png" height="130" alt="وكيل تداول ذاتي التحسن"/><br>
      <h3>🔍 وكيل تداول ذاتي التحسن</h3>
      <div align="left">
        • بحث سوقي باللغة الطبيعية<br>
        • مسودات استراتيجيات وتحليل ملفات/ويب<br>
        • تدفقات عمل مدعومة بالذاكرة
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-multi-agent-trading-teams.png" height="130" alt="فرق تداول متعددة الوكلاء"/><br>
      <h3>🐝 فرق تداول متعددة الوكلاء</h3>
      <div align="left">
        • فرق استثمار وكمّ وكريبتو ومخاطر<br>
        • تقدم مباشر وتقارير محفوظة<br>
        • وكلاء مؤسسون على بيانات سوق مجلوبة
      </div>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-cross-market-data-backtesting.png" height="130" alt="بيانات واختبارات رجعية عبر الأسواق"/><br>
      <h3>📊 بيانات واختبارات رجعية عبر الأسواق</h3>
      <div align="left">
        • أسهم A/HK/US، وكريبتو، وعقود آجلة، وفوركس<br>
        • fallback للبيانات واختبارات مركبة<br>
        • بيانات PIT، وتحقيق، وبطاقات تشغيل
      </div>
    </td>
    <td align="center" width="50%" valign="top">
      <img src="assets/feature-shadow-account.png" height="130" alt="Shadow Account"/><br>
      <h3>👥 Shadow Account</h3>
      <div align="left">
        • تشخيص سلوكي لسجلات الوسطاء<br>
        • مقارنات Shadow Account قائمة على القواعد<br>
        • تقارير تدقيق وكود استراتيجية قابلان للتصدير
      </div>
    </td>
  </tr>
</table>
</div>

## 💡 ما هو Vibe-Trading؟

Vibe-Trading مساحة عمل بحثية مفتوحة المصدر تحول الأسئلة المالية إلى تحليل قابل للتشغيل. يربط المطالبات باللغة الطبيعية بمحملات بيانات السوق، وتوليد الاستراتيجيات، ومحركات الاختبار الرجعي، والتقارير، والتصدير، وذاكرة البحث الدائمة.

صُمم للبحث والمحاكاة والاختبار الرجعي — وعند اختيارك، يتيح أيضاً تداولاً مستقلاً عبر وسيط تُصرّح به بنفسك (مثل Robinhood Agentic Trading). لا يحتفظ بأي أموال، ولا يتداول أبداً خارج الحدود التي تضعها، ويمكنك إيقافه فوراً.

---

## ✨ ما الذي يمكنك فعله؟

| المهمة | الناتج |
|------|--------|
| **طرح سؤال تداول** | بحث سوقي باستخدام الأدوات والبيانات والمستندات وسياق جلسة قابل لإعادة الاستخدام. |
| **اختبار فكرة استراتيجية رجعياً** | كود استراتيجية، ومقاييس، وسياق معياري، ومخرجات تحقق، وبطاقات تشغيل. |
| **مراجعة صفقاتك الخاصة** | قراءة سجلات الوسطاء، وتشخيص السلوك، واستخراج القواعد، ومقارنات Shadow Account. |
| **تحسين الأبحاث المتكررة** | الذاكرة الدائمة والمهارات القابلة للتحرير تحول الروتينات المفيدة إلى تدفقات قابلة لإعادة الاستخدام. |
| **تشغيل فرق محللين** | مراجعات بحث متعددة الوكلاء لتدفقات الاستثمار والكم والكريبتو والماكرو والمخاطر. |
| **وصل الأبحاث بقنوات IM** | إدارة بيئة جلسة واحدة عبر WebSocket وTelegram وSlack وDiscord وMatrix وWhatsApp وSignal وQQ/NapCat وWeChat/WeCom وFeishu/Lark وDingTalk وTeams وemail وMochat من CLI وREST وWeb UI. |
| **إنتاج مخرجات قابلة للاستخدام** | تقارير، وTradingView Pine Script، وTDX، وMetaTrader 5، وأدوات MCP، وجلسات بحث لاحقة. |
| **bench ألفا zoo جاهزة** | تشغيل IC + IR + تصنيف alive/reversed/dead عبر 461 ألفا (Qlib 158 + Kakushadze 101 + GTJA 191 + academic + PIT-safe fundamental) بسطر أوامر واحد على universe الخاص بك. |

---

## ⚡ مثال سريع

```bash
pip install vibe-trading-ai

# بحث بلغة طبيعية
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# bench لـ alpha zoo جاهز بسطر واحد
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 👥 حساب الظل

ينطلق Shadow Account من سجلات تداولك أنت، لا من قالب استراتيجية عام.

ارفع تصديراً من وسيطك، ودع الوكيل يلخص سلوكك، ثم قارن مسار التداول الحقيقي باستراتيجية ظل قائمة على قواعد.

| الخطوة | ناتج الوكيل |
|------|--------------|
| **1. قراءة سجلك** | يقرأ صادرات الوسطاء من 同花顺 و东方财富 و富途 وصيغ CSV العامة. |
| **2. بناء ملف سلوكك** | أيام الاحتفاظ، ومعدل الربح، ونسبة PnL، والتراجع، وdisposition effect، والإفراط في التداول، ومطاردة الزخم، وفحوصات anchoring. |
| **3. استخراج قواعدك** | يحول أنماط الدخول/الخروج المتكررة إلى ملف استراتيجية صريح بدلاً من ملخص ضبابي. |
| **4. تشغيل الظل** | يختبر القواعد المستخرجة رجعياً ويبرز خرق القواعد، والخروج المبكر، والإشارات الفائتة، ومسارات التداول البديلة. |
| **5. تسليم التقرير** | ينتج تقرير HTML/PDF يمكن فحصه أو أرشفته أو تحسينه في جلسة لاحقة. |

```bash
vibe-trading --upload trades_export.csv
vibe-trading run -p "Analyze my trading behavior, extract my shadow strategy, and compare it with my actual trades"
```

---

## 🧪 سير البحث

تتبع أغلب التشغيلات مسار أدلة واحداً: توجيه الطلب، تحميل سياق السوق المناسب، تنفيذ الأدوات، التحقق من المخرجات، وإبقاء المخرجات قابلة للفحص.

| الطبقة | ما يحدث |
|-------|--------------|
| **Plan** | يختار المهارات المالية والأدوات ومصادر البيانات وإعداد السرب الملائمة عند الحاجة. |
| **Ground** | يجلب أسهم A، وأسهم HK/US، والكريبتو، والعقود الآجلة، والفوركس، والمستندات، أو سياق الويب عبر المحملات المتاحة. |
| **Execute** | يولد كود استراتيجية قابل للاختبار، ويشغل الأدوات، ويستخدم محرك الاختبار الرجعي أو سير التحليل المناسب. |
| **Validate** | يضيف المقاييس، والمقارنة المعيارية، وMonte Carlo، وBootstrap، وWalk-Forward، وبطاقات التشغيل، والتحذيرات عند اللزوم. |
| **Deliver** | يعيد التقارير والمخرجات وآثار الأدوات والتصديرات إلى TradingView وTDX وMetaTrader 5 وعملاء MCP أو جلسات لاحقة. |

---

## 📡 مصادر البيانات والتراجع الذكي

استدعاء واحد لـ `get_market_data`، **19 مصدر بيانات سوقية مجانية** (إضافة إلى سوق مدفوع اختياري **QVeris**). اضبط `source: "auto"` — يختار المُحمّل حسب الرمز، ثم يسير عبر سلسلة لكل سوق مرتبة بحسب **خطر حظر عنوان IP**: المصادر العامة التي لا تُحظر أبداً أولاً، والمصادر المُقيّدة أو المحمية بمفتاح أخيراً. بلا أي إعداد، ولا نقطة فشل واحدة.

| Source | Markets | Auth | Role |
|--------|---------|------|------|
| `tencent` · `mootdx` | A-share | none | never IP-banned (`mootdx` = 通达信 TCP) |
| `eastmoney` | A / US / HK | none | OHLCV + deep fundamentals & flow tools (throttled) |
| `baostock` · `akshare` | A (+ US/HK/futures/macro/fx) | none | free fallbacks |
| `tushare` | A / futures / fund / macro | token | richest A-share |
| `yahoo` · `sina` · `stooq` | US (/HK) | none | direct chart/quotes/options · K-line to 1984 · EOD CSV |
| `yfinance` | US / HK | none | wrapper |
| `finnhub` · `alphavantage` · `tiingo` · `fmp` | US | key | optional providers |
| `qveris` | أصول عالمية متعددة | key · credits | **سوق مدفوع** — 63+ مزوداً بمفتاح واحد (اختيار صريح فقط، خارج التراجع التلقائي) |
| `okx` · `ccxt` | crypto | none | OKX + 100+ exchanges |
| `futu` | HK / A | OpenD | optional local FutuOpenD |
| `india_broker` | الهند (NSE/BSE) | تسجيل دخول الوسيط | قراءة فقط لأشرطة Shoonya / Dhan لرموز `.NS` / `.BO` (ذيل سلسلة التراجع) |
| `local` | any | none | your own CSV / Parquet / DuckDB via `local:` prefix |

**سلاسل التراجع (بحسب خطر حظر عنوان IP):**

- **أسهم A** → `tencent` · `mootdx` · `eastmoney` · `baostock` · `akshare` · `tushare` · `local`
- **أسهم US** → `yahoo` · `stooq` · `sina` · `eastmoney` · `yfinance` · `tiingo` · `fmp` · `finnhub` · `alphavantage` · `akshare` · `local`
- **أسهم HK** → `eastmoney` · `yahoo` · `futu` · `yfinance` · `akshare` · `local`
- **أسهم الهند (NSE/BSE)** → `yahoo` · `yfinance` · `india_broker` · `local`
- **الكريبتو** → `okx` · `ccxt` · `yfinance` · `local` &nbsp;·&nbsp; *(العقود الآجلة / الصناديق / الاقتصاد الكلي / الفوركس → `tushare`/`akshare` → `local`)*

إلى جانب OHLCV، تصل **18 أداة بيانات للقراءة فقط** إلى الأساسيات والتدفقات — تدفق الأموال، والتنين والنمر، والتدفق الشمالي، والهامش، والصفقات الكتلية، وعدد المساهمين، وفترة الإغلاق، والقطاعات، وتقارير الأبحاث، والأخبار، وإيداعات SEC، والقوائم المالية، وسلاسل الخيارات، والحيازات المؤسسية، وفحص السوق، والبحث عن الرموز، والاقتصاد الكلي — وكلها مكشوفة عبر MCP. ولا يتراجع رمز `local:` صريح أبداً وبصمت إلى مصدر شبكي.

<!-- QVERIS-START -->
### 💎 بيانات مدفوعة اختيارية — QVeris

<img src="https://www.qveris.com/logo-color.png" alt="QVeris" height="36">

**البيانات المجانية هي الافتراضي، والمدفوعة عند الحاجة.** تبقى المصادر الـ19 المدمجة مجانية مع تراجع ذكي بحسب خطر الحظر، بلا مفتاح ولا تكلفة. عبر QVeris يفتح مفتاح واحد 63+ مزوداً و10,000+ capabilities (per QVeris) للـ options Greeks، والأساسيات المتقدمة، وبيانات الصين/هونغ كونغ/العالم، والماكرو، والكريبتو، والأخبار، والـ filings؛ ولا تُحتسب المكالمات الفاشلة. فعّله من Settings → QVeris أو `vibe-trading data mode paid`.

*QVeris disclosure: التسجيل عبر [رابط إحالة Vibe-Trading](https://qveris.ai/?ref=Vyjjo5G_1cAHJA) يمنحك **+1,000 رصيداً** إضافياً ويدعم المشروع.*
<!-- QVERIS-END -->

---

## 🔩 القدرات التفصيلية

القوائم التفصيلية مطوية أدناه حتى يبقى README سهل القراءة. افتحها عندما تريد فحص اللبنات المتاحة.

<details>
<summary><b>مكتبة المهارات المالية</b> <sub>87 مهارة عبر 9 فئات</sub></summary>

- 📊 87 مهارة مالية متخصصة منظمة في 9 فئات
- 🌐 تغطية كاملة من الأسواق التقليدية إلى الكريبتو وDeFi
- 🔬 قدرات شاملة من مصادر البيانات إلى البحث الكمي

| الفئة | المهارات | أمثلة |
|----------|--------|----------|
| Data Source | 10 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `mootdx`, `ccxt`, `eastmoney`, `sec-edgar`, `qveris` |
| Strategy | 19 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| Analysis | 21 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis`, `dividend-analysis` |
| Asset Class | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| Crypto | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| Flow | 8 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| Tool | 10 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader`, `vnpy-export`, `trade-journal` |
| Research | 2 | `alpha-zoo`, `strategy-dev-manager` |
| Risk Analysis | 1 | `ashare-pre-st-filter` |

</details>

<details>
<summary><b>مصدر بيانات مخصص</b> <sub>سجّل loader تاريخيًا خاصًا بك لبيانات OHLCV</sub></summary>

تحتاج إلى سوق أو مزوّد لا نوفّر له loader جاهزًا؟ أضِف loader تاريخيًا خاصًا بك
واخترْه عبر `source="<name>"`. الخطوات التالية تعدّل مصدر الحزمة، لذا شغّلها من
نسخة clone (`pip install -e .`).

1. **اكتب الـ loader** —— أنشئ `agent/backtest/loaders/<name>_loader.py` مع صنف
   يحقّق `DataLoaderProtocol` (duck-typed، دون صنف أساس) ووسمه بـ `@register`:

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

2. **سجّل الوحدة** كي يعمل `@register` —— أضِف `"backtest.loaders.<name>_loader"`
   إلى `_loader_modules` في `agent/backtest/loaders/registry.py`.
3. **اسمح بالاسم** ليجتاز التحقق من الإعدادات —— أضِف `"mysource"` إلى
   `_VALID_SOURCES` في `agent/backtest/runner.py`.
4. *(اختياري)* أدرِجه ضمن `FALLBACK_CHAINS` لأحد الأسواق في `registry.py` كي
   يصل إليه `source="auto"`.
5. **استخدمه** —— `source="mysource"` في إعداد الباك-تست، أو عبر CLI / agent.

> **بيانات الـ ticks اللحظية / عمق دفتر الأوامر خارج نطاق الـ loaders** —— طبقة
> الـ loader تتعامل فقط مع الأشرطة التاريخية point-in-time. تتدفق بيانات السوق
> اللحظية عبر broker connectors بدلًا من ذلك: `okx` / `binance` / `ccxt`
> للعملات المشفّرة، و`futu` / `tiger` للأسهم.

</details>

<details>
<summary><b>فرق تداول جاهزة</b> <sub>30 إعداد سرب مسبق</sub></summary>

- 🏢 30 فريق وكلاء جاهزاً للاستخدام
- ⚡ تدفقات مالية مهيأة مسبقاً
- 🎯 إعدادات للاستثمار والتداول وإدارة المخاطر

| الإعداد | سير العمل |
|--------|----------|
| `investment_committee` | مناظرة صعود/هبوط → مراجعة مخاطر → قرار مدير المحفظة النهائي |
| `global_equities_desk` | باحث أسهم A + HK/US + كريبتو → استراتيجي عالمي |
| `crypto_trading_desk` | تمويل/أساس + تصفية + تدفق → مدير مخاطر |
| `earnings_research_desk` | أساسيات + مراجعات + خيارات → استراتيجي أرباح |
| `macro_rates_fx_desk` | أسعار فائدة + FX + سلع → مدير محفظة ماكرو |
| `quant_strategy_desk` | فرز + بحث عوامل → اختبار رجعي → تدقيق مخاطر |
| `technical_analysis_panel` | TA كلاسيكي + Ichimoku + harmonic + Elliott + SMC → إجماع |
| `risk_committee` | تراجع + مخاطر ذيل + مراجعة نظام → اعتماد |
| `global_allocation_committee` | أسهم A + كريبتو + HK/US → تخصيص عبر الأسواق |

<sub>بالإضافة إلى أكثر من 20 إعداداً متخصصاً آخر — شغل vibe-trading --swarm-presets لاستكشافها كلها.

</sub>

</details>

<details>
<summary><b>Alpha Zoo</b> <sub>461 ألفا كمّي جاهز عبر 5 families</sub></summary>

- 🧬 461 ألفا cross-sectional، مع منع lookahead على طبقة العوامل (operators)
- 📈 IC + IR + تصنيف alive/reversed/dead بأمر CLI واحد
- 🔬 بوابة نقاء AST + اختبار حماية lookahead بـ 300 صف + قاطع شبكة عبر `pytest-socket`
- 📦 إسناد Apache-2 لـ Qlib؛ ملف `LICENSE.md` لكل zoo يصرّح بأن الصيغ محتوى رياضي
- 🤝 سير عمل توقيع Developer Certificate of Origin (DCO) لمساهمات المجتمع

| Zoo | العدد | المصدر | الرخصة |
|-----|-------|--------|--------|
| **qlib158** | 154 | Microsoft Qlib `Alpha158` (Apache-2.0، مثبّت على commit) | Apache-2.0 |
| **alpha101** | 101 | Kakushadze (2015)، "101 Formulaic Alphas"، arXiv:1601.00991 | الصيغ محتوى رياضي |
| **gtja191** | 191 | Guotai Junan (2014)، "191 Short-period Trading Alpha Factors" | الصيغ محتوى رياضي |
| **academic** | 11 | Fama-French 5 + Carhart momentum (proxy قائم على الأسعار) + Jegadeesh reversal + George-Hwang 52-week-high + Amihud illiquidity + Harvey-Siddique skew + Frazzini-Pedersen betting-against-beta | أدبيات أكاديمية عامة |
| **fundamental** | 4 | بيانات SEC company facts آمنة PIT — earnings yield وROE وgross profitability وasset growth (مثبّتة على filed-date) | بيانات مالية عامة |

شغّل `vibe-trading alpha list` للتصفح، و`vibe-trading alpha show <id>` للحصول على الصيغ + المصدر، و`vibe-trading alpha bench --zoo X --universe Y --period Z` لتقييم zoo كاملة.

</details>

## 🎬 العرض التوضيحي

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
<td colspan="2" align="center"><sub>☝️ اختبار رجعي باللغة الطبيعية ومناظرة سرب متعدد الوكلاء — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 البدء السريع

### تثبيت بسطر واحد (PyPI)

```bash
pip install vibe-trading-ai
```

ثم شغل أول مهمة بحثية:

```bash
vibe-trading init
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024 and summarize return and drawdown"
```

> **هل تُحدِّث من إصدار أقدم؟** انتقل الإصدار 0.1.10 إلى LangChain 1.x. إذا انكسرت عمليات الاستيراد بعد تشغيل `pip install -U vibe-trading-ai` فوق تثبيت أقدم من 0.1.10 (مثل فشل استيراد langgraph)، فأعد إنشاء الـ venv أو شغّل `pip install --force-reinstall vibe-trading-ai`. التثبيت الجديد غير متأثر.

> **اسم الحزمة مقابل الأوامر:** حزمة PyPI هي `vibe-trading-ai`. بعد التثبيت تحصل على ثلاثة أوامر:
>
> | الأمر | الغرض |
> |---------|---------|
> | `vibe-trading` | CLI / TUI تفاعلي |
> | `vibe-trading serve` | تشغيل خادم ويب FastAPI |
> | `vibe-trading-mcp` | بدء خادم MCP (لـ Claude Desktop وOpenClaw وCursor وغيرها) |

```bash
vibe-trading init              # interactive .env setup
vibe-trading                   # launch CLI
vibe-trading serve --port 8899 # launch web UI
vibe-trading-mcp               # start MCP server (stdio)
```

### أو اختر مساراً

| المسار | الأنسب لـ | الوقت |
|------|----------|------|
| **A. Docker** | التجربة الآن، دون إعداد محلي | دقيقتان |
| **B. تثبيت محلي** | التطوير والوصول الكامل إلى CLI | 5 دقائق |
| **C. MCP plugin** | وصله بوكيلك الحالي | 3 دقائق |
| **D. ClawHub** | أمر واحد دون استنساخ | دقيقة واحدة |

### المتطلبات المسبقة

- **مفتاح API لنموذج LLM** من أي مزود مدعوم — أو التشغيل محلياً عبر **Ollama** (لا يحتاج مفتاحاً)
- **Python 3.11+** للمسار B
- **Docker** للمسار A
- يمكن استخدام OpenAI Codex أيضاً عبر ChatGPT OAuth: اضبط `LANGCHAIN_PROVIDER=openai-codex`، ثم شغل `vibe-trading provider login openai-codex`. هذا لا يستخدم `OPENAI_API_KEY`.

> **مزودو LLM المدعومون:** OpenRouter, Requesty, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama (local). راجع `.env.example` للإعداد.

> **نصيحة:** تعمل كل الأسواق دون مفاتيح API بفضل fallback التلقائي. yfinance (HK/US)، وOKX (crypto)، وmootdx (أسهم A، اتصال TCP مباشر بدون قيود IP)، وAKShare (A-shares, US, HK, futures, forex) كلها مجانية. رمز Tushare اختياري — mootdx هو الـ fallback الموصى به لأسهم A بدون رمز، بينما يوفر AKShare احتياطياً أوسع تغطية.

### المسار A: Docker (دون إعداد)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# Edit agent/.env — uncomment your LLM provider and set API key
docker compose up --build
```

افتح `http://localhost:8899`. الخلفية والواجهة الأمامية داخل حاوية واحدة.

ينشر Docker الخلفية على `127.0.0.1:8899` افتراضياً ويشغل التطبيق كمستخدم حاوية غير root. إذا كنت تقصد تعريض API خارج جهازك، فاضبط `API_AUTH_KEY` قوياً وأرسل `Authorization: Bearer <key>` من العملاء.

### المسار B: التثبيت المحلي

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
<summary><b>تشغيل واجهة الويب (اختياري)</b></summary>

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend dev server
cd frontend && npm install && npm run dev
```

افتح `http://localhost:5899`. تمرر الواجهة الأمامية استدعاءات API إلى `localhost:8899`.

**وضع الإنتاج (خادم واحد):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI serves dist/ as static files
```

> [!NOTE]
> يرتبط `vibe-trading serve` بالعنوان `0.0.0.0` لكنه يثق فقط بطلبات loopback افتراضيًا: فتح الواجهة على **نفس الجهاز** (`http://localhost:8899`) يعمل دون أي إعداد. إذا تصفّحت من **جهاز آخر أو مضيف جهاز افتراضي أو هاتف على شبكتك المحلية**، فستُعيد النقاط الحساسة الرمز `403` وتظهر في المحادثة رسالة “Remote API access requires an API key” — عيّن مفتاح `API_AUTH_KEY` قويًا في `agent/.env`، ثم أعد التشغيل وأدخل المفتاح نفسه مرة واحدة في **Settings**. (بوابة مضيف Docker Desktop: عيّن `VIBE_TRADING_TRUST_DOCKER_LOOPBACK=1` مع الإبقاء على ربط المنفذ الافتراضي `127.0.0.1`.)

</details>

### المسار C: MCP plugin

راجع قسم [MCP Plugin](#-mcp-plugin) أدناه.

### المسار D: ClawHub (أمر واحد)

```bash
npx clawhub@latest install vibe-trading --force
```

تُنزل المهارة وإعداد MCP إلى مجلد مهارات وكيلك. راجع [تثبيت ClawHub](#-mcp-plugin) للتفاصيل.

---

## 🧠 متغيرات البيئة

انسخ `agent/.env.example` إلى `agent/.env` وأزل التعليق عن كتلة المزود التي تريدها. يحتاج كل مزود إلى 3-4 متغيرات:

| المتغير | مطلوب | الوصف |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | نعم | اسم المزود (`openrouter`, `deepseek`, `groq`, `ollama`, إلخ) |
| `<PROVIDER>_API_KEY` | نعم* | مفتاح API (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, إلخ) |
| `<PROVIDER>_BASE_URL` | نعم | عنوان URL لنقطة نهاية API |
| `LANGCHAIN_MODEL_NAME` | نعم | اسم النموذج (مثل `deepseek-v4-pro`) |
| `TUSHARE_TOKEN` | لا | رمز Tushare Pro لبيانات أسهم A (يرجع إلى AKShare عند الحاجة) |
| `TIMEOUT_SECONDS` | لا | مهلة استدعاء LLM، الافتراضي 120s |
| `API_AUTH_KEY` | موصى به للنشر الشبكي | Bearer token مطلوب عندما يكون API قابلاً للوصول من عملاء غير محليين |
| `VIBE_TRADING_ENABLE_SHELL_TOOLS` | لا | تفعيل صريح للأدوات القادرة على shell في نشر API/MCP-SSE البعيد |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS` | لا | جذور إضافية مفصولة بفواصل لاستيراد المستندات وسجلات الوسطاء |
| `VIBE_TRADING_ALLOWED_RUN_ROOTS` | لا | جذور إضافية مفصولة بفواصل لأدلة تشغيل الكود المولد |

<sub>* لا يحتاج Ollama إلى مفتاح API. يستخدم OpenAI Codex ChatGPT OAuth ويخزن الرموز عبر `oauth-cli-kit`، لا داخل `agent/.env`.</sub>

**بيانات مجانية (دون مفتاح):** أسهم A عبر AKShare، وأسهم HK/US عبر yfinance، والكريبتو عبر OKX، وأكثر من 100 بورصة كريبتو عبر CCXT. يختار النظام تلقائياً أفضل مصدر متاح لكل سوق.

### 🎯 النماذج الموصى بها

Vibe-Trading وكيل كثيف الأدوات؛ المهارات والاختبارات الرجعية والذاكرة والأسراب كلها تمر عبر استدعاءات أدوات. اختيار النموذج يحدد مباشرة هل سيستخدم الوكيل أدواته أم سيصطنع إجابات من بيانات التدريب.

| المستوى | أمثلة | متى تستخدمه |
|------|----------|-------------|
| **الأفضل** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.5-pro`, `google/gemini-3.5-flash` | أسراب معقدة (3+ وكلاء)، جلسات بحث طويلة، تحليل بمستوى ورقة علمية |
| **النقطة المثلى** (افتراضي) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.6`, `qwen/qwen3-max-thinking` | الاستخدام اليومي، tool-calling موثوق بنحو عُشر التكلفة |
| **تجنبها لاستخدام الوكيل** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | tool-calling غير موثوق؛ سيبدو الوكيل وكأنه "يجيب من الذاكرة" بدلاً من تحميل المهارات أو تشغيل الاختبارات الرجعية |

يأتي `agent/.env.example` افتراضياً مع DeepSeek official API + `deepseek-v4-pro`; ويمكن لمستخدمي OpenRouter استخدام `deepseek/deepseek-v4-pro`.

---

## 🖥 مرجع CLI

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
vibe-trading alpha list    # استعرض 461 ألفا جاهز؛ متاح show / bench / compare / export-manifest
vibe-trading channels status --local  # فحص إعدادات قنوات IM وتلميحات التثبيت
```

<details>
<summary><b>أوامر الشرطة المائلة داخل TUI</b></summary>

| الأمر | الوصف |
|---------|-------------|
| `/help` | عرض كل الأوامر |
| `/skills` | عرض كل المهارات المالية الـ 87 |
| `/swarm` | عرض إعدادات فرق السرب الـ 30 |
| `/swarm run <preset> [vars_json]` | تشغيل فريق سرب مع بث مباشر |
| `/swarm list` | سجل تشغيلات السرب |
| `/swarm show <run_id>` | تفاصيل تشغيل السرب |
| `/swarm cancel <run_id>` | إلغاء سرب قيد التشغيل |
| `/list` | التشغيلات الأخيرة |
| `/show <run_id>` | تفاصيل التشغيل + المقاييس |
| `/code <run_id>` | كود الاستراتيجية المولدة |
| `/pine <run_id>` | تصدير المؤشرات (TradingView + TDX + MT5) |
| `/trace <run_id>` | إعادة تشغيل التنفيذ كاملة |
| `/continue <run_id> <prompt>` | متابعة تشغيل بتعليمات جديدة |
| `/sessions` | عرض جلسات الدردشة |
| `/settings` | عرض إعدادات التشغيل |
| `/clear` | مسح الشاشة |
| `/quit` | خروج |

</details>

<details>
<summary><b>تشغيل واحد والخيارات</b></summary>

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

```bash
vibe-trading alpha list --zoo gtja191 --limit 10
vibe-trading alpha show gtja191_171
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

</details>

<details>
<summary><b>قنوات IM</b></summary>

تصل محولات IM تطبيقات الدردشة الخارجية ببيئة الجلسة نفسها التي يستخدمها Web UI وCLI. اضبط المحولات المفعّلة تحت `channels` في `~/.vibe-trading/agent.json`. المحولات المعتمدة على SDK اختيارية عبر extras، وعند غياب SDK تعرض تلميحات استرداد بدلاً من إسقاط runtime.

```bash
vibe-trading channels status --local   # فحص config وتلميحات SDK الناقصة دون API
vibe-trading channels status           # الاستعلام عن API runtime الجاري
vibe-trading channels start            # بدء المحولات المفعّلة عبر API
vibe-trading channels stop             # إيقاف المحولات المفعّلة عبر API
vibe-trading channels login weixin     # تشغيل hook تسجيل الدخول عند الحاجة
vibe-trading channels pairing --channel telegram list
```

تشمل المحولات المدمجة `websocket` و`telegram` و`slack` و`discord` و`matrix` و`whatsapp` و`signal` و`qq` و`napcat` و`weixin` و`wecom` و`feishu` و`dingtalk` و`msteams` و`email` و`mochat`. يمكنك تثبيت منصة محددة مثل `pip install "vibe-trading-ai[telegram]"` أو تثبيت المجموعة كاملة عبر `pip install "vibe-trading-ai[channels]"`.

**أوامر الشرطة داخل المحادثة** (مستقلة عن القناة، تعمل في جميع المحولات الـ 16):

| الأمر | الوصف |
|-------|-------|
| `/new` | إعادة تعيين الجلسة الحالية — الرسالة التالية تبدأ محادثة جديدة |
| `/reset` | اسم مستعار لـ `/new` |
| `/newsession` | اسم مستعار لـ `/new` |
| `/pairing list` | عرض طلبات sender pairing المعلقة |

الأوامر لا تحس بحالة الأحرف ويجب إرسالها كرسالة كاملة (مثلاً `hello /new` تُعامل كرسالة عادية وليس كأمر إعادة تعيين).

</details>

---

## 💡 أمثلة

### الاستراتيجيات والاختبار الرجعي

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

**bench ألفا zoo جاهز بسطر واحد**:
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

**استعرض الكتالوج** وافحص ألفا مفردة:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**ركّب إشارة متعدد العوامل** من ألفات zoo (Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

### بحث السوق

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### تدفقات السرب

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

### ذاكرة عبر الجلسات

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### رفع المستندات وتحليلها

```bash
# Analyze a broker export or earnings report
vibe-trading --upload trades_export.csv
vibe-trading run -p "Profile my trading behavior and identify any biases"

vibe-trading --upload NVDA_Q1_earnings.pdf
vibe-trading run -p "Summarize the key risks and beats/misses from this earnings report"
```

---

## 🌐 خادم API

```bash
vibe-trading serve --port 8899
```

| الطريقة | نقطة النهاية | الوصف |
|--------|----------|-------------|
| `GET` | `/runs` | عرض التشغيلات |
| `GET` | `/runs/{run_id}` | تفاصيل التشغيل |
| `GET` | `/runs/{run_id}/pine` | تصدير مؤشرات متعدد المنصات |
| `POST` | `/sessions` | إنشاء جلسة |
| `POST` | `/sessions/{id}/messages` | إرسال رسالة |
| `GET` | `/sessions/{id}/events` | بث أحداث SSE |
| `POST` | `/upload` | رفع PDF/ملف |
| `GET` | `/swarm/presets` | عرض إعدادات السرب |
| `POST` | `/swarm/runs` | بدء تشغيل سرب |
| `GET` | `/swarm/runs/{id}/events` | بث SSE للسرب |
| `GET` | `/alpha/list` | قائمة ألفات مع تصفية حسب zoo/theme/universe |
| `GET` | `/alpha/{alpha_id}` | بيانات وصفية + الكود المصدري للألفا |
| `POST` | `/alpha/bench` | بدء مهمة bench (يعيد `job_id`) |
| `GET` | `/alpha/bench/{job_id}/stream` | تدفق تقدّم SSE |
| `GET` | `/settings/llm` | قراءة إعدادات LLM في Web UI |
| `PUT` | `/settings/llm` | تحديث إعدادات LLM المحلية |
| `GET` | `/settings/data-sources` | قراءة إعدادات مصادر البيانات المحلية |
| `PUT` | `/settings/data-sources` | تحديث إعدادات مصادر البيانات المحلية |
| `GET` | `/channels/status` | قراءة حالة IM channel runtime والمحولات |
| `POST` | `/channels/start` | بدء محولات IM configured |
| `POST` | `/channels/stop` | إيقاف محولات IM configured |
| `POST` | `/channels/pairing/command` | تنفيذ أمر sender-pairing على shared store |
| `POST` | `/scheduled-runs` | إنشاء مهمة بحث مجدولة (interval-ms أو cron) |
| `GET` | `/scheduled-runs` | سرد المهام المجدولة |
| `DELETE` | `/scheduled-runs/{job_id}` | إلغاء مهمة مجدولة |

توثيق تفاعلي: `http://localhost:8899/docs`

### الإعدادات الأمنية الافتراضية

للتطوير على localhost، يبقي `vibe-trading serve` سير المتصفح بسيطاً. لأي عميل غير محلي، تتطلب نقاط API الحساسة `API_AUTH_KEY`؛ استخدم `Authorization: Bearer <key>` لطلبات JSON/الرفع. تتعامل Web UI مع تدفقات Browser EventSource بعد إدخال المفتاح نفسه مرة واحدة في Settings.

تتوفر الأدوات القادرة على shell للـ CLI المحلي وتدفقات localhost الموثوقة، لكنها لا تُعرض لجلسات API البعيدة ما لم تضبط صراحة `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`. قارئات المستندات والسجلات محدودة افتراضياً بجذور الرفع/الاستيراد؛ ضع الملفات تحت `agent/uploads` أو `agent/runs` أو `./uploads` أو `./data` أو `~/.vibe-trading/uploads` أو `~/.vibe-trading/imports`، أو أضف دليلاً مخصصاً عبر `VIBE_TRADING_ALLOWED_FILE_ROOTS`.

### إعدادات Web UI

تتيح صفحة Settings في Web UI للمستخدمين المحليين تحديث مزود/نموذج LLM، وbase URL، ومعلمات التوليد، وreasoning effort، وبيانات اعتماد السوق الاختيارية مثل رمز Tushare. تُحفظ الإعدادات في `agent/.env`؛ وتُحمّل قيم المزودين الافتراضية من `agent/src/providers/llm_providers.json`.

قراءات Settings بلا آثار جانبية: لا تنشئ `GET /settings/llm` ولا `GET /settings/data-sources` ملف `agent/.env`، ولا تعيدان إلا مسارات نسبية للمشروع. قد تكشف قراءات وكتابات Settings حالة بيانات الاعتماد أو تحدث بيانات الاعتماد/بيئة التشغيل، لذلك تتطلب `API_AUTH_KEY` عند ضبطه. إذا كان `API_AUTH_KEY` غير مضبوط في وضع التطوير، فلا يقبل الوصول إلى Settings إلا من عملاء loopback.

تحتوي صفحة Settings نفسها على لوحة **قنوات IM** للمشغل المحلي. تستطلع `/channels/status`، وتعرض حالات configured/enabled/available/loaded/running وتلميحات استرداد المحولات، ويمكنها بدء أو إيقاف channel runtime configured دون العودة إلى الطرفية.

### البحث المجدول (Scheduled research)

شغّل prompt بحثي أو backtest وفق جدول متكرر. المنفّذ الخلفي **معطّل افتراضياً** — شغّل الخادم بـ `VIBE_TRADING_ENABLE_SCHEDULER=1` لتفعيله:

```bash
VIBE_TRADING_ENABLE_SCHEDULER=1 vibe-trading serve --port 8899
```

ثم أنشئ المهام عبر REST. الحقل `schedule` إما عدد صحيح بسيط (الفاصل بـ**المللي ثانية**) أو تعبير cron من 5 حقول (`دقيقة ساعة يوم شهر يوم-الأسبوع`):

```bash
# كل 6 ساعات (cron)
curl -X POST http://localhost:8899/scheduled-runs \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Scan CSI300 for momentum breakouts and backtest the top 5","schedule":"0 */6 * * *"}'

# السرد / الإلغاء
curl http://localhost:8899/scheduled-runs
curl -X DELETE http://localhost:8899/scheduled-runs/<job_id>
```

كل تشغيل ينفّذ `prompt` في جلسة agent جديدة (تُوضع معلمات backtest الاختيارية في `config`)، وتُحفظ المهام تحت `~/.vibe-trading/` فتبقى بعد إعادة التشغيل. بدون هذه الراية، تسجّل نقاط `/scheduled-runs` المهام لكن لا يُطلق شيء. أضف `-H "Authorization: Bearer <key>"` لكل طلب عند ضبط `API_AUTH_KEY`.

---

## 🔌 MCP Plugin

يعرض Vibe-Trading 54 أداة MCP لأي عميل متوافق مع MCP. يعمل كعملية stdio فرعية، دون إعداد خادم. أدوات البحث الأساسية تعمل دون أي مفاتيح API لأسواق HK/US/crypto؛ وأدوات connector للتداول تستخدم profile الموصل المختار، ويحتاج `run_swarm` وحده إلى مفتاح LLM.

<details>
<summary><b>Claude Desktop</b></summary>

أضف إلى `claude_desktop_config.json`:

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

أضف إلى `~/.openclaw/config.yaml`:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / عملاء MCP آخرون</b></summary>

```bash
vibe-trading-mcp                  # stdio (default)
vibe-trading-mcp --transport sse  # SSE for web clients
```

</details>

**أدوات MCP المعروضة (54):** `list_skills`, `load_skill`, `start_research_goal`, `get_research_goal`, `add_goal_evidence`, `update_research_goal_status`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `read_url`, `read_document`, `web_search`, `write_file`, `read_file`, `trading_connections`, `trading_select_connection`, `trading_check`, `trading_account`, `trading_positions`, `trading_orders`, `trading_quote`, `trading_history`, `list_swarm_presets`, `run_swarm`, `get_market_data`, `get_fund_flow`, `get_dragon_tiger`, `get_northbound_flow`, `get_margin_trading`, `get_block_trades`, `get_shareholder_count`, `get_lockup_expiry`, `get_sector_info`, `get_research_reports`, `get_stock_news`, `get_sec_filings`, `get_financial_statements`, `get_options_chain`, `get_stock_profile`, `screen_market`, `search_symbol`, `get_macro_series`, `iwencai_search`, `get_swarm_status`, `get_run_result`, `list_runs`, `reap_stale_runs`, `retry_run`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`.

<details>
<summary><b>التثبيت من ClawHub (أمر واحد)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` مطلوب لأن المهارة تشير إلى واجهات API خارجية، مما يطلق فحص VirusTotal الآلي. الكود مفتوح المصدر بالكامل وآمن للفحص.

ينزل هذا المهارة وإعداد MCP إلى مجلد مهارات وكيلك. لا حاجة للاستنساخ.

تصفح على ClawHub: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — مهارات ذاتية التطور</b></summary>

كل المهارات المالية الـ 87 منشورة على [open-space.cloud](https://open-space.cloud) وتتطور ذاتياً عبر محرك التطور الذاتي في OpenSpace.

للاستخدام مع OpenSpace، أضف خادمي MCP إلى إعداد وكيلك:

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

سيكتشف OpenSpace كل المهارات الـ 87 تلقائياً، مما يتيح auto-fix وauto-improve والمشاركة المجتمعية. ابحث عن مهارات Vibe-Trading عبر `search_skills("finance backtest")` في أي وكيل متصل بـ OpenSpace.

</details>

---

## 📁 هيكل المشروع

<details>
<summary><b>انقر للتوسيع</b></summary>

```
Vibe-Trading/
├── agent/                          # Backend (Python)
│   ├── cli/                        # CLI package — interactive TUI + subcommands
│   ├── api_server.py               # FastAPI server — runs, sessions, upload, swarm, SSE
│   ├── mcp_server.py               # MCP server — 54 tools for OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct agent core
│   │   │   ├── loop.py             #   5-layer compression + read/write tool batching
│   │   │   ├── context.py          #   system prompt + auto-recall from persistent memory
│   │   │   ├── skills.py           #   skill loader (87 bundled + user-created via CRUD)
│   │   │   ├── tools.py            #   tool base class + registry
│   │   │   ├── memory.py           #   lightweight workspace state per run
│   │   │   ├── frontmatter.py      #   shared YAML frontmatter parser
│   │   │   └── trace.py            #   execution trace writer
│   │   │
│   │   ├── memory/                 # Cross-session persistent memory
│   │   │   └── persistent.py       #   file-based memory (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 68 auto-discovered agent tools
│   │   │   ├── backtest_tool.py    #   run backtests
│   │   │   ├── remember_tool.py    #   cross-session memory (save/recall/forget)
│   │   │   ├── skill_writer_tool.py #  skill CRUD (save/patch/delete/file)
│   │   │   ├── session_search_tool.py # FTS5 cross-session search
│   │   │   ├── swarm_tool.py       #   launch swarm teams
│   │   │   ├── web_search_tool.py  #   DuckDuckGo web search
│   │   │   └── ...                 #   bash, file I/O, factor analysis, options, alpha browser + bench, etc.
│   │   │
│   │   ├── factors/                # Alpha Zoo — 461 ألفا عبر 5 families
│   │   │   ├── base.py             #   19 عاملاً (rank/scale/ts_*/delta/decay_linear/safe_div/vwap)
│   │   │   ├── registry.py         #   تحميل بيانات وصفية AST فقط + حساب كسول + بوابات سلامة
│   │   │   ├── bench_runner.py     #   IC + تصنيف alive/reversed/dead
│   │   │   └── zoo/                #   qlib158 (154) + alpha101 (101) + gtja191 (191) + academic (10) + fundamental (4)
│   │   │
│   │   ├── api/                    # وحدات مسارات FastAPI
│   │   │   └── alpha_routes.py     #   /alpha/list, /alpha/{id}, /alpha/bench, SSE stream
│   │   │
│   │   ├── skills/                 # 87 finance skills in 9 categories (SKILL.md each)
│   │   ├── swarm/                  # Swarm DAG execution engine
│   │   │   └── presets/            #   30 swarm preset YAML definitions
│   │   ├── session/                # Multi-turn chat + FTS5 session search
│   │   └── providers/              # LLM provider abstraction
│   │
│   └── backtest/                   # Backtest engines
│       ├── engines/                #   7 engines + composite cross-market engine + options_portfolio
│       ├── loaders/                #   20 sources: tushare, okx, yfinance, akshare, baostock, tencent, mootdx, ccxt, futu, local, eastmoney, sina, stooq, yahoo, finnhub, alphavantage, tiingo, fmp, qveris, india_broker
│       │   ├── base.py             #   DataLoader Protocol
│       │   └── registry.py         #   Registry + auto-fallback chains
│       └── optimizers/             #   MVO, equal vol, max div, risk parity
│
├── frontend/                       # Web UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   Home, Agent, AlphaZoo, RunDetail, Compare, Correlation, Settings
│       ├── components/             #   chat, charts, layout
│       └── stores/                 #   Zustand state management
│
├── Dockerfile                      # Multi-stage build
├── docker-compose.yml              # One-command deploy
├── pyproject.toml                  # Package config + CLI entrypoint
├── tools/                          # Repo-level CI helpers
│   └── ci_grep_gates.sh            # rejects yaml.load / trademark / per-stock-data leaks
└── LICENSE                         # MIT
```

</details>

---

## 🏛 النظام البيئي

Vibe-Trading جزء من نظام وكلاء **[HKUDS](https://github.com/HKUDS)**:

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

## 🗺 خارطة الطريق

> نشحن على مراحل. تنتقل العناصر إلى [Issues](https://github.com/HKUDS/Vibe-Trading/issues) عندما يبدأ العمل.

| المرحلة | الميزة | الحالة |
|-------|---------|--------|
| **Trust Layer** | بطاقات تشغيل قابلة لإعادة الإنتاج تُنتج وتظهر في Run Detail؛ يضيف v1 آثار الأدوات والاستشهادات | v0 شُحن |
| **Hypothesis Registry** | فرضيات بحثية دائمة مع حالة lifecycle ومصادر بيانات ومهارات وروابط run-card وملاحظات إبطال | Backend MVP شُحن |
| **Research Autopilot** | حلقة بحث يدوية أولاً: فرضية → اختبار رجعي حتمي → تقرير أدلة | المراحل 1–3 شُحنت |
| **Data Bridge** | أحضر بياناتك: موصلات CSV/Parquet/SQL محلية مع schema mapping | المُحمِّل المحلي شُحن |
| **Options Lab** | سطح تقلب، ولوحة Greeks، ومستكشف payoff/scenario | مخطط |
| **Portfolio Studio** | أشعة مخاطر، وقيود، ومحسن يراعي الدوران، وملاحظات إعادة توازن | محسن يراعي الدوران **تم الإطلاق 0.1.11**؛ الباقي مخطط |
| **Alpha Zoo** | 461 ألفا كمّي جاهز (Qlib 158 + Kakushadze 101 + GTJA 191 + academic + fundamental)، سطر أوامر واحد للـ bench، تكامل agent، وواجهة Web | **تم الإطلاق 0.1.8**، موسّع حتى 0.1.11 |
| **Research Delivery** | موجزات مجدولة وجلسات بحث حي عبر Slack / Telegram / قنوات IM شبيهة بالبريد | المُجدوِل + IM Runtime شُحنا |
| **Community** | مهارات وإعدادات مسبقة وبطاقات استراتيجية قابلة للمشاركة | قيد الاستكشاف |

---

## المساهمة

نرحب بالمساهمات! راجع [CONTRIBUTING.md](CONTRIBUTING.md) للإرشادات.

**المشكلات الجيدة للمبتدئين** موسومة بـ [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — اختر واحدة وابدأ.

هل تريد المساهمة بشيء أكبر؟ راجع [خارطة الطريق](#-خارطة-الطريق) أعلاه وافتح issue للنقاش قبل البدء.

---

## المساهمون

شكراً لكل من ساهم في Vibe-Trading!

مساهمو واعتمادات دورة v0.1.11 الأخيرة:

- @shadowinlife — تتويج تحديث وحدات `api_server` (من 1,103 إلى 371 سطراً، #424 يغلق #331)، ومركزية إعداد البيئة مع بوابة CI المعتمدة على AST (#440)، ومطابقة بروتوكول `fetch()` في المحمّلات (#437)، وRFC لمدير تطوير الاستراتيجيات قيد المراجعة (#455/#457) — 12 PR مدموجاً هذه الدورة
- @Robin1987China — إغلاق حلقة Research Autopilot (المرحلة 3) (#267)، و4 عوامل ألفا أكاديمية قياسية (#277)، وشروط دخول Shadow Account الآمنة زمنياً (PIT-safe) (#302/#314/#316)، ومحسّن المحفظة الذي يراعي الدوران (#466)، واختبارات مسارات scheduled-research (#452)، ودفعات تغطية اختبارية لطبقات trade-journal / pattern / loader (#268/#269/#276)
- @muku314115 — دعم الأسهم الهندية (NSE/BSE) من الدرجة الأولى: محرك `IndiaEquityEngine`، وحزمة التكاليف، وتوجيه `.NS`/`.BO`، وجسر `india_broker` (#305)
- @mvanhorn — مُنفِّذ الأبحاث المجدولة من طرف إلى طرف (#278)، وموصّل Trading 212 للقراءة فقط (#321)، وحسم النموذج الافتراضي لـ OpenAI (#319)، والتحقق من إعداد Robinhood (#320)
- @fei-moss — أداة الرؤية `analyze_image` (#464)، وإقران NapCat DM (#463)، وتقرير allowed-roots لوسائط IM (#465)
- @sambazhu — طقم أدوات الاستثمار القيمي: أدوات الصرامة المالية + تدقيق التقارير، و4 مهارات، وإعداد `value_investing_committee` المسبق (#407/#408)
- @Elfsa-Miranda — استكشاف خط أنابيب أبحاث ألفا المقيّد بالأدلة (#405/#416، أُعيد تحديد نطاقه لاحقاً ضمن #442)
- @Hinotoi-agent — رفض CSRF على الاسترجاع (#293)، وطلبات واجهة same-origin البعيدة المصادَقة (#304)
- @dpersek — مهلة رد IM قابلة للتهيئة (#413)، وإصلاح redirect في provider preflight (#404)
- @digger-yu — أوامر `setup`/`dev` عبر المنصات (#292)، وفحوص مسبقة لتبعيات التطوير (#349)
- @skloxo — توسيع التلدة (~) + تراجع أمان لجذور الملفات (#299)، وتوطين zh-CN تفاعلي (#301)
- @kadaliao — دليل المبتدئين (#393)، وبطاقات Alpha Library الاجتماعية (#396)
- @morluto — الحفاظ على أول رسالة عند استئناف CLI (#448)، والنموذج الافتراضي لـ Codex OAuth (#446)
- @yxhuang — مزوّد Kimi for Coding (#435)، والتشخيص الدقيق لـ #433 خلف التراجع عن governance stack
- @isaveall — إصلاح دليل artifacts لـ `validation.json` (#429)، وأخطاء `--swarm-run` أوضح (#428)
- @mustafakamal88 — طوابع زمنية UTC واعية بالمنطقة الزمنية (#397)
- @irfanallana-oss — حارس الأوامر ذات الحجم الصفري في `trading_place_order` (#417)
- @Shizoqua — حارس المحمّل المركزي لثوابت OHLC (#274)
- @hobostay — تقوية حارس SSRF لنطاقات CGNAT/mesh + إصلاح redirect لوسائط QQ (#389)
- @aeonframework — رفع حدود CVE الدنيا لـ Pillow / langchain (#390)
- @hannibal-lee — إصلاح قيد إصدار pandas (#329)
- @MarkfuGod — عدّ مصادر البيانات الديناميكي + microcompaction محكوم بالـ tokens (#296)
- @gyx09212214-prog — مخرجات تحقق JSON صارمة (#306)
- @LemonCANDY42 — مكتبة تقارير الاختبار الخلفي (#224)
- @fanfpy — تسلسل Longbridge Decimal→float (#459)
- @asahikiko — مزامنة عدّ القدرات في SKILL.md المحزوم + اختبار حارس المانيفست (#461)
- @wison1717-maker — مربع التأكيد الثاني للتفويض + توحيد رسائل الأخطاء (#453)
- @imsankz — تعيينات مزوّد opencode (#444)
- @flash1234pku — إصلاح code-fence في مراجع tushare (#449)
- @Penn-Live — تقرير انهيار route-iteration عند بدء Docker (#450)
- @warren618 / Haozhe Wu — طبقة العوامل الأساسية (panels SEC آمنة زمنياً PIT-safe)، ومسار QVeris المدفوع، وبيئة تشغيل قنوات IM، ومراجعة تكامل الأسهم الهندية، وfallback البحث الصيني، وتكامل الإصدار

<details>
<summary>مساهمو دورة v0.1.10</summary>

- @Hinotoi-agent — موجة تقوية أمنية: مصادقة الإيقاف المحلي (#241)، ورفض إعادة ربط مضيف الاسترجاع (#242)، وتفعيل صريح لأدوات shell للوكيل (#243)، ومصادقة كتابة الإعدادات (#245)، واحتواء mandate proposal-id (#256)، والتحقق من أنواع الذاكرة الدائمة (#257)، واحتواء MCP swarm run-id (#258)
- @mvanhorn — ذاكرة تخزين بيانات محلية اختيارية (#177)، وذهاب وإياب Gemini thoughtSignature عبر استدعاءات أدوات متوافقة مع OpenAI (#176)، ودليل مصدر بيانات مخصّص (#194)، واسم بديل لمزوّد glm/zhipu + استنتاج اسم النموذج (#247)
- @gyx09212214-prog — متانة المحمّل أمام متغيّرات بيئة مهلة crypto/RSSHub المشوّهة (#227، #240)، وتضمين تاريخ النهاية المطلوب في yfinance (#226)، وJSON صارم لمقاييس run-card غير المنتهية (#238)، وتغطية إعادة محاولة ddgs (#239)
- @BillDin — عرض حالة وكيل swarm في واجهة الدردشة (#188)، ومعالجة أسماء preset الصريحة (#189)، وأداة بيانات السوق المعتمدة على المحمّل لعمّال swarm (#199)، واستمرارية سياق preset (#200)
- @Robin1987China — جسر الفرضية-الهدف لـ Research Autopilot (#260)، ومحمّل بيانات CSV/Parquet/DuckDB المحلي (#252)، وإصلاح assistant-prefill + User-Agent قابل للضبط لـ Kimi (#248)
- @LemonCANDY42 — لوحة حالة وقت التشغيل للقراءة فقط (#210)، وحفظ منتجات استخدام AgentLoop (#223)، وحمولات مخططات Run Detail الاختيارية (#225)
- @zwrong — إعادة هيكلة trace.jsonl بلا اقتطاع + offload (#206)، وعرض session-id عند الخروج + `resume <session-id>` (#218)
- @forge-builder — دليل المساهم بالذكاء الاصطناعي (#173)، ووثائق اختبار OpenClaw MCP للقراءة فقط (#165)
- @skloxo — توطين الواجهة الأمامية بالصينية (zh-CN) (مُعتمد من #217)
- @LeeCQiang — docstrings صينية عبر جميع عوامل Alpha Zoo الـ 452 (#180)
- @KaiLuettmann — نشر صورة GHCR مُسبقة البناء عند الإصدار (#187)
- @ngoanpv — الحفاظ على Gemini thought_signature عبر مسار dict في AgentLoop (#184)
- @ShahNewazKhan — الوصول إلى Ollama المضيف عبر host.docker.internal (#196)
- @sambazhu — مزامنة الواجهة الأمامية لمحاولات الدردشة المكتملة (#236)
- @bhlt — دعم تنسيق رمز baostock الأصلي (#230)
- @octo-patch — ترقية نموذج MiniMax M3 الافتراضي (#162)
- @warren618 / Haozhe Wu — طبقة البيانات العالمية (8 مصادر + 18 أداة بيانات للقراءة فقط)، و10 موصّلات وسطاء SDK، وحزمة alpha compare الكاملة، وإصلاح موثوقية المزوّدين، وfallback متعدد المحركات لـ web_search، وStop تفاعلي + إعادة اتصال SSE، وتكامل الإصدار

</details>

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## إخلاء المسؤولية

Vibe-Trading برنامج للبحث والتداول. ليس نصيحة استثمارية، ولا يحتفظ بأي أموال، ولا يشغّل أي منصة تنفيذ. يحدث التداول فقط عبر قناة وسيط تُصرّح بها صراحةً (مثل Robinhood Agentic Trading)، ضمن الحدود التي تضعها، ويمكنك إيقافه في أي وقت. قدرة التداول عبر الوسيط هذه تجريبية ولم نتحقق منها على حساب وسيط حقيقي — استخدمها على مسؤوليتك. الأداء السابق لا يضمن النتائج المستقبلية.

## الرخصة

رخصة MIT — راجع [LICENSE](LICENSE)

---

<p align="center" dir="rtl">
  ⭐ إذا ساعدك <b>Vibe-Trading</b> في بحثك، فإن منح نجمة يساعد المزيد على اكتشافه.
</p>

---

<p align="center">
  شكراً لزيارة <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
