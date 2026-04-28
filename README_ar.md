<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <b>العربية</b>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="شعار Vibe-Trading"/>
</p>

<h1 align="center">Vibe-Trading: وكيل التداول الشخصي الخاص بك</h1>

<p align="center">
  <b>أمر واحد لتمكين وكيلك بقدرات تداول شاملة</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="الرخصة"></a>
  <br>
  <img src="https://img.shields.io/badge/Skills-72-orange" alt="المهارات">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="السرب">
  <img src="https://img.shields.io/badge/Tools-27-0F766E" alt="الأدوات">
  <img src="https://img.shields.io/badge/Data_Sources-6-2563EB" alt="مصادر البيانات">
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-أحدث-الأخبار">الأخبار</a> &nbsp;&middot;&nbsp;
  <a href="#-ما-هو-vibe-trading">ما هو</a> &nbsp;&middot;&nbsp;
  <a href="#-الميزات-الرئيسية">الميزات</a> &nbsp;&middot;&nbsp;
  <a href="#-البدء-السريع">البدء</a> &nbsp;&middot;&nbsp;
  <a href="#-مرجع-سطر-الأوامر">CLI</a> &nbsp;&middot;&nbsp;
  <a href="#-خادم-api">API</a> &nbsp;&middot;&nbsp;
  <a href="#-إضافة-mcp">MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-هيكل-المشروع">الهيكل</a> &nbsp;&middot;&nbsp;
  <a href="#-خارطة-الطريق">خارطة الطريق</a> &nbsp;&middot;&nbsp;
  <a href="#المساهمة">المساهمة</a> &nbsp;&middot;&nbsp;
  <a href="#المساهمون">المساهمون</a>
</p>

<p align="center">
  <a href="#-البدء-السريع"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 أحدث الأخبار

- **2026-04-28** 🚀 **إصدار v0.1.6** (`pip install -U vibe-trading-ai`): إصلاح إرجاع `vibe-trading --swarm-presets` فارغًا بعد `pip install` / `uv tool install` ([#55](https://github.com/HKUDS/Vibe-Trading/issues/55)) — ملفات YAML للإعدادات المسبقة الآن مضمّنة داخل حزمة `src.swarm` ومثبّتة بـ 6 اختبارات انحدار. إضافة إلى ذلك، محمّل AKShare يوجّه الآن صناديق ETF (`510300.SH`) والعملات الأجنبية (`USDCNH`) إلى نقاط النهاية الصحيحة مع تعزيز سلسلة البديل. تجميع كل التحديثات منذ v0.1.5: لوحة مقارنة المرجع، تدفق `/upload` + حدود الحجم، محمّل Futu (HK + أسهم A)، مهارة تصدير vnpy، تصليب أمني، التحميل الكسول للواجهة (688KB → 262KB).
- **2026-04-27** 📊 **لوحة مقارنة المرجع + أمان الرفع**: مخرجات الاختبار الخلفي تشمل الآن لوحة مقارنة مرجعية (الرمز / عائد المرجع / العائد الفائض / نسبة المعلومات) مع الحلّ عبر yfinance لـ SPY و CSI 300 وغيرها ([#48](https://github.com/HKUDS/Vibe-Trading/issues/48)). إضافة إلى ذلك، نقطة `/upload` تتدفق جسم الطلب في أجزاء 1 ميغابايت وتتوقف فور تجاوز `MAX_UPLOAD_SIZE` مع تنظيف الملف الجزئي، بما يجعل حد 50 ميغابايت فعالاً تحت الطلبات الخبيثة/الضخمة ([#53](https://github.com/HKUDS/Vibe-Trading/pull/53)) — مثبّت بـ 4 اختبارات انحدار.
- **2026-04-22** 🛡️ **تصليب + تكاملات جديدة**: فرض احتواء المسار في `safe_path` + عزل أدوات سجل التداول/حساب الظل، إضافة `MANIFEST.in` لتضمين `.env.example` / الاختبارات / ملفات Docker في sdist، التحميل الكسول على مستوى المسار يقلّص حزمة الواجهة الأولية من 688KB إلى 262KB. إضافة محمّل بيانات Futu لأسهم هونغ كونغ وA ([#47](https://github.com/HKUDS/Vibe-Trading/pull/47)) ومهارة تصدير vnpy CtaTemplate ([#46](https://github.com/HKUDS/Vibe-Trading/pull/46)).

<details>
<summary>أخبار سابقة</summary>

- **2026-04-21** 🛡️ **مساحة العمل + الوثائق**: تطبيع `run_dir` النسبي إلى دليل التشغيل النشط ([#43](https://github.com/HKUDS/Vibe-Trading/pull/43)). إضافة أمثلة استخدام إلى README ([#45](https://github.com/HKUDS/Vibe-Trading/pull/45)).
- **2026-04-20** 🔌 **نماذج التفكير + إصلاحات Swarm**: الحفاظ على `reasoning_content` عبر جميع مسارات تسلسل `ChatOpenAI` — يعمل Kimi / DeepSeek / Qwen thinking من البداية إلى النهاية ([#39](https://github.com/HKUDS/Vibe-Trading/issues/39)). تدفق Swarm + إيقاف نظيف بـ Ctrl+C ([#42](https://github.com/HKUDS/Vibe-Trading/issues/42)).
- **2026-04-19** 📦 **v0.1.5**: تم النشر على PyPI وClawHub. رفع حد `python-multipart` لسد ثغرة CVE، ربط 5 أدوات MCP جديدة (`analyze_trade_journal` + 4 أدوات حساب الظل)، إصلاح عدم تطابق اسم السجل `pattern_recognition` → `pattern`، مزامنة تبعيات Docker، مزامنة بيان SKILL (22 أداة MCP / 71 مهارة).
- **2026-04-18** 👥 **حساب الظل Shadow Account**: استخرج قواعد إستراتيجيتك من سجل التداول الخاص بك → اختبر الظل عبر الأسواق → تقرير HTML/PDF من 8 أقسام يوضح بدقة أين فقدت المال (خرق القواعد، الخروج المبكر، الإشارات المفقودة، الصفقات العكسية). 4 أدوات جديدة، مهارة واحدة جديدة، إجمالي 32 أداة. أمثلة Trade Journal / Shadow Account متاحة الآن في شاشة الترحيب على واجهة الويب.
- **2026-04-17** 📊 **محلل سجل التداول + قارئ ملفات عالمي**: حمّل سجلات التداول من الوسطاء (同花顺/东财/富途/CSV عام) → ملف تعريف تداول تلقائي (أيام الاحتفاظ، معدل الفوز، نسبة الربح/الخسارة، أقصى تراجع) + تشخيص 4 تحيزات سلوكية (تأثير التصرف، الإفراط في التداول، مطاردة الزخم، التثبيت السعري). `read_document` يوزّع الآن PDF وWord وExcel وPowerPoint والصور (OCR) و40+ صيغة نصية خلف استدعاء موحد.
- **2026-04-16** 🧠 **هيكل الوكيل**: ذاكرة دائمة عبر الجلسات، بحث جلسات FTS5، مهارات ذاتية التطور (CRUD كامل)، ضغط سياق 5 طبقات، معالجة أدوات القراءة/الكتابة دفعة واحدة. 27 أداة، 107 اختبار جديد.
- **2026-04-15** 🤖 **Z.ai + MiniMax**: إضافة مزود Z.ai ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35))، إصلاح temperature وتحديث نموذج MiniMax ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33)). 13 مزوداً.
- **2026-04-14** 🔧 **استقرار MCP**: إصلاح خطأ `Connection closed` في أداة الاختبار الرجعي عبر نقل stdio ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32)).
- **2026-04-13** 🌐 **الاختبار الرجعي المركب عبر الأسواق**: محرك `CompositeEngine` الجديد لاختبار محافظ متعددة الأسواق (مثل أسهم A + العملات المشفرة) بمجمع رأسمال مشترك. إصلاح متغيرات قوالب Swarm ومهلة الواجهة الأمامية.
- **2026-04-12** 🌍 **تصدير متعدد المنصات**: أمر `/pine` يصدّر إلى TradingView (Pine Script v6) وTDX (通达信/同花顺/东方财富) وMetaTrader 5 (MQL5) دفعة واحدة.
- **2026-04-11** 🛡️ **الموثوقية وDX**: إعداد `.env` عبر `vibe-trading init` ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19))، فحوصات مسبقة، بديل تلقائي لمصادر البيانات، تعزيز محرك الاختبار الرجعي. README متعدد اللغات ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21)).
- **2026-04-10** 📦 **v0.1.4**: إصلاح Docker ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8))، أداة MCP `web_search`، 12 مزود LLM، تبعيات `akshare`/`ccxt`. النشر على PyPI وClawHub.
- **2026-04-09** 📊 **الموجة الثانية من الاختبار الرجعي**: محركات ChinaFutures وGlobalFutures وForex وOptions v2. تحقق مونت كارلو وBootstrap CI وWalk-Forward.
- **2026-04-08** 🔧 **اختبار رجعي متعدد الأسواق**: قواعد خاصة بكل سوق، تصدير Pine Script v6، 5 مصادر بيانات مع بديل تلقائي.

</details>

---

## 💡 ما هو Vibe-Trading؟

Vibe-Trading هو مساحة عمل مالية متعددة الوكلاء مدعومة بالذكاء الاصطناعي تحول الطلبات بلغة طبيعية إلى استراتيجيات تداول قابلة للتنفيذ ورؤى بحثية وتحليل محافظ عبر الأسواق العالمية.

### القدرات الرئيسية:
• **لغة طبيعية → استراتيجية** — صِف فكرتك؛ الوكيل يكتب الكود ويختبره ويصدّره<br>
• **6 مصادر بيانات، بدون إعداد** — أسهم A، HK/US، العملات المشفرة، العقود الآجلة، الفوركس مع بديل تلقائي<br>
• **29 فريق خبراء** — سير عمل سرب متعدد الوكلاء للاستثمار والتداول وإدارة المخاطر<br>
• **ذاكرة عبر الجلسات** — يتذكر التفضيلات والرؤى؛ ينشئ ويطور المهارات القابلة لإعادة الاستخدام<br>
• **7 محركات اختبار رجعي** — اختبار مركب عبر الأسواق + تحقق إحصائي + 4 محسّنات<br>
• **تصدير متعدد المنصات** — نقرة واحدة إلى TradingView وTDX وMetaTrader 5

---

## ✨ الميزات الرئيسية

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="البحث"/><br>
      <h3>🔍 بحث عميق للتداول</h3>
      <img src="https://img.shields.io/badge/72_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="المهارات" /><br><br>
      <div align="left" style="font-size: 4px;">
        • 72 مهارة متخصصة مع ذاكرة دائمة عبر الجلسات<br>
        • تطور ذاتي: الوكيل ينشئ ويحسّن سير العمل من التجربة<br>
        • ضغط سياق 5 طبقات — بلا فقدان معلومات في المحادثات الطويلة<br>
        • توجيه المهام بلغة طبيعية عبر جميع المجالات المالية
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="السرب"/><br>
      <h3>🐝 ذكاء السرب</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="السرب" /><br><br>
      <div align="left">
        • 29 إعداد مسبق لفرق التداول الجاهزة<br>
        • تنسيق متعدد الوكلاء قائم على DAG<br>
        • لوحة معلومات بث مباشر مع حالة الوكلاء الحية<br>
        • بحث FTS5 عبر الجلسات في جميع المحادثات السابقة
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-backtest.png" height="150" alt="الاختبار الرجعي"/><br>
      <h3>📊 اختبار رجعي عبر الأسواق</h3>
      <img src="https://img.shields.io/badge/5_Data_Sources-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="الاختبار الرجعي" /><br><br>
      <div align="left">
        • أسهم A، أسهم HK/US، العملات المشفرة، العقود الآجلة والفوركس<br>
        • 7 محركات سوق: أسهم A، أسهم US/HK، العملات المشفرة، العقود الآجلة الصينية، العقود الآجلة العالمية، الفوركس<br>
        • التحقق الإحصائي: مونت كارلو، Bootstrap CI، المشي للأمام<br>
        • 15+ مقياس أداء و4 محسّنات
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-quant.png" height="150" alt="الكمي"/><br>
      <h3>🧮 أدوات التحليل الكمي</h3>
      <img src="https://img.shields.io/badge/Quant_Tools-C77DFF?style=for-the-badge&logo=wolfram&logoColor=white" alt="الكمي" /><br><br>
      <div align="left">
        • تحليل العامل IC/IR والاختبار الرجعي للشرائح<br>
        • تسعير Black-Scholes وحساب كامل للمتغيرات اليونانية<br>
        • التعرف على الأنماط الفنية واكتشافها<br>
        • تحسين المحافظ عبر MVO/Risk Parity/BL
      </div>
    </td>
  </tr>
</table>

## 72 مهارة عبر 7 فئات

- 📊 72 مهارة مالية متخصصة منظمة في 7 فئات
- 🌐 تغطية شاملة من الأسواق التقليدية إلى العملات المشفرة وDeFi
- 🔬 قدرات شاملة تمتد من مصادر البيانات إلى البحث الكمي

| الفئة | المهارات | أمثلة |
|----------|--------|----------|
| مصدر البيانات | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| الاستراتيجية | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| التحليل | 15 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis` |
| فئة الأصول | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| العملات المشفرة | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| التدفقات | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| الأدوات | 8 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader` |

## 29 إعداد مسبق لفرق وكلاء السرب

- 🏢 29 فرق وكلاء جاهزة للاستخدام
- ⚡ سير عمل مالية مُعدة مسبقاً
- 🎯 إعدادات مسبقة للاستثمار والتداول وإدارة المخاطر

| الإعداد المسبق | سير العمل |
|--------|----------|
| `investment_committee` | مناظرة صعود/هبوط ← مراجعة مخاطر ← قرار مدير المحفظة النهائي |
| `global_equities_desk` | باحث أسهم A + HK/US + العملات المشفرة ← استراتيجي عالمي |
| `crypto_trading_desk` | التمويل/الأساس + التصفية + التدفق ← مدير مخاطر |
| `earnings_research_desk` | أساسي + مراجعة + خيارات ← استراتيجي الأرباح |
| `macro_rates_fx_desk` | أسعار الفائدة + الفوركس + السلع ← مدير محفظة كلية |
| `quant_strategy_desk` | فرز + بحث العوامل ← اختبار رجعي ← تدقيق مخاطر |
| `technical_analysis_panel` | TA كلاسيكي + إيشيموكو + هارمونيك + إليوت + SMC ← إجماع |
| `risk_committee` | السحب + مخاطر الذيل + مراجعة النظام ← موافقة |
| `global_allocation_committee` | أسهم A + عملات مشفرة + HK/US ← تخصيص عبر الأسواق |

<sub>بالإضافة إلى 20+ إعداد مسبق متخصص إضافي — شغّل vibe-trading --swarm-presets لاستكشافها جميعاً.

</sub>

### 🎬 عرض توضيحي

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
<td colspan="2" align="center"><sub>☝️ اختبار رجعي بلغة طبيعية ومناظرة سرب متعدد الوكلاء — واجهة ويب + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 البدء السريع

### تثبيت بسطر واحد (PyPI)

```bash
pip install vibe-trading-ai
```

> **اسم الحزمة مقابل الأوامر:** حزمة PyPI هي `vibe-trading-ai`. بعد التثبيت، ستحصل على ثلاثة أوامر:
>
> | الأمر | الغرض |
> |---------|---------|
> | `vibe-trading` | CLI تفاعلي / TUI |
> | `vibe-trading serve` | تشغيل خادم ويب FastAPI |
> | `vibe-trading-mcp` | بدء خادم MCP (لـ Claude Desktop, OpenClaw, Cursor, إلخ) |

```bash
vibe-trading init              # إعداد تفاعلي لملف .env
vibe-trading                   # تشغيل CLI
vibe-trading serve --port 8899 # تشغيل واجهة الويب
vibe-trading-mcp               # بدء خادم MCP (stdio)
```

### أو اختر مساراً

| المسار | الأنسب لـ | الوقت |
|------|----------|------|
| **A. Docker** | تجربته الآن، بدون إعداد محلي | دقيقتان |
| **B. تثبيت محلي** | التطوير، وصول كامل لـ CLI | 5 دقائق |
| **C. إضافة MCP** | ربطه بوكيلك الحالي | 3 دقائق |
| **D. ClawHub** | أمر واحد، بدون استنساخ | دقيقة واحدة |

### المتطلبات المسبقة

- **مفتاح API لنموذج لغة** من أي مزود مدعوم — أو التشغيل محلياً مع **Ollama** (بدون مفتاح)
- **Python 3.11+** للمسار B
- **Docker** للمسار A

> **مزودو نماذج اللغة المدعومون:** OpenRouter, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama (محلي). راجع `.env.example` للإعدادات.

> **نصيحة:** جميع الأسواق تعمل بدون أي مفاتيح API بفضل البديل التلقائي. yfinance (HK/US) و OKX (العملات المشفرة) و AKShare (أسهم A، US، HK، العقود الآجلة، الفوركس) جميعها مجانية. رمز Tushare اختياري — AKShare يغطي أسهم A كبديل مجاني.

### المسار A: Docker (بدون إعداد)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# عدّل agent/.env — أزل التعليق عن مزود نموذج اللغة وحدد مفتاح API
docker compose up --build
```

افتح `http://localhost:8899`. الخلفية + الواجهة الأمامية في حاوية واحدة.

### المسار B: التثبيت المحلي

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# التفعيل
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # عدّل — حدد مفتاح API لمزود نموذج اللغة
vibe-trading                       # تشغيل TUI التفاعلي
```

<details>
<summary><b>تشغيل واجهة الويب (اختياري)</b></summary>

```bash
# الطرفية 1: خادم API
vibe-trading serve --port 8899

# الطرفية 2: خادم تطوير الواجهة الأمامية
cd frontend && npm install && npm run dev
```

افتح `http://localhost:5899`. تعيد الواجهة الأمامية توجيه استدعاءات API إلى `localhost:8899`.

**وضع الإنتاج (خادم واحد):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # يخدم FastAPI مجلد dist/ كملفات ثابتة
```

</details>

### المسار C: إضافة MCP

راجع قسم [إضافة MCP](#-إضافة-mcp) أدناه.

### المسار D: ClawHub (أمر واحد)

```bash
npx clawhub@latest install vibe-trading --force
```

يتم تنزيل المهارة + إعدادات MCP إلى مجلد مهارات وكيلك. راجع [تثبيت ClawHub](#-إضافة-mcp) للتفاصيل.

---

## 🧠 متغيرات البيئة

انسخ `agent/.env.example` إلى `agent/.env` وأزل التعليق عن كتلة المزود التي تريدها. كل مزود يحتاج إلى 3-4 متغيرات:

| المتغير | مطلوب | الوصف |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | نعم | اسم المزود (`openrouter`, `deepseek`, `groq`, `z.ai`, `ollama`, إلخ) |
| `<PROVIDER>_API_KEY` | نعم* | مفتاح API (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, إلخ) |
| `<PROVIDER>_BASE_URL` | نعم | رابط نقطة نهاية API |
| `LANGCHAIN_MODEL_NAME` | نعم | اسم النموذج (مثلاً `deepseek/deepseek-v3.2`) |
| `TUSHARE_TOKEN` | لا | رمز Tushare Pro لبيانات أسهم A (بديل AKShare) |
| `TIMEOUT_SECONDS` | لا | مهلة استدعاء نموذج اللغة، الافتراضي 120 ثانية |

<sub>* Ollama لا يتطلب مفتاح API.</sub>

**بيانات مجانية (بدون مفتاح):** أسهم A عبر AKShare، أسهم HK/US عبر yfinance، العملات المشفرة عبر OKX، 100+ بورصة عملات مشفرة عبر CCXT. يختار النظام تلقائياً أفضل مصدر متاح لكل سوق.

### 🎯 النماذج الموصى بها

Vibe-Trading وكيل يعتمد بكثافة على استدعاءات الأدوات — المهارات والاختبار الخلفي والذاكرة و swarm كلها تعمل عبر tool calls. اختيار النموذج يحدد مباشرة ما إذا كان الوكيل **يستخدم أدواته فعلاً** أو يلفّق الإجابات من بيانات التدريب.

| المستوى | أمثلة | متى يُستخدم |
|---------|-------|-------------|
| **الأفضل** | `anthropic/claude-opus-4.7`، `anthropic/claude-sonnet-4.6`، `openai/gpt-5.4`، `google/gemini-3.1-pro-preview` | swarm معقد (3+ وكلاء)، جلسات بحث طويلة، تحليل بمستوى ورقة علمية |
| **نقطة مثلى** (افتراضي) | `deepseek/deepseek-v3.2`، `x-ai/grok-4.20`، `z-ai/glm-5.1`، `moonshotai/kimi-k2.5`، `qwen/qwen3-max-thinking` | الاستخدام اليومي — tool-calling موثوق بحوالي 1/10 من التكلفة |
| **تجنّب كوكيل** | `*-nano`، `*-flash-lite`، `*-coder-next`، إصدارات صغيرة / مُقطّرة | tool-calling غير موثوق — سيبدو الوكيل وكأنه "يجيب من الذاكرة" بدلاً من تحميل المهارات أو تشغيل الاختبار الخلفي |

يأتي `agent/.env.example` الافتراضي مع `deepseek/deepseek-v3.2` — الخيار الأرخص في مستوى النقطة المثلى.

---

## 🖥 مرجع سطر الأوامر

```bash
vibe-trading               # TUI تفاعلي
vibe-trading run -p "..."  # تشغيل واحد
vibe-trading serve         # خادم API
```

<details>
<summary><b>أوامر الشرطة المائلة داخل TUI</b></summary>

| الأمر | الوصف |
|---------|-------------|
| `/help` | عرض جميع الأوامر |
| `/skills` | عرض جميع مهارات التداول الـ 69 |
| `/swarm` | عرض إعدادات فرق السرب الـ 29 |
| `/swarm run <preset> [vars_json]` | تشغيل فريق سرب مع بث مباشر |
| `/swarm list` | سجل تشغيلات السرب |
| `/swarm show <run_id>` | تفاصيل تشغيل السرب |
| `/swarm cancel <run_id>` | إلغاء سرب قيد التشغيل |
| `/list` | التشغيلات الأخيرة |
| `/show <run_id>` | تفاصيل التشغيل + المقاييس |
| `/code <run_id>` | كود الاستراتيجية المولّدة |
| `/pine <run_id>` | Pine Script لـ TradingView |
| `/trace <run_id>` | إعادة تشغيل التنفيذ الكاملة |
| `/continue <run_id> <prompt>` | متابعة تشغيل بتعليمات جديدة |
| `/sessions` | عرض جلسات الدردشة |
| `/settings` | عرض إعدادات التشغيل |
| `/clear` | مسح الشاشة |
| `/quit` | الخروج |

</details>

<details>
<summary><b>التشغيل الفردي والعلامات</b></summary>

```bash
vibe-trading run -p "اختبر استراتيجية BTC-USDT MACD رجعياً، آخر 30 يوماً"
vibe-trading run -p "حلل زخم AAPL" --json
vibe-trading run -f strategy.txt
echo "اختبر 000001.SZ RSI رجعياً" | vibe-trading run
```

```bash
vibe-trading -p "طلبك"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"توقعات BTC"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # Pine Script لـ TradingView
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "حسّن الاستراتيجية"
vibe-trading --upload report.pdf
```

</details>

---

## 🌐 خادم API

```bash
vibe-trading serve --port 8899
```

| الطريقة | نقطة النهاية | الوصف |
|--------|----------|-------------|
| `GET` | `/runs` | عرض التشغيلات |
| `GET` | `/runs/{run_id}` | تفاصيل التشغيل |
| `GET` | `/runs/{run_id}/pine` | تصدير Pine Script |
| `POST` | `/sessions` | إنشاء جلسة |
| `POST` | `/sessions/{id}/messages` | إرسال رسالة |
| `GET` | `/sessions/{id}/events` | بث أحداث SSE |
| `POST` | `/upload` | رفع PDF/ملف |
| `GET` | `/swarm/presets` | عرض إعدادات السرب |
| `POST` | `/swarm/runs` | بدء تشغيل سرب |
| `GET` | `/swarm/runs/{id}/events` | بث SSE للسرب |

توثيق تفاعلي: `http://localhost:8899/docs`

---

## 🔌 إضافة MCP

يقدم Vibe-Trading 22 أداة MCP لأي عميل متوافق مع MCP. يعمل كعملية فرعية stdio — بدون إعداد خادم. **21 من 22 أداة تعمل بدون مفاتيح API** (HK/US/العملات المشفرة). فقط `run_swarm` يحتاج إلى مفتاح نموذج لغة.

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
<summary><b>Cursor / Windsurf / عملاء MCP الآخرين</b></summary>

```bash
vibe-trading-mcp                  # stdio (الافتراضي)
vibe-trading-mcp --transport sse  # SSE لعملاء الويب
```

</details>

**أدوات MCP المتاحة (22):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `analyze_trade_journal`, `extract_shadow_strategy`, `run_shadow_backtest`, `render_shadow_report`, `scan_shadow_signals`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

<details>
<summary><b>التثبيت من ClawHub (أمر واحد)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` مطلوب لأن المهارة تشير إلى واجهات برمجية خارجية، مما يؤدي إلى فحص تلقائي من VirusTotal. الكود مفتوح المصدر بالكامل وآمن للفحص.

هذا ينزّل المهارة + إعدادات MCP إلى مجلد مهارات وكيلك. بدون الحاجة للاستنساخ.

تصفح على ClawHub: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — مهارات ذاتية التطور</b></summary>

جميع مهارات التداول الـ 69 منشورة على [open-space.cloud](https://open-space.cloud) وتتطور بشكل مستقل عبر محرك التطور الذاتي من OpenSpace.

للاستخدام مع OpenSpace، أضف خادمي MCP إلى إعدادات وكيلك:

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

سيكتشف OpenSpace تلقائياً جميع المهارات الـ 69، مما يتيح الإصلاح التلقائي والتحسين التلقائي والمشاركة المجتمعية. ابحث عن مهارات Vibe-Trading عبر `search_skills("finance backtest")` في أي وكيل متصل بـ OpenSpace.

</details>

---

## 📁 هيكل المشروع

<details>
<summary><b>انقر للتوسيع</b></summary>

```
Vibe-Trading/
├── agent/                          # الخلفية (Python)
│   ├── cli.py                      # نقطة دخول CLI — TUI تفاعلي + أوامر فرعية
│   ├── api_server.py               # خادم FastAPI — تشغيلات، جلسات، رفع، سرب، SSE
│   ├── mcp_server.py               # خادم MCP — 22 أداة لـ OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # نواة وكيل ReAct
│   │   │   ├── loop.py             #   ضغط 5 طبقات + معالجة أدوات القراءة/الكتابة دفعة واحدة
│   │   │   ├── context.py          #   موجه النظام + استرجاع تلقائي من الذاكرة الدائمة
│   │   │   ├── skills.py           #   محمل المهارات (69 مدمجة + إنشاء CRUD من المستخدم)
│   │   │   ├── tools.py            #   فئة الأدوات الأساسية + السجل
│   │   │   ├── memory.py           #   حالة مساحة عمل خفيفة لكل تشغيل
│   │   │   ├── frontmatter.py      #   محلل YAML frontmatter مشترك
│   │   │   └── trace.py            #   كاتب أثر التنفيذ
│   │   │
│   │   ├── memory/                 # ذاكرة دائمة عبر الجلسات
│   │   │   └── persistent.py       #   ذاكرة قائمة على الملفات (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 27 أداة وكيل مكتشفة تلقائياً
│   │   │   ├── backtest_tool.py    #   تشغيل الاختبارات الرجعية
│   │   │   ├── remember_tool.py    #   ذاكرة عبر الجلسات (حفظ/استرجاع/نسيان)
│   │   │   ├── skill_writer_tool.py #  CRUD للمهارات (حفظ/تصحيح/حذف/ملف)
│   │   │   ├── session_search_tool.py # بحث FTS5 عبر الجلسات
│   │   │   ├── swarm_tool.py       #   إطلاق فرق السرب
│   │   │   ├── web_search_tool.py  #   بحث ويب DuckDuckGo
│   │   │   └── ...                 #   bash، إدخال/إخراج ملف، تحليل العوامل، الخيارات، إلخ
│   │   │
│   │   ├── skills/                 # 72 مهارة مالية في 7 فئات (SKILL.md لكل منها)
│   │   ├── swarm/                  # محرك تنفيذ DAG للسرب
│   │   │   └── presets/            #   29 تعريف YAML للإعدادات المسبقة للسرب
│   │   ├── session/                # دردشة متعددة الأدوار + بحث FTS5 عبر الجلسات
│   │   └── providers/              # تجريد مزود نموذج اللغة
│   │
│   └── backtest/                   # محركات الاختبار الرجعي
│       ├── engines/                #   7 محركات + محرك مركب عبر الأسواق + options_portfolio
│       ├── loaders/                #   6 مصادر: tushare, okx, yfinance, akshare, ccxt, futu
│       │   ├── base.py             #   بروتوكول DataLoader
│       │   └── registry.py         #   السجل + سلاسل البديل التلقائي
│       └── optimizers/             #   MVO، تساوي التقلب، أقصى تنويع، تكافؤ المخاطر
│
├── frontend/                       # واجهة الويب (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   الرئيسية، الوكيل، تفاصيل التشغيل، المقارنة
│       ├── components/             #   دردشة، رسوم بيانية، تخطيط
│       └── stores/                 #   إدارة حالة Zustand
│
├── Dockerfile                      # بناء متعدد المراحل
├── docker-compose.yml              # نشر بأمر واحد
├── pyproject.toml                  # إعدادات الحزمة + نقطة دخول CLI
└── LICENSE                         # MIT
```

</details>

---

## 🏛 النظام البيئي

Vibe-Trading هو جزء من النظام البيئي للوكلاء **[HKUDS](https://github.com/HKUDS)**:

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>ذكاء سرب الوكلاء</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>مساعد ذكاء اصطناعي شخصي فائق الخفة</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>جعل جميع البرامج أصلية للوكلاء</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>مهارات وكلاء ذكاء اصطناعي ذاتية التطور</sub>
    </td>
  </tr>
</table>

---

## 🗺 خارطة الطريق

> نشحن على مراحل. تنتقل العناصر إلى [المشكلات](https://github.com/HKUDS/Vibe-Trading/issues) عند بدء العمل.

| المرحلة | الميزة | الحالة |
|-------|---------|--------|
| **هيكل الوكيل** | ذاكرة دائمة عبر الجلسات (حفظ / استرجاع / نسيان) | **تم** |
| | مهارات ذاتية التطور — الوكيل ينشئ ويعدل ويحذف سير العمل بنفسه | **تم** |
| | بحث FTS5 عبر الجلسات في جميع المحادثات السابقة | **تم** |
| | ضغط سياق 5 طبقات (micro → collapse → auto → manual → iterative) | **تم** |
| | معالجة أدوات القراءة/الكتابة دفعة واحدة — تنفيذ موازٍ للأدوات للقراءة فقط | **تم** |
| **التالي** | حلقة بحث مستقلة — الوكيل يكرر الفرضيات طوال الليل | قيد التنفيذ |
| | تكامل المراسلة (Slack / Telegram / WeChat) | مخطط |
| **التحليل والتصور** | سطح التقلب للخيارات والمتغيرات اليونانية مع تصور ثلاثي الأبعاد | مخطط |
| | خريطة حرارة الارتباط عبر الأصول مع نافذة متدحرجة وتجميع | مخطط |
| | مقارنة المعيار في مخرجات الاختبار الرجعي لـ CLI | مخطط |
| **المهارات والإعدادات المسبقة** | مهارة تحليل الأرباح | مخطط |
| | إعداد سرب مسبق للاستثمار المستدام / ESG | مخطط |
| **المحافظ والتحسين** | محسّن محافظ متقدم: الرافعة المالية، حدود القطاعات، قيود التداول | مخطط |
| **المستقبل** | سوق الاستراتيجيات (مشاركة واكتشاف) | قيد الاستكشاف |
| | بث بيانات مباشر عبر WebSocket | قيد الاستكشاف |

---

## المساهمة

نرحب بالمساهمات! راجع [CONTRIBUTING.md](CONTRIBUTING.md) للإرشادات.

**المشكلات الجيدة للمبتدئين** محددة بعلامة [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — اختر واحدة وابدأ.

ترغب في المساهمة بشيء أكبر؟ راجع [خارطة الطريق](#-خارطة-الطريق) أعلاه وافتح مشكلة للمناقشة قبل البدء.

---

## المساهمون

شكراً لكل من ساهم في Vibe-Trading!

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## إخلاء المسؤولية

Vibe-Trading مخصص للبحث والمحاكاة والاختبار الرجعي فقط. وهو ليس نصيحة استثمارية ولا ينفذ صفقات حية. الأداء السابق لا يضمن النتائج المستقبلية.

## الرخصة

رخصة MIT — راجع [LICENSE](LICENSE)

---

## تاريخ النجوم

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/Vibe-Trading&type=Date)](https://star-history.com/#HKUDS/Vibe-Trading&Date)

---

<p align="center">
  شكراً لزيارتك <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="الزوار"/>
</p>
