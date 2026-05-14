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

- **2026-05-14** 🧠 أصبحت الذاكرة الدائمة قابلة للفحص من سطر الأوامر عبر `vibe-trading memory list/show/search/forget` ([#102](https://github.com/HKUDS/Vibe-Trading/pull/102)، شكراً @Teerapat-Vatpitak).
- **2026-05-13** 🧭 أصبحت تشغيلات السرب تؤسس عمل الوكلاء على بيانات سوق مجلوبة مسبقاً، مع تقارير محفوظة أنظف ([#93](https://github.com/HKUDS/Vibe-Trading/pull/93)، [#84](https://github.com/HKUDS/Vibe-Trading/pull/84)).
- **2026-05-12** 🧾 أصبحت الاختبارات الرجعية تنتج `run_card.json` و`run_card.md` إلى جانب المخرجات لدعم تشغيلات بحثية قابلة لإعادة الإنتاج.

<details>
<summary>أخبار سابقة</summary>

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

صُمم للبحث والمحاكاة والاختبار الرجعي. لا ينفذ صفقات حية.

---

## ✨ ما الذي يمكنك فعله؟

| المهمة | الناتج |
|------|--------|
| **طرح سؤال تداول** | بحث سوقي باستخدام الأدوات والبيانات والمستندات وسياق جلسة قابل لإعادة الاستخدام. |
| **اختبار فكرة استراتيجية رجعياً** | كود استراتيجية، ومقاييس، وسياق معياري، ومخرجات تحقق، وبطاقات تشغيل. |
| **مراجعة صفقاتك الخاصة** | قراءة سجلات الوسطاء، وتشخيص السلوك، واستخراج القواعد، ومقارنات Shadow Account. |
| **تحسين الأبحاث المتكررة** | الذاكرة الدائمة والمهارات القابلة للتحرير تحول الروتينات المفيدة إلى تدفقات قابلة لإعادة الاستخدام. |
| **تشغيل فرق محللين** | مراجعات بحث متعددة الوكلاء لتدفقات الاستثمار والكم والكريبتو والماكرو والمخاطر. |
| **إنتاج مخرجات قابلة للاستخدام** | تقارير، وTradingView Pine Script، وTDX، وMetaTrader 5، وأدوات MCP، وجلسات بحث لاحقة. |

---

## ⚡ مثال سريع

```bash
pip install vibe-trading-ai
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"
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

## 🔩 القدرات التفصيلية

القوائم التفصيلية مطوية أدناه حتى يبقى README سهل القراءة. افتحها عندما تريد فحص اللبنات المتاحة.

<details>
<summary><b>مكتبة المهارات المالية</b> <sub>74 مهارة عبر 8 فئات</sub></summary>

- 📊 74 مهارة مالية متخصصة منظمة في 8 فئات
- 🌐 تغطية كاملة من الأسواق التقليدية إلى الكريبتو وDeFi
- 🔬 قدرات شاملة من مصادر البيانات إلى البحث الكمي

| الفئة | المهارات | أمثلة |
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
<summary><b>فرق تداول جاهزة</b> <sub>29 إعداد سرب مسبق</sub></summary>

- 🏢 29 فريق وكلاء جاهزاً للاستخدام
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

> **مزودو LLM المدعومون:** OpenRouter, OpenAI, OpenAI Codex (ChatGPT OAuth), Claude Code (اشتراك Pro/Max), DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama (local). راجع `.env.example` للإعداد.

> **نصيحة:** تعمل كل الأسواق دون مفاتيح API بفضل fallback التلقائي. yfinance (HK/US)، وOKX (crypto)، وAKShare (A-shares, US, HK, futures, forex) مجانية. رمز Tushare اختياري، إذ يغطي AKShare أسهم A كبديل مجاني.

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
| **الأفضل** | `anthropic/claude-opus-4.7`, `anthropic/claude-sonnet-4.6`, `openai/gpt-5.4`, `google/gemini-3.1-pro-preview` | أسراب معقدة (3+ وكلاء)، جلسات بحث طويلة، تحليل بمستوى ورقة علمية |
| **النقطة المثلى** (افتراضي) | `deepseek-v4-pro`, `deepseek/deepseek-v4-pro`, `x-ai/grok-4.20`, `z-ai/glm-5.1`, `moonshotai/kimi-k2.5`, `qwen/qwen3-max-thinking` | الاستخدام اليومي، tool-calling موثوق بنحو عُشر التكلفة |
| **تجنبها لاستخدام الوكيل** | `*-nano`, `*-flash-lite`, `*-coder-next`, small / distilled variants | tool-calling غير موثوق؛ سيبدو الوكيل وكأنه "يجيب من الذاكرة" بدلاً من تحميل المهارات أو تشغيل الاختبارات الرجعية |

يأتي `agent/.env.example` افتراضياً مع DeepSeek official API + `deepseek-v4-pro`; ويمكن لمستخدمي OpenRouter استخدام `deepseek/deepseek-v4-pro`.

---

## 🖥 مرجع CLI

```bash
vibe-trading               # interactive TUI
vibe-trading run -p "..."  # single run
vibe-trading serve         # API server
```

<details>
<summary><b>أوامر الشرطة المائلة داخل TUI</b></summary>

| الأمر | الوصف |
|---------|-------------|
| `/help` | عرض كل الأوامر |
| `/skills` | عرض كل المهارات المالية الـ 74 |
| `/swarm` | عرض إعدادات فرق السرب الـ 29 |
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
| `GET` | `/settings/llm` | قراءة إعدادات LLM في Web UI |
| `PUT` | `/settings/llm` | تحديث إعدادات LLM المحلية |
| `GET` | `/settings/data-sources` | قراءة إعدادات مصادر البيانات المحلية |
| `PUT` | `/settings/data-sources` | تحديث إعدادات مصادر البيانات المحلية |

توثيق تفاعلي: `http://localhost:8899/docs`

### الإعدادات الأمنية الافتراضية

للتطوير على localhost، يبقي `vibe-trading serve` سير المتصفح بسيطاً. لأي عميل غير محلي، تتطلب نقاط API الحساسة `API_AUTH_KEY`؛ استخدم `Authorization: Bearer <key>` لطلبات JSON/الرفع. تتعامل Web UI مع تدفقات Browser EventSource بعد إدخال المفتاح نفسه مرة واحدة في Settings.

تتوفر الأدوات القادرة على shell للـ CLI المحلي وتدفقات localhost الموثوقة، لكنها لا تُعرض لجلسات API البعيدة ما لم تضبط صراحة `VIBE_TRADING_ENABLE_SHELL_TOOLS=1`. قارئات المستندات والسجلات محدودة افتراضياً بجذور الرفع/الاستيراد؛ ضع الملفات تحت `agent/uploads` أو `agent/runs` أو `./uploads` أو `./data` أو `~/.vibe-trading/uploads` أو `~/.vibe-trading/imports`، أو أضف دليلاً مخصصاً عبر `VIBE_TRADING_ALLOWED_FILE_ROOTS`.

### إعدادات Web UI

تتيح صفحة Settings في Web UI للمستخدمين المحليين تحديث مزود/نموذج LLM، وbase URL، ومعلمات التوليد، وreasoning effort، وبيانات اعتماد السوق الاختيارية مثل رمز Tushare. تُحفظ الإعدادات في `agent/.env`؛ وتُحمّل قيم المزودين الافتراضية من `agent/src/providers/llm_providers.json`.

قراءات Settings بلا آثار جانبية: لا تنشئ `GET /settings/llm` ولا `GET /settings/data-sources` ملف `agent/.env`، ولا تعيدان إلا مسارات نسبية للمشروع. قد تكشف قراءات وكتابات Settings حالة بيانات الاعتماد أو تحدث بيانات الاعتماد/بيئة التشغيل، لذلك تتطلب `API_AUTH_KEY` عند ضبطه. إذا كان `API_AUTH_KEY` غير مضبوط في وضع التطوير، فلا يقبل الوصول إلى Settings إلا من عملاء loopback.

---

## 🔌 MCP Plugin

يعرض Vibe-Trading 22 أداة MCP لأي عميل متوافق مع MCP. يعمل كعملية stdio فرعية، دون إعداد خادم. **21 من أصل 22 أداة تعمل دون أي مفاتيح API** (HK/US/crypto). يحتاج `run_swarm` وحده إلى مفتاح LLM.

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

**أدوات MCP المعروضة (22):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

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

كل المهارات المالية الـ 74 منشورة على [open-space.cloud](https://open-space.cloud) وتتطور ذاتياً عبر محرك التطور الذاتي في OpenSpace.

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

سيكتشف OpenSpace كل المهارات الـ 74 تلقائياً، مما يتيح auto-fix وauto-improve والمشاركة المجتمعية. ابحث عن مهارات Vibe-Trading عبر `search_skills("finance backtest")` في أي وكيل متصل بـ OpenSpace.

</details>

---

## 📁 هيكل المشروع

<details>
<summary><b>انقر للتوسيع</b></summary>

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

## 🏛 النظام البيئي

Vibe-Trading جزء من نظام وكلاء **[HKUDS](https://github.com/HKUDS)**:

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

## 🗺 خارطة الطريق

> نشحن على مراحل. تنتقل العناصر إلى [Issues](https://github.com/HKUDS/Vibe-Trading/issues) عندما يبدأ العمل.

| المرحلة | الميزة | الحالة |
|-------|---------|--------|
| **Research Autopilot** | حلقة بحث ليلية: فرضية → جلب بيانات → اختبار رجعي → تقرير أدلة | قيد التنفيذ |
| **Data Bridge** | أحضر بياناتك: موصلات CSV/Parquet/SQL محلية مع schema mapping | مخطط |
| **Options Lab** | سطح تقلب، ولوحة Greeks، ومستكشف payoff/scenario | مخطط |
| **Portfolio Studio** | أشعة مخاطر، وقيود، ومحسن يراعي الدوران، وملاحظات إعادة توازن | مخطط |
| **Alpha Zoo** | مكتبات عوامل Alpha101 / Alpha158 / Alpha191 مع فرز واختبارات IC | مخطط |
| **Research Delivery** | موجزات مجدولة إلى Slack / Telegram / قنوات شبيهة بالبريد | مخطط |
| **Trust Layer** | بطاقات تشغيل قابلة لإعادة الإنتاج: أثر الأدوات، ومصادر البيانات، والافتراضات، والاستشهادات | قيد التنفيذ |
| **Community** | مهارات وإعدادات مسبقة وبطاقات استراتيجية قابلة للمشاركة | قيد الاستكشاف |

---

## المساهمة

نرحب بالمساهمات! راجع [CONTRIBUTING.md](CONTRIBUTING.md) للإرشادات.

**المشكلات الجيدة للمبتدئين** موسومة بـ [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — اختر واحدة وابدأ.

هل تريد المساهمة بشيء أكبر؟ راجع [خارطة الطريق](#-خارطة-الطريق) أعلاه وافتح issue للنقاش قبل البدء.

---

## المساهمون

شكراً لكل من ساهم في Vibe-Trading!

مساهمو واعتمادات دورة v0.1.7 الأخيرة:

- @GTC2080 / TaoMu — Web UI Settings وواجهات إعداد provider/data-source (#57)
- @BigNounce90 — تعزيز validation CLI لمدخل `run_dir` في الاختبار الرجعي (#60)
- @shadowinlife — مهارة A-share pre-ST filter (#63)
- @MB-Ndhlovu — لوحة خريطة الارتباط الحرارية وإصلاحات المراجعة (#64, #66)
- @ykykj — خيار مزود OpenAI Codex OAuth (#65)
- @RuifengFu — شريط حالة CLI التفاعلي وتحرير prompt (#69)
- @SiMinus — أمر فحص swarm preset (#73)
- @warren618 / Haozhe Wu — تعزيز الأمان، وتكامل الإصدار، والوثائق، وDocker، والتغليف، وسير التطوير المحلي
- lemi9090 (S2W) — بحث أمني منسق، وتحقق، ودعم الإفصاح

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## إخلاء المسؤولية

Vibe-Trading مخصص للبحث والمحاكاة والاختبار الرجعي فقط. ليس نصيحة استثمارية ولا ينفذ صفقات حية. الأداء السابق لا يضمن النتائج المستقبلية.

## الرخصة

رخصة MIT — راجع [LICENSE](LICENSE)

---

## تاريخ النجوم

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  شكراً لزيارة <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="visitors"/>
</p>
