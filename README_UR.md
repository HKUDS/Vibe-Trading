<p align="center">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ko.md">한국어</a> | <a href="README_ar.md">العربية</a> | <b>اردو</b>
</p>

<p align="center">
  <img src="assets/icon.png" width="120" alt="Vibe-Trading لوگو"/>
</p>

<h1 align="center">Vibe-Trading: آپ کا ذاتی تجارتی ایجنٹ</h1>

<p align="center">
  <b>ایک کمانڈ سے اپنے ایجنٹ کو جامع تجارتی صلاحیتوں سے لیس کریں</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688?style=flat" alt="FastAPI">
  <img src="https://img.shields.io/badge/Frontend-React%2019-61DAFB?style=flat&logo=react&logoColor=white" alt="React">
  <a href="https://pypi.org/project/vibe-trading-ai/"><img src="https://img.shields.io/pypi/v/vibe-trading-ai?style=flat&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat" alt="لائسنس"></a>
  <br>
  <img src="https://img.shields.io/badge/Skills-71-orange" alt="مہارتیں">
  <img src="https://img.shields.io/badge/Swarm_Presets-29-7C3AED" alt="سوارم">
  <img src="https://img.shields.io/badge/Tools-27-0F766E" alt="اوزار">
  <img src="https://img.shields.io/badge/Data_Sources-5-2563EB" alt="ڈیٹا ذرائع">
  <br>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/Feishu-Group-E9DBFC?style=flat-square&logo=feishu&logoColor=white" alt="Feishu"></a>
  <a href="https://github.com/HKUDS/.github/blob/main/profile/README.md"><img src="https://img.shields.io/badge/WeChat-Group-C5EAB4?style=flat-square&logo=wechat&logoColor=white" alt="WeChat"></a>
  <a href="https://discord.gg/2vDYc2w5"><img src="https://img.shields.io/badge/Discord-Join-7289DA?style=flat-square&logo=discord&logoColor=white" alt="Discord"></a>
</p>

<p align="center">
  <a href="#-تازہ-ترین-خبریں">خبریں</a> &nbsp;&middot;&nbsp;
  <a href="#-vibe-trading-کیا-ہے">کیا ہے</a> &nbsp;&middot;&nbsp;
  <a href="#-اہم-خصوصیات">خصوصیات</a> &nbsp;&middot;&nbsp;
  <a href="#-فوری-آغاز">آغاز</a> &nbsp;&middot;&nbsp;
  <a href="#-cli-حوالہ">CLI</a> &nbsp;&middot;&nbsp;
  <a href="#-api-سرور">API</a> &nbsp;&middot;&nbsp;
  <a href="#-mcp-پلگ-ان">MCP</a> &nbsp;&middot;&nbsp;
  <a href="#-منصوبے-کا-ڈھانچہ">ڈھانچہ</a> &nbsp;&middot;&nbsp;
  <a href="#-راہ-نقشہ">راہ نقشہ</a> &nbsp;&middot;&nbsp;
  <a href="#شراکت">شراکت</a> &nbsp;&middot;&nbsp;
  <a href="#شراکت-داران">شراکت داران</a>
</p>

<p align="center">
  <a href="#-فوری-آغاز"><img src="assets/pip-install.svg" height="45" alt="pip install vibe-trading-ai"></a>
</p>

---

## 📰 تازہ ترین خبریں

- **2026-04-19** 📦 **v0.1.5**: PyPI اور ClawHub پر شائع۔ `python-multipart` CVE فلور بمپ، 5 نئے MCP ٹولز (`analyze_trade_journal` + 4 شیڈو اکاؤنٹ ٹولز)، `pattern_recognition` → `pattern` رجسٹری درستگی، Docker انحصار برابری، SKILL مینی فیسٹ سنک (22 MCP ٹولز / 71 مہارتیں)۔
- **2026-04-18** 👥 **شیڈو اکاؤنٹ**: بروکر جرنل سے اپنے حکمت عملی کے قواعد نکالیں → مارکیٹوں میں شیڈو کا بیک ٹیسٹ → 8 حصوں کی HTML/PDF رپورٹ جو دکھاتی ہے کہ آپ کتنا چھوڑ رہے ہیں (قاعدہ کی خلاف ورزیاں، جلدی اخراج، چھوٹے ہوئے سگنل، متوقع ترین تجارت)۔ 4 نئے ٹولز، 1 مہارت، کل 32 ٹولز۔ ٹریڈ جرنل + شیڈو اکاؤنٹ کے نمونے اب ویب UI کے خیرمقدم اسکرین پر۔
- **2026-04-17** 📊 **ٹریڈ جرنل تجزیہ کار + یونیورسل فائل ریڈر**: بروکر ایکسپورٹ (同花顺/东财/富途/عام CSV) اپ لوڈ کریں → خودکار تجارتی پروفائل (ہولڈنگ دن، جیت کی شرح، PnL تناسب، ڈراڈاؤن) + 4 تعصب تشخیص (تصرف اثر، حد سے زیادہ تجارت، رفتار کا پیچھا، قیمتی لنگر)۔ `read_document` اب PDF، Word، Excel، PowerPoint، تصاویر (OCR) اور 40 سے زیادہ متنی فارمیٹس کو ایک یکجا کال سے پروسیس کرتا ہے۔

<details>
<summary>پرانی خبریں</summary>

- **2026-04-16** 🧠 **ایجنٹ ہارنس**: مستقل کراس سیشن میموری، FTS5 سیشن تلاش، خود ارتقائی مہارتیں (مکمل CRUD)، 5 پرتی سیاق و سباق کمپریشن، پڑھنے/لکھنے کے اوزار بیچنگ۔ 27 اوزار، 107 نئے ٹیسٹ۔
- **2026-04-15** 🤖 **Z.ai + MiniMax**: Z.ai فراہم کنندہ ([#35](https://github.com/HKUDS/Vibe-Trading/pull/35))، MiniMax درجہ حرارت درستگی + ماڈل اپ ڈیٹ ([#33](https://github.com/HKUDS/Vibe-Trading/pull/33))۔ 13 فراہم کنندگان۔
- **2026-04-14** 🔧 **MCP استحکام**: stdio ٹرانسپورٹ پر بیک ٹیسٹ ٹول کی `Connection closed` خرابی درست کی ([#32](https://github.com/HKUDS/Vibe-Trading/pull/32))۔
- **2026-04-13** 🌐 **کراس مارکیٹ مرکب بیک ٹیسٹ**: نئے `CompositeEngine` سے مشترک سرمائے کے ساتھ ملے جلے مارکیٹ پورٹ فولیوز (مثلاً A-شیئرز + کرپٹو) کا بیک ٹیسٹ۔ swarm ٹیمپلیٹ متغیر اور فرنٹ اینڈ ٹائم آؤٹ بھی درست کیے۔
- **2026-04-12** 🌍 **ملٹی پلیٹ فارم برآمد**: `/pine` کمانڈ ایک کمانڈ میں TradingView (Pine Script v6)، TDX (通达信/同花顺/东方财富) اور MetaTrader 5 (MQL5) کو برآمد کرتی ہے۔
- **2026-04-11** 🛡️ **قابل اعتماد اور DX**: `vibe-trading init` سے .env سیٹ اپ ([#19](https://github.com/HKUDS/Vibe-Trading/pull/19))، پری فلائٹ چیک، رن ٹائم ڈیٹا سورس فال بیک، مضبوط بیک ٹیسٹ انجن۔ کثیر زبانی README ([#21](https://github.com/HKUDS/Vibe-Trading/pull/21))۔
- **2026-04-10** 📦 **v0.1.4**: Docker درستگی ([#8](https://github.com/HKUDS/Vibe-Trading/issues/8))، `web_search` MCP ٹول، 12 LLM فراہم کنندگان، `akshare`/`ccxt` انحصارات۔ PyPI اور ClawHub پر شائع۔
- **2026-04-09** 📊 **بیک ٹیسٹ لہر 2**: ChinaFutures، GlobalFutures، Forex، Options v2 انجن۔ Monte Carlo، Bootstrap CI، Walk-Forward تصدیق۔
- **2026-04-08** 🔧 **ملٹی مارکیٹ بیک ٹیسٹ** فی مارکیٹ قواعد، Pine Script v6 برآمد، 5 ڈیٹا سورسز کے ساتھ خودکار فال بیک۔

</details>

---

## 💡 Vibe-Trading کیا ہے؟

Vibe-Trading ایک AI سے چلنے والی ملٹی ایجنٹ مالیاتی ورک اسپیس ہے جو قدرتی زبان کی درخواستوں کو عالمی مارکیٹوں میں قابل عمل تجارتی حکمت عملیوں، تحقیقی بصیرت اور پورٹ فولیو تجزیے میں تبدیل کرتی ہے۔

### اہم صلاحیتیں:
• **قدرتی زبان → حکمت عملی** — اپنا خیال بیان کریں؛ ایجنٹ تجارتی کوڈ لکھتا، جانچتا اور برآمد کرتا ہے<br>
• **5 ڈیٹا سورسز، کوئی ترتیب نہیں** — A-شیئرز، HK/US، کرپٹو، فیوچرز اور فاریکس خودکار فال بیک کے ساتھ<br>
• **29 ماہر ٹیمیں** — سرمایہ کاری، تجارت اور رسک کے لیے پہلے سے تیار ملٹی ایجنٹ سوارم ورک فلوز<br>
• **کراس سیشن میموری** — ترجیحات اور بصیرتیں یاد رکھتا ہے؛ دوبارہ استعمال کے قابل مہارتیں بناتا اور ارتقاء دیتا ہے<br>
• **7 بیک ٹیسٹ انجن** — اعداد و شمار کی تصدیق اور 4 آپٹیمائزرز کے ساتھ کراس مارکیٹ مرکب جانچ<br>
• **ملٹی پلیٹ فارم برآمد** — ایک کلک سے TradingView، TDX (通达信/同花顺) اور MetaTrader 5

---

## ✨ اہم خصوصیات

<table width="100%">
  <tr>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-research.png" height="150" alt="تحقیق"/><br>
      <h3>🔍 تجارت کے لیے ڈیپ ریسرچ</h3>
      <img src="https://img.shields.io/badge/71_Skills-FF6B6B?style=for-the-badge&logo=bookstack&logoColor=white" alt="مہارتیں" /><br><br>
      <div align="left" style="font-size: 4px;">
        • مستقل کراس سیشن میموری کے ساتھ 71 ماہر مہارتیں<br>
        • خود ارتقائی: ایجنٹ تجربے سے ورک فلوز بناتا اور بہتر کرتا ہے<br>
        • 5 پرتی سیاق و سباق کمپریشن — طویل سیشنز میں کوئی معلومات ضائع نہیں<br>
        • تمام مالیاتی ڈومینز میں قدرتی زبان سے ٹاسک روٹنگ
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-swarm.png" height="150" alt="سوارم"/><br>
      <h3>🐝 سوارم انٹیلیجنس</h3>
      <img src="https://img.shields.io/badge/29_Trading_Teams-4ECDC4?style=for-the-badge&logo=hive&logoColor=white" alt="سوارم" /><br><br>
      <div align="left">
        • 29 تیار شدہ تجارتی ٹیم پری سیٹس<br>
        • DAG پر مبنی ملٹی ایجنٹ آرکیسٹریشن<br>
        • لائیو ایجنٹ حیثیت کے ساتھ ریئل ٹائم اسٹریمنگ ڈیش بورڈ<br>
        • تمام پرانی گفتگوؤں میں FTS5 سیشن تلاش
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-backtest.png" height="150" alt="بیک ٹیسٹ"/><br>
      <h3>📊 کراس مارکیٹ بیک ٹیسٹ</h3>
      <img src="https://img.shields.io/badge/5_Data_Sources-FFD93D?style=for-the-badge&logo=bitcoin&logoColor=black" alt="بیک ٹیسٹ" /><br><br>
      <div align="left">
        • A-شیئرز، HK/US ایکویٹیز، کرپٹو، فیوچرز اور فاریکس<br>
        • 7 مارکیٹ انجن + مشترک سرمائے کے ساتھ مرکب کراس مارکیٹ انجن<br>
        • اعداد و شمار کی تصدیق: Monte Carlo، Bootstrap CI، Walk-Forward<br>
        • 15+ کارکردگی میٹرکس اور 4 آپٹیمائزرز
      </div>
    </td>
    <td align="center" width="25%" valign="top">
      <img src="assets/scene-quant.png" height="150" alt="مقداری"/><br>
      <h3>🧮 مقداری تجزیہ ٹول کٹ</h3>
      <img src="https://img.shields.io/badge/Quant_Tools-C77DFF?style=for-the-badge&logo=wolfram&logoColor=white" alt="مقداری" /><br><br>
      <div align="left">
        • فیکٹر IC/IR تجزیہ اور quantile بیک ٹیسٹنگ<br>
        • Black-Scholes قیمت گذاری اور مکمل Greeks حساب<br>
        • تکنیکی پیٹرن پہچان اور شناخت<br>
        • MVO/Risk Parity/BL کے ذریعے پورٹ فولیو آپٹیمائزیشن
      </div>
    </td>
  </tr>
</table>

## 7 زمروں میں 71 مہارتیں

- 📊 7 زمروں میں منظم 71 خصوصی مالیاتی مہارتیں
- 🌐 روایتی مارکیٹوں سے کرپٹو اور DeFi تک مکمل کوریج
- 🔬 ڈیٹا سورسنگ سے مقداری تحقیق تک جامع صلاحیتیں

| زمرہ | مہارتیں | مثالیں |
|----------|--------|----------|
| ڈیٹا سورس | 6 | `data-routing`, `tushare`, `yfinance`, `okx-market`, `akshare`, `ccxt` |
| حکمت عملی | 17 | `strategy-generate`, `cross-market-strategy`, `technical-basic`, `candlestick`, `ichimoku`, `elliott-wave`, `smc`, `multi-factor`, `ml-strategy` |
| تجزیہ | 15 | `factor-research`, `macro-analysis`, `global-macro`, `valuation-model`, `earnings-forecast`, `credit-analysis` |
| اثاثہ کلاس | 9 | `options-strategy`, `options-advanced`, `convertible-bond`, `etf-analysis`, `asset-allocation`, `sector-rotation` |
| کرپٹو | 7 | `perp-funding-basis`, `liquidation-heatmap`, `stablecoin-flow`, `defi-yield`, `onchain-analysis` |
| فلو | 7 | `hk-connect-flow`, `us-etf-flow`, `edgar-sec-filings`, `financial-statement`, `adr-hshare` |
| ٹول | 8 | `backtest-diagnose`, `report-generate`, `pine-script`, `doc-reader`, `web-reader` |

## 29 ایجنٹ سوارم ٹیم پری سیٹس

- 🏢 29 تیار شدہ ایجنٹ ٹیمیں
- ⚡ پہلے سے ترتیب دیے گئے مالیاتی ورک فلوز
- 🎯 سرمایہ کاری، تجارت اور رسک مینجمنٹ پری سیٹس

| پری سیٹ | ورک فلو |
|--------|----------|
| `investment_committee` | تیزی/مندی بحث → رسک جائزہ → PM کا حتمی فیصلہ |
| `global_equities_desk` | A-شیئر + HK/US + کرپٹو محقق → عالمی حکمت کار |
| `crypto_trading_desk` | فنڈنگ/بیسس + لیکویڈیشن + فلو → رسک مینیجر |
| `earnings_research_desk` | بنیادی + نظرثانی + آپشنز → کمائی حکمت کار |
| `macro_rates_fx_desk` | شرح سود + FX + کموڈٹی → میکرو PM |
| `quant_strategy_desk` | اسکریننگ + فیکٹر ریسرچ → بیک ٹیسٹ → رسک آڈٹ |
| `technical_analysis_panel` | کلاسک TA + Ichimoku + harmonic + Elliott + SMC → اتفاق رائے |
| `risk_committee` | ڈراؤڈاؤن + ٹیل رسک + ریجیم جائزہ → منظوری |
| `global_allocation_committee` | A-شیئرز + کرپٹو + HK/US → کراس مارکیٹ مختص |

<sub>مزید 20+ خصوصی پری سیٹس — تمام دیکھنے کے لیے vibe-trading --swarm-presets چلائیں۔

</sub>

### 🎬 ڈیمو

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
<td colspan="2" align="center"><sub>☝️ قدرتی زبان بیک ٹیسٹ اور ملٹی ایجنٹ سوارم بحث — Web UI + CLI</sub></td>
</tr>
</table>
</div>

---

## 🚀 فوری آغاز

### ایک لائن انسٹالیشن (PyPI)

```bash
pip install vibe-trading-ai
```

> **پیکیج کا نام بمقابلہ کمانڈز:** PyPI پیکیج `vibe-trading-ai` ہے۔ انسٹال ہونے کے بعد آپ کو تین کمانڈز ملتی ہیں:
>
> | کمانڈ | مقصد |
> |---------|---------|
> | `vibe-trading` | انٹرایکٹو CLI / TUI |
> | `vibe-trading serve` | FastAPI ویب سرور شروع کریں |
> | `vibe-trading-mcp` | MCP سرور شروع کریں (Claude Desktop، OpenClaw، Cursor وغیرہ کے لیے) |

```bash
vibe-trading init              # انٹرایکٹو .env سیٹ اپ
vibe-trading                   # CLI شروع کریں
vibe-trading serve --port 8899 # ویب UI شروع کریں
vibe-trading-mcp               # MCP سرور شروع کریں (stdio)
```

### یا ایک راستہ چنیں

| راستہ | بہترین | وقت |
|------|----------|------|
| **A. Docker** | ابھی آزمائیں، کوئی مقامی سیٹ اپ نہیں | 2 منٹ |
| **B. مقامی انسٹالیشن** | ترقی، مکمل CLI رسائی | 5 منٹ |
| **C. MCP پلگ ان** | اپنے موجودہ ایجنٹ سے جوڑیں | 3 منٹ |
| **D. ClawHub** | ایک کمانڈ، کلوننگ نہیں | 1 منٹ |

### ضروری شرائط

- کسی بھی معاون فراہم کنندہ کا **LLM API کلید** — یا **Ollama** کے ساتھ مقامی طور پر چلائیں (کوئی کلید نہیں)
- راستے B کے لیے **Python 3.11+**
- راستے A کے لیے **Docker**

> **معاون LLM فراہم کنندگان:** OpenRouter, OpenAI, DeepSeek, Gemini, Groq, DashScope/Qwen, Zhipu, Moonshot/Kimi, MiniMax, Xiaomi MIMO, Z.ai, Ollama (مقامی)۔ ترتیب کے لیے `.env.example` دیکھیں۔

> **مشورہ:** خودکار فال بیک کی وجہ سے تمام مارکیٹس بغیر کسی API کلید کے کام کرتی ہیں۔ yfinance (HK/US)، OKX (کرپٹو) اور AKShare (A-شیئرز، US، HK، فیوچرز، فاریکس) سب مفت ہیں۔ Tushare ٹوکن اختیاری ہے — AKShare مفت متبادل کے طور پر A-شیئرز کا احاطہ کرتا ہے۔

### راستہ A: Docker (کوئی سیٹ اپ نہیں)

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
cp agent/.env.example agent/.env
# agent/.env میں ترمیم کریں — اپنے LLM فراہم کنندہ کو غیر تبصرہ کریں اور API کلید سیٹ کریں
docker compose up --build
```

`http://localhost:8899` کھولیں۔ بیک اینڈ + فرنٹ اینڈ ایک کنٹینر میں۔

### راستہ B: مقامی انسٹالیشن

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv

# فعال کریں
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\Activate.ps1       # Windows PowerShell

pip install -e .
cp agent/.env.example agent/.env   # ترمیم کریں — اپنے LLM فراہم کنندہ کی API کلید سیٹ کریں
vibe-trading                       # انٹرایکٹو TUI شروع کریں
```

<details>
<summary><b>ویب UI شروع کریں (اختیاری)</b></summary>

```bash
# ٹرمینل 1: API سرور
vibe-trading serve --port 8899

# ٹرمینل 2: فرنٹ اینڈ ڈیو سرور
cd frontend && npm install && npm run dev
```

`http://localhost:5899` کھولیں۔ فرنٹ اینڈ API کالز کو `localhost:8899` پر پراکسی کرتا ہے۔

**پروڈکشن موڈ (ایک سرور):**

```bash
cd frontend && npm run build && cd ..
vibe-trading serve --port 8899     # FastAPI جامد فائلوں کے طور پر dist/ پیش کرتا ہے
```

</details>

### راستہ C: MCP پلگ ان

نیچے [MCP پلگ ان](#-mcp-پلگ-ان) سیکشن دیکھیں۔

### راستہ D: ClawHub (ایک کمانڈ)

```bash
npx clawhub@latest install vibe-trading --force
```

مہارت + MCP ترتیب آپ کے ایجنٹ کی مہارتوں کی ڈائریکٹری میں ڈاؤنلوڈ ہو جاتی ہے۔ تفصیلات کے لیے [ClawHub انسٹال](#-mcp-پلگ-ان) دیکھیں۔

---

## 🧠 ماحولیاتی متغیرات

`agent/.env.example` کو `agent/.env` میں کاپی کریں اور اپنا مطلوبہ فراہم کنندہ بلاک غیر تبصرہ کریں۔ ہر فراہم کنندہ کو 3-4 متغیرات درکار ہیں:

| متغیر | ضروری | تفصیل |
|----------|:--------:|-------------|
| `LANGCHAIN_PROVIDER` | ہاں | فراہم کنندہ کا نام (`openrouter`, `deepseek`, `groq`, `ollama` وغیرہ) |
| `<PROVIDER>_API_KEY` | ہاں* | API کلید (`OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY` وغیرہ) |
| `<PROVIDER>_BASE_URL` | ہاں | API اینڈ پوائنٹ URL |
| `LANGCHAIN_MODEL_NAME` | ہاں | ماڈل کا نام (مثلاً `deepseek/deepseek-v3.2`) |
| `TUSHARE_TOKEN` | نہیں | A-شیئر ڈیٹا کے لیے Tushare Pro ٹوکن (AKShare پر فال بیک) |
| `TIMEOUT_SECONDS` | نہیں | LLM کال ٹائم آؤٹ، ڈیفالٹ 120 سیکنڈ |

<sub>* Ollama کو API کلید کی ضرورت نہیں۔</sub>

**مفت ڈیٹا (کوئی کلید درکار نہیں):** AKShare کے ذریعے A-شیئرز، yfinance کے ذریعے HK/US ایکویٹیز، OKX کے ذریعے کرپٹو، CCXT کے ذریعے 100+ کرپٹو ایکسچینجز۔ سسٹم ہر مارکیٹ کے لیے خودبخود بہترین دستیاب سورس منتخب کرتا ہے۔

### 🎯 تجویز کردہ ماڈل

Vibe-Trading ایک ٹول سے بھرپور ایجنٹ ہے — مہارتیں، بیک ٹیسٹ، میموری اور سوارم سب ٹول کالز کے ذریعے چلتے ہیں۔ ماڈل کا انتخاب براہ راست یہ طے کرتا ہے کہ ایجنٹ اپنے اوزار *استعمال* کرتا ہے یا تربیتی ڈیٹا سے جوابات گھڑتا ہے۔

| درجہ | مثالیں | کب استعمال کریں |
|------|----------|-------------|
| **بہترین** | `anthropic/claude-opus-4.7`، `anthropic/claude-sonnet-4.6`، `openai/gpt-5.4`، `google/gemini-3.1-pro-preview` | پیچیدہ سوارم (3+ ایجنٹس)، طویل تحقیقی سیشن، تحقیقی سطح کا تجزیہ |
| **بہترین توازن** (ڈیفالٹ) | `deepseek/deepseek-v3.2`، `x-ai/grok-4.20`، `z-ai/glm-5.1`، `moonshotai/kimi-k2.5`، `qwen/qwen3-max-thinking` | روزمرہ استعمال — ~1/10 لاگت پر قابل اعتماد ٹول کالنگ |
| **ایجنٹ کے لیے گریز کریں** | `*-nano`، `*-flash-lite`، `*-coder-next`، چھوٹے / ڈسٹلڈ ورژن | ٹول کالنگ ناقابل اعتماد — ایجنٹ مہارتیں لوڈ کرنے یا بیک ٹیسٹ چلانے کے بجائے "یادداشت سے جواب دیتا" نظر آئے گا |

ڈیفالٹ `agent/.env.example` `deepseek/deepseek-v3.2` کے ساتھ آتا ہے — بہترین توازن کے درجے میں سب سے سستا آپشن۔

---

## 🖥 CLI حوالہ

```bash
vibe-trading               # انٹرایکٹو TUI
vibe-trading run -p "..."  # ایک بار چلائیں
vibe-trading serve         # API سرور
```

<details>
<summary><b>TUI کے اندر سلیش کمانڈز</b></summary>

| کمانڈ | تفصیل |
|---------|-------------|
| `/help` | تمام کمانڈز دکھائیں |
| `/skills` | تمام 71 مالیاتی مہارتوں کی فہرست |
| `/swarm` | 29 سوارم ٹیم پری سیٹس کی فہرست |
| `/swarm run <preset> [vars_json]` | لائیو اسٹریمنگ کے ساتھ سوارم ٹیم چلائیں |
| `/swarm list` | سوارم رن تاریخ |
| `/swarm show <run_id>` | سوارم رن کی تفصیلات |
| `/swarm cancel <run_id>` | چل رہے سوارم کو منسوخ کریں |
| `/list` | حالیہ رنز |
| `/show <run_id>` | رن کی تفصیلات + میٹرکس |
| `/code <run_id>` | تیار کردہ حکمت عملی کوڈ |
| `/pine <run_id>` | انڈیکیٹرز برآمد کریں (TradingView + TDX + MT5) |
| `/trace <run_id>` | مکمل عملدرآمد ری پلے |
| `/continue <run_id> <prompt>` | نئی ہدایات کے ساتھ رن جاری رکھیں |
| `/sessions` | چیٹ سیشنز کی فہرست |
| `/settings` | رن ٹائم ترتیب دکھائیں |
| `/clear` | اسکرین صاف کریں |
| `/quit` | باہر نکلیں |

</details>

<details>
<summary><b>ایک بار چلانا اور فلیگز</b></summary>

```bash
vibe-trading run -p "BTC-USDT MACD حکمت عملی کا بیک ٹیسٹ کریں، آخری 30 دن"
vibe-trading run -p "AAPL کی رفتار کا تجزیہ کریں" --json
vibe-trading run -f strategy.txt
echo "000001.SZ RSI کا بیک ٹیسٹ کریں" | vibe-trading run
```

```bash
vibe-trading -p "آپ کا پرامپٹ"
vibe-trading --skills
vibe-trading --swarm-presets
vibe-trading --swarm-run investment_committee '{"topic":"BTC آؤٹ لک"}'
vibe-trading --list
vibe-trading --show <run_id>
vibe-trading --code <run_id>
vibe-trading --pine <run_id>           # انڈیکیٹرز برآمد کریں (TradingView + TDX + MT5)
vibe-trading --trace <run_id>
vibe-trading --continue <run_id> "حکمت عملی بہتر کریں"
vibe-trading --upload report.pdf
```

</details>

---

## 🌐 API سرور

```bash
vibe-trading serve --port 8899
```

| طریقہ | اینڈ پوائنٹ | تفصیل |
|--------|----------|-------------|
| `GET` | `/runs` | رنز کی فہرست |
| `GET` | `/runs/{run_id}` | رن کی تفصیلات |
| `GET` | `/runs/{run_id}/pine` | ملٹی پلیٹ فارم انڈیکیٹر برآمد |
| `POST` | `/sessions` | سیشن بنائیں |
| `POST` | `/sessions/{id}/messages` | پیغام بھیجیں |
| `GET` | `/sessions/{id}/events` | SSE ایونٹ اسٹریم |
| `POST` | `/upload` | PDF/فائل اپ لوڈ کریں |
| `GET` | `/swarm/presets` | سوارم پری سیٹس کی فہرست |
| `POST` | `/swarm/runs` | سوارم رن شروع کریں |
| `GET` | `/swarm/runs/{id}/events` | سوارم SSE اسٹریم |

انٹرایکٹو دستاویزات: `http://localhost:8899/docs`

---

## 🔌 MCP پلگ ان

Vibe-Trading کسی بھی MCP مطابق کلائنٹ کے لیے 17 MCP ٹولز پیش کرتا ہے۔ stdio سب پروسیس کے طور پر چلتا ہے — کوئی سرور سیٹ اپ نہیں۔ **17 میں سے 16 ٹولز صفر API کلیدز کے ساتھ کام کرتے ہیں** (HK/US/کرپٹو)۔ صرف `run_swarm` کو LLM کلید درکار ہے۔

<details>
<summary><b>Claude Desktop</b></summary>

`claude_desktop_config.json` میں شامل کریں:

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

`~/.openclaw/config.yaml` میں شامل کریں:

```yaml
skills:
  - name: vibe-trading
    command: vibe-trading-mcp
```

</details>

<details>
<summary><b>Cursor / Windsurf / دیگر MCP کلائنٹس</b></summary>

```bash
vibe-trading-mcp                  # stdio (ڈیفالٹ)
vibe-trading-mcp --transport sse  # ویب کلائنٹس کے لیے SSE
```

</details>

**دستیاب MCP ٹولز (17):** `list_skills`, `load_skill`, `backtest`, `factor_analysis`, `analyze_options`, `pattern_recognition`, `get_market_data`, `web_search`, `read_url`, `read_document`, `read_file`, `write_file`, `list_swarm_presets`, `run_swarm`, `get_swarm_status`, `get_run_result`, `list_runs`۔

<details>
<summary><b>ClawHub سے انسٹال کریں (ایک کمانڈ)</b></summary>

```bash
npx clawhub@latest install vibe-trading --force
```

> `--force` ضروری ہے کیونکہ مہارت بیرونی APIs کا حوالہ دیتی ہے جو VirusTotal کا خودکار اسکین شروع کر دیتا ہے۔ کوڈ مکمل طور پر اوپن سورس اور معائنے کے لیے محفوظ ہے۔

یہ مہارت + MCP ترتیب کو آپ کے ایجنٹ کی مہارتوں کی ڈائریکٹری میں ڈاؤنلوڈ کرتا ہے۔ کلوننگ کی ضرورت نہیں۔

ClawHub پر دیکھیں: [clawhub.ai/skills/vibe-trading](https://clawhub.ai/skills/vibe-trading)

</details>

<details>
<summary><b>OpenSpace — خود ارتقائی مہارتیں</b></summary>

تمام 71 مالیاتی مہارتیں [open-space.cloud](https://open-space.cloud) پر شائع ہیں اور OpenSpace کے خود ارتقاء انجن کے ذریعے خودمختاری سے ارتقاء پاتی ہیں۔

OpenSpace کے ساتھ استعمال کرنے کے لیے، اپنے ایجنٹ کی ترتیب میں دونوں MCP سرورز شامل کریں:

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

OpenSpace تمام 71 مہارتیں خودبخود دریافت کرے گا، خودکار درستگی، خودکار بہتری اور کمیونٹی شیئرنگ کو ممکن بناتے ہوئے۔ کسی بھی OpenSpace سے جڑے ایجنٹ میں `search_skills("finance backtest")` کے ذریعے Vibe-Trading مہارتیں تلاش کریں۔

</details>

---

## 📁 منصوبے کا ڈھانچہ

<details>
<summary><b>توسیع کے لیے کلک کریں</b></summary>

```
Vibe-Trading/
├── agent/                          # بیک اینڈ (Python)
│   ├── cli.py                      # CLI داخلہ نقطہ — انٹرایکٹو TUI + ذیلی کمانڈز
│   ├── api_server.py               # FastAPI سرور — رنز، سیشن، اپ لوڈ، سوارم، SSE
│   ├── mcp_server.py               # MCP سرور — OpenClaw / Claude Desktop کے لیے 17 ٹولز
│   │
│   ├── src/
│   │   ├── agent/                  # ReAct ایجنٹ کور
│   │   │   ├── loop.py             #   5 پرتی کمپریشن + پڑھنے/لکھنے کے ٹول بیچنگ
│   │   │   ├── context.py          #   سسٹم پرامپٹ + مستقل میموری سے خودکار ریکال
│   │   │   ├── skills.py           #   مہارت لوڈر (71 بنڈلڈ + CRUD کے ذریعے صارف ساختہ)
│   │   │   ├── tools.py            #   ٹول بیس کلاس + رجسٹری
│   │   │   ├── memory.py           #   فی رن ہلکا ورک اسپیس اسٹیٹ
│   │   │   ├── frontmatter.py      #   مشترک YAML frontmatter پارسر
│   │   │   └── trace.py            #   عملدرآمد ٹریس رائٹر
│   │   │
│   │   ├── memory/                 # کراس سیشن مستقل میموری
│   │   │   └── persistent.py       #   فائل پر مبنی میموری (~/.vibe-trading/memory/)
│   │   │
│   │   ├── tools/                  # 27 خودبخود دریافت شدہ ایجنٹ ٹولز
│   │   │   ├── backtest_tool.py    #   بیک ٹیسٹ چلائیں
│   │   │   ├── remember_tool.py    #   کراس سیشن میموری (محفوظ/ریکال/بھول)
│   │   │   ├── skill_writer_tool.py #  مہارت CRUD (محفوظ/پیچ/حذف/فائل)
│   │   │   ├── session_search_tool.py # FTS5 کراس سیشن تلاش
│   │   │   ├── swarm_tool.py       #   سوارم ٹیمیں شروع کریں
│   │   │   ├── web_search_tool.py  #   DuckDuckGo ویب تلاش
│   │   │   └── ...                 #   bash، فائل I/O، فیکٹر تجزیہ، آپشنز وغیرہ
│   │   │
│   │   ├── skills/                 # 7 زمروں میں 71 مالیاتی مہارتیں (ہر ایک میں SKILL.md)
│   │   ├── swarm/                  # سوارم DAG عملدرآمد انجن
│   │   ├── session/                # ملٹی ٹرن چیٹ + FTS5 سیشن تلاش
│   │   └── providers/              # LLM فراہم کنندہ تجرید
│   │
│   ├── backtest/                   # بیک ٹیسٹ انجن
│   │   ├── engines/                #   7 انجن + مرکب کراس مارکیٹ انجن + options_portfolio
│   │   ├── loaders/                #   5 سورسز: tushare, okx, yfinance, akshare, ccxt
│   │   │   ├── base.py             #   DataLoader پروٹوکول
│   │   │   └── registry.py         #   رجسٹری + خودکار فال بیک چینز
│   │   └── optimizers/             #   MVO، مساوی vol، max div، رسک پیریٹی
│   │
│   └── config/swarm/               # 29 سوارم پری سیٹ YAML تعریفات
│
├── frontend/                       # ویب UI (React 19 + Vite + TypeScript)
│   └── src/
│       ├── pages/                  #   ہوم، ایجنٹ، RunDetail، موازنہ
│       ├── components/             #   چیٹ، چارٹس، لے آؤٹ
│       └── stores/                 #   Zustand اسٹیٹ مینجمنٹ
│
├── Dockerfile                      # ملٹی اسٹیج بلڈ
├── docker-compose.yml              # ایک کمانڈ تعیناتی
├── pyproject.toml                  # پیکیج ترتیب + CLI داخلہ نقطہ
└── LICENSE                         # MIT
```

</details>

---

## 🏛 ماحولیاتی نظام

Vibe-Trading **[HKUDS](https://github.com/HKUDS)** ایجنٹ ماحولیاتی نظام کا حصہ ہے:

<table>
  <tr>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/ClawTeam"><b>ClawTeam</b></a><br>
      <sub>ایجنٹ سوارم انٹیلیجنس</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/nanobot"><b>NanoBot</b></a><br>
      <sub>انتہائی ہلکا ذاتی AI معاون</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/CLI-Anything"><b>CLI-Anything</b></a><br>
      <sub>تمام سافٹ ویئر کو ایجنٹ نیٹیو بنانا</sub>
    </td>
    <td align="center" width="25%">
      <a href="https://github.com/HKUDS/OpenSpace"><b>OpenSpace</b></a><br>
      <sub>خود ارتقائی AI ایجنٹ مہارتیں</sub>
    </td>
  </tr>
</table>

---

## 🗺 راہ نقشہ

> ہم مراحل میں شپ کرتے ہیں۔ کام شروع ہونے پر آئٹمز [Issues](https://github.com/HKUDS/Vibe-Trading/issues) پر منتقل ہو جاتے ہیں۔

| مرحلہ | خصوصیت | حیثیت |
|-------|---------|--------|
| **ایجنٹ ہارنس** | مستقل کراس سیشن میموری (یاد رکھیں / ریکال / بھولیں) | **مکمل** |
| | خود ارتقائی مہارتیں — ایجنٹ اپنے ورک فلوز خود بناتا، پیچ کرتا اور حذف کرتا ہے | **مکمل** |
| | تمام پرانی گفتگوؤں میں FTS5 کراس سیشن تلاش | **مکمل** |
| | 5 پرتی سیاق و سباق کمپریشن (micro → collapse → auto → manual → iterative) | **مکمل** |
| | پڑھنے/لکھنے کے ٹول بیچنگ — صرف پڑھنے والے ٹولز کا متوازی عملدرآمد | **مکمل** |
| **آگے** | خودمختار تحقیقی لوپ — ایجنٹ رات بھر مفروضے دہراتا ہے | جاری |
| | IM انضمام (Slack / Telegram / WeChat) | منصوبہ بند |
| **تجزیہ اور تصویر کشی** | آپشنز volatility surface اور Greeks کا 3D تصویری نمائندگی | منصوبہ بند |
| | رولنگ ونڈو اور کلسٹرنگ کے ساتھ کراس اثاثہ ارتباط ہیٹ میپ | منصوبہ بند |
| | CLI بیک ٹیسٹ آؤٹ پٹ میں بینچ مارک موازنہ | منصوبہ بند |
| **مہارتیں اور پری سیٹس** | ڈیویڈنڈ تجزیہ مہارت | منصوبہ بند |
| | ESG / پائیدار سرمایہ کاری سوارم پری سیٹ | منصوبہ بند |
| **پورٹ فولیو اور آپٹیمائزیشن** | اعلی پورٹ فولیو آپٹیمائزر: لیوریج، سیکٹر حدود، ٹرن اوور پابندیاں | منصوبہ بند |
| **مستقبل** | حکمت عملی مارکیٹ پلیس (شیئر اور دریافت) | زیر غور |
| | WebSocket کے ذریعے لائیو ڈیٹا اسٹریمنگ | زیر غور |

---

## شراکت

ہم شراکت کا خیرمقدم کرتے ہیں! رہنما اصولوں کے لیے [CONTRIBUTING.md](CONTRIBUTING.md) دیکھیں۔

**اچھے پہلے مسائل** [`good first issue`](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) سے نشان زد ہیں — ایک چنیں اور شروع کریں۔

کچھ بڑا شراکت کرنا چاہتے ہیں؟ اوپر [راہ نقشہ](#-راہ-نقشہ) دیکھیں اور شروع کرنے سے پہلے بحث کے لیے مسئلہ کھولیں۔

---

## شراکت داران

Vibe-Trading میں شراکت کرنے والے سب کا شکریہ!

<a href="https://github.com/HKUDS/Vibe-Trading/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=HKUDS/Vibe-Trading" />
</a>

---

## اعلانِ لاتعلقی

Vibe-Trading صرف تحقیق، نقالی اور بیک ٹیسٹنگ کے لیے ہے۔ یہ سرمایہ کاری کا مشورہ نہیں ہے اور یہ لائیو ٹریڈز نہیں کرتا۔ ماضی کی کارکردگی مستقبل کے نتائج کی ضمانت نہیں دیتی۔

## لائسنس

MIT لائسنس — [LICENSE](LICENSE) دیکھیں

---

<p align="center">
  <b>Vibe-Trading</b> پر آنے کا شکریہ ✨
</p>
<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=HKUDS.Vibe-Trading&style=flat" alt="زائرین"/>
</p>
