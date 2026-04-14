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
  <img src="https://img.shields.io/badge/Skills-69-orange" alt="المهارات">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="السرب">
  <img src="https://img.shields.io/badge/Tools-21-0F766E" alt="الأدوات">
  <img src="https://img.shields.io/badge/Data_Sources-5-2563EB" alt="مصادر البيانات">
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

- **2026-04-13** 🌐 **الاختبار الرجعي المركب عبر الأسواق**: محرك `CompositeEngine` الجديد يتيح اختبار محافظ تشمل أسواقاً مختلفة (مثل أسهم A + العملات المشفرة) في تشغيل واحد مع **مجمع رأسمال مشترك**. قواعد كل سوق (T+1، رسوم التمويل، المقايضة) تُطبق لكل رمز، الإشارات تُحاذى وفق التقويم التجاري لكل رمز. استخدم `source: "auto"` مع رموز مختلطة مثل `["000001.SZ", "BTC-USDT"]`.
- **2026-04-11** 🛡️ **الموثوقية وتجربة المطور**: إعداد تفاعلي لملف `.env` عبر `vibe-trading init` ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19))، فحوصات بدء التشغيل المسبقة لمصادر البيانات ونماذج اللغة، بديل تلقائي لمصدر البيانات عند إرجاع المصدر الأساسي لنتائج فارغة، تعزيز محرك الاختبار الرجعي مع التحقق من البيانات وعزل الأخطاء، حقن سياق التاريخ/الوقت في أوامر الوكيل والسرب. ملف README متعدد اللغات (zh/ja/ko) عبر طلب سحب المجتمع [#21](https://github.com/HKUDS/Vibe-Trading/pull/21).
- **2026-04-10** 📦 **الإصدار v0.1.4**: إصلاح بناء Docker ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8))، إضافة أداة MCP `web_search` (17 إجمالاً)، `akshare`/`ccxt` في التبعيات وMCP. 11 مزود لنماذج اللغة (DeepSeek, Groq, Gemini, Ollama, إلخ)، جميع معلمات الضبط عبر `.env`. تعزيز مهارة `ml-strategy`. النشر على PyPI وClawHub.
- **2026-04-09** 📊 **الموجة الثانية من الاختبار الرجعي — محركات متعددة الأصول**: إضافة العقود الآجلة الصينية (CFFEX/SHFE/DCE/ZCE، 50+ عقد)، العقود الآجلة العالمية (CME/ICE/Eurex، 30+ عقد)، الفوركس (24 زوجاً، السبريد + المقايضة)، الخيارات v2 (الممارسة الأمريكية، ابتسامة التقلب الضمني). التحقق الإحصائي: اختبار التبديل مونت كارلو، فاصل ثقة شارب bootstrap، تحليل المشي للأمام.
- **2026-04-08** 🔧 **الاختبار الرجعي متعدد الأسواق** مع قواعد خاصة بكل سوق؛ **تصدير Pine Script v6** لـ TradingView. **توسيع مصادر البيانات**: 5 مصادر مع بديل تلقائي، أداة `web_search`، تصنيف المهارات (7 فئات).
- **2026-04-01** 🚀 **الإصدار v0.1.0** — الإصدار الأولي: وكيل ReAct، 64 مهارة، 29 إعداد مسبق للسرب، اختبار رجعي عبر الأسواق، CLI + واجهة ويب + خادم MCP.

---

## 💡 ما هو Vibe-Trading؟

Vibe-Trading هو مساحة عمل مالية متعددة الوكلاء مدعومة بالذكاء الاصطناعي تحول الطلبات بلغة طبيعية إلى استراتيجيات تداول قابلة للتنفيذ ورؤى بحثية وتحليل محافظ عبر الأسواق العالمية.

### القدرات الرئيسية:
• **توليد الاستراتيجيات** — كتابة أكواد التداول تلقائياً من أفكارك<br>
• **الوصول الذكي للبيانات** — 5 مصادر بيانات مع بديل تلقائي؛ بدون إعدادات لجميع الأسواق<br>
• **اختبار الأداء** — اختبار استراتيجياتك مقابل بيانات السوق التاريخية<br>
• **تصدير TradingView** — تحويل الاستراتيجيات إلى Pine Script v6 بنقرة واحدة لـ TradingView<br>
• **فرق الخبراء** — نشر وكلاء ذكاء اصطناعي متخصصين لمهام البحث المعقدة<br>
• **تحديثات مباشرة** — مشاهدة عملية التحليل بأكملها في الوقت الفعلي

---

## ✨ الميزات الرئيسية

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="البحث"/><br>
      <h3>🔍 بحث عميق للتداول</h3>
      <img src="https://img.shields.io/badge/69_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="المهارات" /><br><br>
      <div align="left" style="font-size: 4px;">
        • تغطية تحليل متعددة المجالات عبر الأسواق<br>
        • توليد تلقائي للاستراتيجيات والإشارات<br>
        • بحث ورؤى اقتصادية كلية<br>
        • توجيه المهام بلغة طبيعية عبر الدردشة
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="السرب"/><br>
      <h3>🐝 ذكاء السرب</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="السرب" /><br><br>
      <div align="left">
        • 29 إعداد مسبق لفرق التداول الجاهزة<br>
        • تنسيق متعدد الوكلاء قائم على DAG<br>
        • لوحة معلومات تدفق القرارات في الوقت الفعلي<br>
        • بناء فرق مخصصة عبر YAML
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

## 69 مهارة عبر 7 فئات

- 📊 69 مهارة مالية متخصصة منظمة في 7 فئات
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

يقدم Vibe-Trading 17 أداة MCP لأي عميل متوافق مع MCP. يعمل كعملية فرعية stdio — بدون إعداد خادم. **16 من 17 أداة تعمل بدون مفاتيح API** (HK/US/العملات المشفرة). فقط `run_swarm` يحتاج إلى مفتاح نموذج لغة.

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

**أدوات MCP المتاحة (17):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`.

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
│   ├── mcp_server.py               # خادم MCP — 17 أداة لـ OpenClaw / Claude Desktop
│   │
│   ├── src/
│   │   ├── agent/                  # نواة وكيل ReAct
│   │   │   ├── loop.py             #   حلقة الاستدلال الرئيسية
│   │   │   ├── skills.py           #   محمل المهارات (69 ملف SKILL.md، 7 فئات)
│   │   │   ├── tools.py            #   تنسيق الأدوات
│   │   │   ├── context.py          #   منشئ موجه النظام
│   │   │   ├── memory.py           #   ذاكرة التشغيل / تخزين القطع الأثرية
│   │   │   └── trace.py            #   كاتب أثر التنفيذ
│   │   │
│   │   ├── tools/                  # 21 أداة وكيل
│   │   │   ├── backtest_tool.py    #   تشغيل الاختبارات الرجعية
│   │   │   ├── factor_analysis_tool.py
│   │   │   ├── options_pricing_tool.py
│   │   │   ├── pattern_tool.py     #   اكتشاف أنماط الرسم البياني
│   │   │   ├── doc_reader_tool.py  #   قارئ PDF (بديل OCR)
│   │   │   ├── web_reader_tool.py  #   قارئ صفحات الويب (Jina)
│   │   │   ├── web_search_tool.py  #   بحث ويب DuckDuckGo
│   │   │   ├── swarm_tool.py       #   إطلاق فرق السرب
│   │   │   └── ...                 #   إدخال/إخراج ملف، bash، مهام، إلخ
│   │   │
│   │   ├── skills/                 # 69 مهارة مالية في 7 فئات (SKILL.md لكل منها)
│   │   ├── swarm/                  # محرك تنفيذ DAG للسرب
│   │   ├── session/                # إدارة جلسات الدردشة متعددة الأدوار
│   │   └── providers/              # تجريد مزود نموذج اللغة
│   │
│   ├── backtest/                   # محركات الاختبار الرجعي
│   │   ├── engines/                #   7 محركات + محرك مركب عبر الأسواق + options_portfolio
│   │   ├── loaders/                #   5 مصادر: tushare, okx, yfinance, akshare, ccxt
│   │   │   ├── base.py             #   بروتوكول DataLoader
│   │   │   └── registry.py         #   السجل + سلاسل البديل التلقائي
│   │   └── optimizers/             #   MVO، تساوي التقلب، أقصى تنويع، تكافؤ المخاطر
│   │
│   └── config/swarm/               # 29 تعريف YAML للإعدادات المسبقة للسرب
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
| **التحليل والتصور** | سطح التقلب للخيارات والمتغيرات اليونانية مع تصور ثلاثي الأبعاد | مخطط |
| | خريطة حرارة الارتباط عبر الأصول مع نافذة متدحرجة وتجميع | مخطط |
| | مقارنة المعيار في مخرجات الاختبار الرجعي لـ CLI | مخطط |
| | نسبة كالمار ونسبة أوميغا في مقاييس الاختبار الرجعي | مخطط |
| **المهارات والإعدادات المسبقة** | مهارة تحليل الأرباح | مخطط |
| | إعداد سرب مسبق للاستثمار المستدام / ESG | مخطط |
| | إعداد سرب مسبق لمكتب بحث الأسواق الناشئة | مخطط |
| **المحافظ والتحسين** | محسّن محافظ متقدم: الرافعة المالية، حدود القطاعات، قيود التداول | مخطط |
| **المستقبل** | درس تمهيدي: "اختبار رجعي بلغة طبيعية في 5 دقائق" | مخطط |
| | بث بيانات مباشر عبر WebSocket | قيد الاستكشاف |
| | سوق الاستراتيجيات (مشاركة واكتشاف) | قيد الاستكشاف |

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

<p align="center">
  شكراً لزيارتك <b>Vibe-Trading</b> ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="الزوار"/>
</p>
