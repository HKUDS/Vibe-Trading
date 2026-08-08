---
name: credit-analysis
description: "固收与信用分析：信用债评级、利差分析、违约风险评估、城投债研究、可转债定价与策略。"
category: analysis
---

# Credit Analysis Skill — 固收与信用分析

## 适用场景

当用户提出以下类型问题时，优先调用本 skill：
- 债券定价、YTM 计算、久期/凸性分析
- 企业信用评级、违约概率估算
- 信用利差分析与交易策略
- 城投债、ABS/MBS 信用评估
- 利率风险管理（DV01、关键利率久期）
- 中国固收市场结构分析

---

## 一、信用分析框架

### 1.1 信用评级体系

#### 主体评级 vs 债项评级

| 类型 | 定义 | 评级对象 |
|------|------|----------|
| **主体评级（Issuer Rating）** | 发行人整体偿债能力 | 企业、政府、金融机构 |
| **债项评级（Issue Rating）** | 特定债券的信用质量 | 具体债券，考虑抵押品、优先级、契约条款 |

债项评级可高于或低于主体评级（取决于担保结构）。

#### 标准普尔 / 穆迪 / 中国评级对照

| S&P | Moody's | 中国评级 | 含义 |
|-----|---------|----------|------|
| AAA | Aaa | AAA | 最高信用质量，极低违约风险 |
| AA+/AA/AA- | Aa1/Aa2/Aa3 | AA+/AA/AA- | 高质量，极低违约风险 |
| A+/A/A- | A1/A2/A3 | A+/A/A- | 较高信用质量 |
| BBB+/BBB/BBB- | Baa1/Baa2/Baa3 | BBB+/BBB/BBB- | 投资级下限（IG/HY分水岭） |
| BB+及以下 | Ba1及以下 | BB+及以下 | 高收益/投机级 |
| D | D | D | 违约 |

> **中国特点**：国内评级虚高，AA级在国内约等同于国际BBB-，需结合评级展望（正面/稳定/负面）综合判断。

---

### 1.2 Altman Z-Score 模型

用于预测企业财务困境，原始模型适用于上市制造业：

```
Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5
```

| 变量 | 计算公式 | 含义 |
|------|----------|------|
| X1 | 营运资本 / 总资产 | 流动性 |
| X2 | 留存收益 / 总资产 | 盈利积累 |
| X3 | EBIT / 总资产 | 盈利能力 |
| X4 | 股权市值 / 总负债账面值 | 财务杠杆 |
| X5 | 销售收入 / 总资产 | 资产效率 |

**判断区间**：
- Z > 2.99：安全区（低违约风险）
- 1.81 < Z < 2.99：灰色区（需深入分析）
- Z < 1.81：危险区（高违约风险）

**改进版本**：
- Z'（私有企业）：X4改用股权账面值，临界值2.90/1.23
- Z''（非制造业/新兴市场）：去掉X5，临界值2.60/1.10

**局限性**：
- 基于历史数据，滞后性强
- 不适用金融类企业（杠杆定义不同）
- 中国市场需重新标定参数

---

### 1.3 Merton 结构化模型

将公司股权视为对公司资产的看涨期权（执行价格=债务面值）：

**核心假设**：
- 公司资产价值 V 遵循几何布朗运动：`dV = μV dt + σ_V V dW`
- 债务为零息债，面值 D，到期日 T
- 违约仅在 T 时刻发生（欧式违约设定）

**股权定价（BS公式）**：
```
E = V·N(d1) - D·e^(-rT)·N(d2)

d1 = [ln(V/D) + (r + σ_V²/2)T] / (σ_V·√T)
d2 = d1 - σ_V·√T
```

**违约概率（风险中性）**：
```
PD = N(-d2)
```

**距违约距离（DD, Distance to Default）**：
```
DD = [ln(V/D) + (μ - σ_V²/2)T] / (σ_V·√T)
```

**信用利差估算**：
```
信用利差 ≈ -ln[N(d2) + (V/D·e^(rT))·N(-d1)] / T
```

**参数估算方法**（联立方程组）：
1. E = V·N(d1) - D·e^(-rT)·N(d2)
2. σ_E·E = N(d1)·σ_V·V

---

### 1.4 KMV 模型（预期违约频率 EDF）

KMV 是 Merton 模型的商业化实现，由穆迪收购：

**步骤**：
1. 用股价和股权波动率反推资产价值 V 和资产波动率 σ_V
2. 计算违约触发点（Default Point）：`DP = 短期债务 + 0.5×长期债务`
3. 计算距违约距离：`DD = (V - DP) / (V × σ_V)`
4. 通过历史违约数据库将 DD 映射为 EDF（非正态映射）

**与 Merton 的区别**：
- 违约触发点不是全部债务，而是短期+半长期
- DD→EDF 映射基于实证数据库，非正态分布假设
- EDF 是真实世界概率，而非风险中性概率

**EDF 参考区间**（约）：
- EDF < 0.1%：投资级
- 0.1%–1%：BBB-BB 级
- 1%–5%：B 级
- EDF > 5%：CCC 及以下

---

### 1.5 信用评分卡方法论

适用于零售信贷/ABS 底层资产分析：

**建模流程**：
1. **数据准备**：收集历史贷款数据，定义违约标签（如逾期90天+）
2. **特征工程**：WOE（Weight of Evidence）编码
3. **特征选择**：IV值（Information Value）筛选，IV>0.02保留
4. **模型训练**：Logistic Regression（主流）、XGBoost
5. **评分转换**：`Score = A - B×ln(odds)`，通常基准分600，PDO=20

**WOE 和 IV 计算**：
```python
WOE_i = ln(好样本比例_i / 坏样本比例_i)
IV_i = (好样本比例_i - 坏样本比例_i) × WOE_i
总IV = Σ IV_i
```

**IV 参考标准**：
- IV < 0.02：无预测力
- 0.02–0.1：弱预测力
- 0.1–0.3：中等预测力
- IV > 0.3：强预测力

---

## 二、固收产品分析

### 2.1 国债与政府债

#### 收益率曲线分析

**即期利率曲线（Zero Curve）**：各期限无风险零息债收益率，通过 Bootstrap 方法从附息债提取。

**远期利率曲线（Forward Curve）**：
```
f(T1, T2) = [(1+r2)^T2 / (1+r1)^T1]^(1/(T2-T1)) - 1
```

**期限利差**：
- 10Y-2Y：经济周期预判指标，负值通常预示衰退
- 10Y-1Y：流动性偏好衡量指标
- 30Y-10Y：超长端供需判断

**收益率曲线形态**：
| 形态 | 特征 | 经济含义 |
|------|------|----------|
| 正斜率（Normal） | 长端>短端 | 经济扩张预期 |
| 平坦（Flat） | 各期限相近 | 经济转折点 |
| 倒挂（Inverted） | 短端>长端 | 衰退信号 |
| 驼峰（Humped） | 中端最高 | 流动性分层 |

#### 中国国债收益率曲线特点
- 基准曲线：中国国债（CGBs）+ 国开债（Policy Bank Bonds）
- 关键点位：1Y/3Y/5Y/7Y/10Y/30Y
- 10Y国债为核心基准利率

---

### 2.2 企业债分析

#### 核心指标

**票面利率（Coupon Rate）**：发行时约定，按面值计息。

**到期收益率 YTM（Yield to Maturity）**：
使 债券现值 = 市场价格的内部收益率：
```
P = Σ [C/(1+y)^t] + F/(1+y)^n
```
其中 C=票息，F=面值，y=YTM，n=期数。

**当期收益率（Current Yield）**：`CY = 年票息 / 市场价格`（忽略本金损益）

**修正久期（Modified Duration）**：
```
MD = -dP/P ÷ dy = Macaulay Duration / (1+y/m)
```
含义：利率每变化1%，债券价格变化约MD%（反向）。

**凸性（Convexity）**：
```
CX = [Σ t(t+1)·CF_t/(1+y)^(t+2)] / P
价格变化修正：ΔP/P ≈ -MD·Δy + 0.5·CX·(Δy)²
```

#### 债券价格公式（实现）

定价函数是仓库里的实测代码，直接 import，**不要在会话里重新手写**：

```python
from src.quantlib.fixedincome import bond_price

bond_price(face=100, coupon_rate=0.05, ytm=0.04, n_periods=5, freq=1)
# -> 104.4518...   5年期、票息5%、YTM=4%、年付
```

两个约定在这里是**显式参数**，不是隐含假设：

- `compounding`：`"discrete"`（默认，每年 `freq` 次离散复利，即上面 `P = Σ C/(1+y/m)^t` 的形式）或 `"continuous"`。
- 日算基准：`bond_price` 按整数付息期贴现，因此返回的是**付息日**的价格（净价，应计为 0）。
  非付息日结算要另加应计利息才是全价（脏价）：

```python
import datetime as dt
from src.quantlib.fixedincome import accrued_interest

accrued = accrued_interest(
    face=100, coupon_rate=0.05, freq=2,
    last_coupon=dt.date(2024, 1, 15),
    settlement=dt.date(2024, 4, 15),
    next_coupon=dt.date(2024, 7, 15),
    day_count="30/360",   # ACT/365F(默认) | ACT/360 | ACT/ACT | 30/360 | 30E/360
)                          # -> 1.25
dirty_price = bond_price(100, 0.05, 0.04, 10, 2) + accrued
```

---

### 2.3 可转债（纯债部分）

> 可转债的转股期权部分详见 `convertible-bond` skill，本节聚焦纯债价值。

**纯债价值（Bond Floor）**：
```
纯债价值 = Σ [票息/(1+r_straight)^t] + 面值/(1+r_straight)^n
```
其中 r_straight 为同评级同期限直债收益率。

**转股溢价率与纯债溢价率**：
- 转股溢价率 = (可转债价格 - 转股价值) / 转股价值
- 纯债溢价率 = (可转债价格 - 纯债价值) / 纯债价值

**下修条款信用含义**：
下修转股价可能导致摊薄，需评估公司意愿（强赎冲动 vs 回售压力）。

---

### 2.4 ABS/MBS 分析

#### 底层资产分析框架

**资产质量指标**：
- 加权平均票息（WAC）
- 加权平均剩余期限（WAM）
- 加权平均贷款价值比（LTV）
- 历史逾期率（DPD 30/60/90+）
- 累计违约率（CDR，Cumulative Default Rate）

**早偿率模型**：
- CPR（Conditional Prepayment Rate）：年化早偿率
- SMM（Single Monthly Mortality）：月早偿率
  ```
  CPR = 1 - (1 - SMM)^12
  SMM = 1 - (1 - CPR)^(1/12)
  ```
- PSA 模型：标准早偿假设（PSA100 = 前30个月线性增至6%/年，之后6%/年恒定）

**分层结构（Tranche）分析**：
- 优先级（Senior）：最先受偿，评级最高
- 夹层（Mezzanine）：次级受偿
- 劣后级（Equity/Junior）：首先吸收损失，超额利差归属

**关键风险指标**：
```
增信倍数 = (底层资产池规模 - 优先级规模) / 优先级规模
超额利差 = 底层资产池利率 - 优先级融资成本 - 服务费
```

---

### 2.5 城投债信用分析

城投债（LGFV，地方政府融资平台债）是中国固收市场特有品种。

#### 分析框架

**四维评估模型**：

| 维度 | 核心指标 | 权重 |
|------|----------|------|
| 区域财政实力 | 一般公共预算收入、GDP规模、财政自给率 | 40% |
| 平台层级 | 省级>市级>区县级，级别越高隐性支持越强 | 25% |
| 平台地位 | 是否唯一城投、资产注入力度、业务多元化 | 20% |
| 债务结构 | 有息负债规模、短期债务占比、再融资压力 | 15% |

**隐性债务风险信号**：
- 城投货币资金/短期债务 < 0.5（流动性紧张）
- EBITDA利息覆盖率 < 1（依赖外部融资付息）
- 非标融资占比>30%（再融资风险高）
- 区县级城投、弱区域（负债率>100%）

**城投估值溢价结构**（参考）：
```
城投利率 ≈ 同期国债 + 流动性溢价(30-50bp) + 区域溢价(0-200bp) + 平台溢价(0-100bp)
```

**政策风险**：2023年城投化债政策后分化加剧，关注：
- 一揽子化债进度
- 平台转型（城投转企业）
- 区域名单管理政策

---

## 三、利率风险管理

### 3.1 久期体系

#### Macaulay Duration（麦考利久期）

时间加权现金流现值之和，单位为"年"：
```
D_mac = Σ [t × CF_t/(1+y)^t] / P
```

#### Modified Duration（修正久期）

利率敏感性度量：
```
D_mod = D_mac / (1 + y/m)
ΔP ≈ -D_mod × P × Δy
```

#### Effective Duration（有效久期）

适用于含权债券（可赎回债、MBS等）：
```
D_eff = (P_down - P_up) / (2 × P_0 × Δy)
```
其中 P_down/P_up 为利率下移/上移Δy后的价格。

#### Dollar Duration（久期金额）

```
Dollar Duration = D_mod × P × 面值
```

---

### 3.2 凸性（Convexity）

衡量久期对利率的敏感性（二阶效应）：

```
C = Σ [t(t+1) × CF_t/(1+y)^(t+2)] / P

价格精确估算：
ΔP/P ≈ -D_mod·Δy + 0.5·C·(Δy)²
```

**凸性的价值**：正凸性使债券在利率下行时涨幅大于预期（利率上行时跌幅小于预期），因此正凸性债券比负凸性债券（如可赎回债、MBS）更受青睐。

---

### 3.3 DV01（基点价值）

利率变动1基点（0.01%）导致的价格变化：
```
DV01 = D_mod × P × 0.0001
```

组合层面：`Portfolio DV01 = Σ (DV01_i × 持仓量_i)`

**用途**：利率对冲比率计算
```
对冲比率 = DV01_被对冲头寸 / DV01_对冲工具
```

---

### 3.4 关键利率久期（Key Rate Duration, KRD）

衡量收益率曲线各关键期限平行移动1bp对价格的影响：
- 常用关键点：1Y, 2Y, 3Y, 5Y, 7Y, 10Y, 20Y, 30Y
- `KRD_i = -ΔP/(P × Δy_i)`（仅第i个关键利率变动1bp）
- `Σ KRD_i ≈ D_mod`（各关键利率久期之和约等于修正久期）

**应用**：
- 识别组合对特定期限利率的暴露
- 精确对冲非平行移动风险（扭曲/蝶式）

---

### 3.5 免疫策略

**久期匹配（Duration Matching）**：
使资产组合久期 = 负债久期，对利率平行移动免疫。
条件：`Σ (w_i × D_i) = D_liability`

**现金流匹配（Cash Flow Matching）**：
直接匹配每期现金流，彻底消除再投资风险，但灵活性差、成本高。

**条件免疫（Contingent Immunization）**：
当组合价值超过安全底线时主动管理，跌至底线时切换为被动免疫。

**再平衡频率**：
- 久期随时间漂移，需定期（季度/月度）再平衡
- 利率大幅变动（>50bp）后立即再平衡

---

## 四、信用利差分析

### 4.1 信用利差的构成

```
信用利差（Credit Spread）= 违约风险溢价 + 流动性溢价 + 税收溢价（部分市场）
```

| 组成部分 | 影响因素 | 量化方式 |
|----------|----------|----------|
| 违约风险溢价 | 评级、行业、财务状况、宏观周期 | CDS报价、模型测算 |
| 流动性溢价 | 发行规模、剩余期限、市场深度 | 买卖价差、换手率 |
| 税收溢价 | 国债免税优惠（部分国家/投资者） | 利率差异分析 |

**利差衡量基准**：
- 国际市场：G-Spread（vs 国债）、I-Spread（vs 掉期）、Z-Spread（零息利差）、OAS（期权调整利差）
- 中国市场：信用利差通常对比国债或AAA城投

**OAS（Option-Adjusted Spread）**：
剥离嵌入期权价值后的信用利差，适用于含权债比较：
```
P = Σ CF_t / (1 + r_t + OAS)^t
```

---

### 4.2 信用利差曲线形态

**正斜率**（常见）：长期利差 > 短期利差，反映期限不确定性叠加。

**平坦/倒挂**：
- 市场对长期信用风险乐观（平坦）
- 短期流动性危机/再融资困境（倒挂），警示信号

**信用利差与国债收益率的相关性**：
- 经济扩张：信用利差收窄（风险偏好上升）
- 经济衰退/信用事件：信用利差走阔
- "逃向质量"效应：国债收益率下行+信用利差扩大，双重打击高收益债

---

### 4.3 信用利差变化的驱动因素

**宏观因素**：
- GDP增速、PMI：预期改善→利差收窄
- 货币政策宽松：流动性溢价下降
- 信用事件（违约潮）：系统性利差走阔

**行业因素**：
- 行业政策（如地产调控、城投化债）
- 行业景气周期
- 再融资环境

**个券因素**：
- 评级调整（下调→利差跳升）
- 财务数据变化
- 到期压力（临近到期→流动性利差增加）

---

### 4.4 信用利差交易策略

**利差压缩交易（Spread Tightening）**：
做多被低估（高利差）信用债，做空国债对冲利率风险。
- 适用场景：经济复苏初期、央行宽松周期

**利差扩大交易（Spread Widening）**：
做空信用债（通过CDS），做多国债。
- 适用场景：经济下行、信用事件频发

**跨评级利差交易**：
做多高收益/做空投资级（利差压缩时），或相反。

**蝶式利差交易（Butterfly）**：
做多中期、做空短端和长端，获利于信用曲线中段的相对价值。

**中国特色工具**：
- 信用风险缓释工具（CRMW/CDS）：对冲信用风险
- 国债期货：对冲利率久期风险

---

## 五、Python 实现（quantlib）

本章的模型**已经是仓库里的实测代码**，位于 `src/quantlib/fixedincome.py`（债券数学 + 曲线拟合）
与 `src/quantlib/credit.py`（Altman Z / Merton-KMV / 利差）。两个模块都有对应的
`tests/quantlib/test_fixedincome.py`、`tests/quantlib/test_credit.py`，久期与 DV01 是对
"重新定价 ±1bp" 逐点核过的。

**直接 import 调用，不要在会话里重写这些公式。** 手写一遍既拿不到测试保障，也不可复现。

一律的单位约定：利率与比率是小数（`0.05` 表示 5%），期限与时间跨度是**年**，
久期/凸性的返回值是**年 / 年²**（不是付息期数），带 `_bp` 后缀的才是基点。

### 5.1 债券定价、久期与 DV01

```python
from src.quantlib.fixedincome import (
    bond_price, ytm_solve, macaulay_duration, modified_duration,
    convexity, dv01, effective_duration,
)

face, coupon, ytm, n, freq = 100, 0.05, 0.04, 5, 1

price = bond_price(face, coupon, ytm, n, freq)          # 104.4518
ytm_solve(price, face, coupon, n, freq)                 # 0.04（价格反解 YTM）

macaulay_duration(face, coupon, ytm, n, freq)           # 4.5571 年
modified_duration(face, coupon, ytm, n, freq)           # 4.3818 年
convexity(face, coupon, ytm, n, freq)                   # 24.4766 年²
dv01(face, coupon, ytm, n, freq, par_amount=1_000_000)  # 457.69 元/bp
```

**参数要点**

| 参数 | 说明 |
|------|------|
| `freq` | 每年付息次数，`1`=年付、`2`=半年付。所有函数都接受，绝不写死 |
| `compounding` | `"discrete"`（默认）或 `"continuous"`。连续复利下修正久期恒等于 Macaulay 久期 |
| `par_amount` | `dv01` 的持仓面值，默认 100 万；对冲的市值按 `par_amount * price / face` 计 |
| `bracket` | `ytm_solve` 的求根区间，默认 `(-0.5, 10.0)`，覆盖所有可交易债券 |

含权债（可赎回债、MBS）的现金流会随利率移动，解析久期不适用，改用重新定价法：

```python
d_eff = effective_duration(reprice=lambda y: my_oas_model(y), yield_level=0.04, bump=1e-4)
```

`reprice` 必须自带赎回/早偿逻辑；`effective_duration` 只负责 `(P_down - P_up) / (2·P₀·Δy)`。

### 5.2 收益率曲线拟合（Nelson-Siegel / Svensson）

```python
import numpy as np
from src.quantlib.fixedincome import fit_yield_curve, nelson_siegel, svensson

maturities = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
yields     = np.array([0.019, 0.020, 0.022, 0.024, 0.025, 0.027, 0.028, 0.029, 0.033, 0.035])

fit = fit_yield_curve(maturities, yields, model="svensson")
fit.params      # (beta0, beta1, beta2, beta3, lambda1, lambda2)
fit.rmse        # 拟合残差（小数，与输入同单位）
fit(4.5)        # 任意期限插值 -> 该点即期利率
fit([1, 5, 10]) # 也接受数组
```

`fit_yield_curve` 返回一个 **`CurveFit` 对象**（不是 `(params, func)` 元组）：它本身可调用，
同时带 `model` / `params` / `rmse` 三个只读字段。`model` 取 `"nelson_siegel"`（4 参数）
或 `"svensson"`（6 参数，双曲率因子）。

拟合方式是**可分离最小二乘**：给定衰减参数 λ 后 β 是线性的，用 OLS 精确求解，
只对 1~2 个 λ 做网格 + Nelder-Mead 搜索。这一点很要紧——对全部参数一起做单点起始的
L-BFGS-B（本 skill 早先模板的做法）**连自己生成的曲线都还原不回来**：
在 10 个期限的无噪 Nelson-Siegel 曲线上它停在 RMSE 6.4e-4（6.4bp），
而现在这个实现是 4.0e-14。

需要直接按参数取值（例如做因子分解、做情景模拟）时用底层函数：

```python
nelson_siegel(tau=[1, 5, 10], beta0=0.045, beta1=-0.02, beta2=0.03, lambda1=2.5)
svensson(tau=5.0, beta0=0.05, beta1=-0.03, beta2=0.04, beta3=-0.02,
         lambda1=1.2, lambda2=8.0)
```

`beta0` 是水平因子（长端渐近利率），`beta0 + beta1` 是瞬时短端利率，
`beta2` / `beta3` 是曲率因子，`lambda*` 是衰减速度（年）。传标量返回标量，传数组返回数组。

### 5.3 Altman Z-Score 计算

```python
from src.quantlib.credit import altman_z_score

z = altman_z_score(
    working_capital=200,      # X1 分子：流动资产 - 流动负债
    retained_earnings=300,    # X2 分子：留存收益
    ebit=150,                 # X3 分子：息税前利润
    equity_value=900,         # X4 分子：original 用股权市值，prime/double_prime 用账面净资产
    total_liabilities=600,    # X4 分母：全部负债的账面值
    total_assets=1000,        # X1/X2/X3/X5 的分母
    revenue=1200,             # X5 分子；double_prime 不需要，可省略
    model="original",         # original | prime | double_prime
)

z.z_score            # 3.255
z.zone               # "safe" | "grey" | "distress"
z.label_zh           # "安全区（低违约风险）"
z.components         # {"x1": 0.20, "x2": 0.30, "x3": 0.15, "x4": 1.50, "x5": 1.20}
z.safe_threshold     # 2.99
z.distress_threshold # 1.81
```

三个变体的系数与临界值在 `ALTMAN_MODELS` 里，与 §1.2 的表格一一对应：

| `model` | 适用对象 | 系数 (X1..X5) | 安全 / 危险 |
|---------|----------|---------------|-------------|
| `original` | 上市制造业（Altman 1968） | 1.2 / 1.4 / 3.3 / 0.6 / 1.0 | > 2.99 / < 1.81 |
| `prime`（Z'） | 私有企业，X4 改用账面净资产 | 0.717 / 0.847 / 3.107 / 0.420 / 0.998 | > 2.90 / < 1.23 |
| `double_prime`（Z''） | 非制造业 / 新兴市场，去掉 X5 | 6.56 / 3.26 / 6.72 / 1.05 / — | > 2.60 / < 1.10 |

> **X4 的分母是「全部负债」，不是「有息负债」。** §1.2 的变量表写的是"总负债账面值"，
> 参数名 `total_liabilities` 与模型定义一致。用有息负债代入会系统性高估 Z 值。

同一份报表在三个变体下给出的分区可以不同（上例：`original` 安全区、`prime` 灰色区），
这正是重新标定的意义，不是矛盾。

### 5.4 信用利差分析

```python
from src.quantlib.credit import credit_spread_analysis, spread_term_structure

df = credit_spread_analysis(
    bond_yields=bond_ytm_series,       # pd.Series，索引=日期
    risk_free_yields=cgb_ytm_series,   # 必须与上面同一个索引
    window=252,                        # 滚动窗口（交易日）
    lookback_periods=21,               # 慢速变化列的回溯期
    signal_z=1.5,                      # 触发 rich/cheap 的 |z| 阈值
    input_unit="percent",              # percent | decimal | bp
)
```

返回的 DataFrame 列固定为：`spread_bp`、`rolling_mean_bp`、`rolling_std_bp`、`z_score`、
`historical_percentile`、`change_1p_bp`、`change_lookback_bp`、`signal`。
`signal` 取 `"rich"`（利差偏低、偏贵）/ `"neutral"` / `"cheap"`（利差偏高、偏便宜）。

> **`historical_percentile` 是全样本排名，带前视偏差，不能当回测信号用。** 它把每一行
> 和它**之后**的行一起排序——同一天的分位数会随着新数据到来而改变（实测：同一行在 50 行
> 切片上是 0.02，在 100 行上变成 0.01）。这是原模板的行为，保留是为了不静默改变口径。
> `z_score` 与 `signal` 走滚动窗口，是因果的，要做信号用这两个。

```python
grid = spread_term_structure(
    issuers={"AAA城投": {1: 0.025, 3: 0.028, 5: 0.032},
             "AA城投":  {1: 0.032, 3: 0.041, 5: 0.055}},
    risk_free_curve={1: 0.020, 3: 0.022, 5: 0.025},
    input_unit="decimal",   # 注意默认值与上面那个函数不同
    decimals=1,
)
# 行=发行人，列=1Y_spread_bp / 3Y_spread_bp / 5Y_spread_bp
```

> **输入单位必须自己确认。** 两个函数的历史默认值不一致：`credit_spread_analysis`
> 默认收益率是**百分数**（`3.2` 表示 3.2%），`spread_term_structure` 默认是**小数**（`0.032`）。
> 默认值保留了原模板的行为，但 `input_unit` 现在是显式参数——喂数据前先看清楚手里的序列是哪一种，
> 搞反就是 100 倍的利差。

### 5.5 Merton 结构化模型与 KMV

```python
from src.quantlib.credit import (
    merton_model, merton_asset_solve, distance_to_default,
    kmv_default_point, kmv_distance_to_default, edf_reference_band,
)

m = merton_model(
    equity_value=100,   # 股权市值
    equity_vol=0.40,    # 股权年化波动率
    debt_face=100,      # 债务面值（简化为单笔零息债）
    risk_free=0.03,     # 连续复利无风险利率
    horizon=1.0,        # 债务到期年限
    asset_drift=None,   # 距违约距离用的资产漂移；None = 用 risk_free（风险中性口径）
)

m.asset_value           # 197.04  反推出的资产价值
m.asset_vol             # 0.2030  反推出的资产波动率
m.distance_to_default   # 3.3868  asset_drift=None 时等于 d2
m.default_probability   # 0.000354  风险中性违约概率 N(-d2)
m.credit_spread_bp      # 0.176 bp
```

联立方程（§1.3 的两式）在 `merton_asset_solve` 里解，且是在**对数空间**求解的，
所以根不会跑到负资产或负波动率上；不收敛会直接抛 `ValueError`，不会静默返回垃圾解。

**Merton 与 KMV 的 DD 是两个不同的量，不要混用**：

```python
# Merton：对数空间、带漂移与期限
distance_to_default(asset_value=200, asset_vol=0.25, default_point=100,
                    horizon=2.0, drift=0.06)

# KMV：线性缺口，无期限无漂移，违约点只含短债 + 部分长债
dp = kmv_default_point(short_term_debt=100, long_term_debt=200,
                       long_term_weight=0.5)      # -> 200
kmv_distance_to_default(asset_value=1000, asset_vol=0.25, default_point=dp)  # -> 3.2

edf_reference_band(3.2)   # -> (0.001, 0.01)，即 §8 表里的 0.1%–1% 档
```

> `edf_reference_band` 只是把 §8 那张"DD → EDF"经验表做成了查表函数。
> 真正的 KMV EDF 来自穆迪的专有违约数据库，这里的输出只能当**量级校验**，
> 绝不能当作已标定的违约概率报出去。

**风险中性 vs 真实世界**：`asset_drift` 只影响 `distance_to_default`，不影响 `d2`、
`default_probability` 和 `credit_spread`——后三者按定义就是风险中性的。想看真实世界口径，
传一个预期资产回报进去，然后配 `edf_reference_band` 读档，不要拿 `N(-dd)` 当 EDF 报。

---

## 六、中国固收市场特色

### 6.1 市场结构

#### 银行间市场 vs 交易所市场

| 维度 | 银行间市场（CFETS） | 交易所市场（上交所/深交所） |
|------|---------------------|--------------------------|
| 监管机构 | 人民银行 | 证监会 |
| 主要参与者 | 银行、保险、基金、外资 | 券商、基金、个人投资者 |
| 交易方式 | 询价（OTC）+ 匿名点击 | 集中撮合 + 大宗交易 |
| 主要品种 | 国债、政金债、信用债、ABS | 企业债、公司债、可转债 |
| 规模占比 | ~90%（以交易量计） | ~10% |
| 结算方式 | T+0/T+1（DVP） | T+1 |
| 流动性 | 高（国债/政金债） | 高（可转债）/低（纯债） |

#### 主要债券品种

| 品种 | 发行主体 | 监管/注册 | 信用风险 |
|------|----------|-----------|----------|
| 国债（CGBs） | 财政部 | 无限制 | 无（主权信用） |
| 地方政府债 | 各省市政府 | 财政部审批 | 极低 |
| 政策性银行债（国开/农发/进出口） | 政策行 | 无限制 | 极低（准主权） |
| 同业存单（NCD） | 银行 | 央行 | 低（银行信用） |
| 超短期融资券（SCP）/ 短融（CP）/ 中票（MTN） | 非金融企业 | 交易商协会（NAFMII） | 中 |
| 企业债 | 企业 | 发改委 | 中高 |
| 公司债 | 上市公司 | 证监会 | 中高 |
| 城投债 | 地方融资平台 | 多元 | 中高（隐性政府背书） |
| ABS/ABN | SPV | NAFMII/证监会 | 取决于底层资产 |

---

### 6.2 城投债深度分析要点

**一级市场分析**（发行定价）：
1. 核查发行人层级和区域（省/市/区县）
2. 审查主业占比（基础设施业务vs商业化业务比例）
3. 评估区域一般公共预算收入和政府负债率
4. 分析近3年城投流转资产的真实性（往来款异常）

**二级市场分析**（持仓估值）：
1. 跟踪利差变化（vs 同评级同期限）
2. 关注舆情事件（技术性违约/商票逾期/评级下调）
3. 监测再融资节奏（到期压力 vs 新发节奏）
4. 关注区域政策（化债名单、债务置换进度）

**风险预警信号（红线）**：
- 货币资金/短期债务 < 0.3
- 非标融资/有息负债 > 40%
- 商票逾期被纳入系统（票据失信名单）
- 所在区域城投整体再融资受阻
- 管理层人事变动叠加区域评级负面展望

---

### 6.3 理财/资管产品信用分析

**净值化转型后的底层穿透分析**：
- 混合型理财：需分别评估权益端（市值波动）和固收端（信用风险）
- 固收+策略：主体80%+债券，20%-以内权益/可转债
- FOF型理财：两层嵌套穿透，需评估底层基金持仓

**流动性分析框架**：
```
产品层面流动性 = f(底层资产流动性, 赎回条款, 摊余成本法 vs 市值法)
```
- 摊余成本法：价格稳定但隐藏风险（不适用净值化产品）
- 市值法：反映真实价值，但波动暴露可能引发赎回潮

**底层信用评估步骤**：
1. 获取债券持仓明细（季报/半年报披露）
2. 按评级/行业/城投/非城投分类
3. 计算加权信用利差
4. 识别集中度风险（单券 > 5%为高集中度）
5. 评估流动性梯度（高流动→低流动覆盖度）

---

### 6.4 违约案例分析方法论

**违约类型**：
| 类型 | 特征 | 中国典型案例 |
|------|------|------------|
| 流动性违约 | 资产健康但现金流断裂 | 部分中小房企 |
| 技术性违约 | 触发条款（交叉违约/加速到期） | 多见于弱资质主体 |
| 经营性违约 | 主业恶化导致还款能力下降 | 永煤、华晨（2020） |
| 欺诈性违约 | 财务造假/资产腾挪 | 康美药业、蓝盛博 |

**违约前沿信号（Precursor Signals）**：

```
财务层面：
  - 应收账款/总资产 异常增高（虚增收入）
  - 货币资金余额高但受限比例高
  - 商誉/无形资产占比持续增大
  - 关联方交易占比异常

市场层面：
  - 二级市场价格持续下跌（跌破90）
  - 信用利差快速走阔（单周>50bp）
  - 主承销商更换或不参与后续发行
  - CDS报价（如有）快速上升

评级层面：
  - 评级列入负面观察
  - 多家评级机构下调
  - 展望由稳定下调至负面
```

**事后分析框架（Post-Default Analysis）**：
1. 违约触发时点与资金流向重构
2. 资产负债表"真实性"评估（区分真实资产 vs 账面资产）
3. 债权优先级梳理（担保顺序、抵质押品）
4. 处置预期回收率估算（Recovery Rate）
5. 系统性风险传染路径（交叉持有、同类主体）

**中国市场回收率参考**：
- 城投债（技术性违约后化解）：接近100%
- 房企违约：约20%-50%（取决于土储质量）
- 工业企业违约：约30%-60%
- 金融机构（非银）：约40%-70%（监管介入程度）

---

## 七、与其他 Skill 的关联

| 相关 Skill | 互补关系 |
|------------|----------|
| `convertible-bond` | 可转债转股期权部分由 convertible-bond skill 处理，本 skill 负责纯债定价和信用风险 |
| `macro-analysis` | 宏观利率环境和信用周期判断由 macro skill 提供输入 |
| `risk-management` | 组合层面信用风险（VaR/CVaR）参考 risk-management skill |
| `equity-fundamental` | 信用分析与股权估值共享财务报表分析框架，Altman Z-Score两侧均适用 |

---

## 八、快速参考

### 常用公式速查

```
YTM 近似公式：
  YTM ≈ [C + (F-P)/n] / [(F+P)/2]

久期与价格变化：
  ΔP ≈ -D_mod × P × Δy + 0.5 × CX × P × (Δy)²

DV01 = D_mod × P × 0.0001 × 持仓面值

信用利差 = 债券YTM - 同期限国债YTM

Z-Score 风险信号：
  Z > 2.99 → 安全   1.81 < Z < 2.99 → 灰色   Z < 1.81 → 危险

违约距离 DD → EDF：
  DD > 4: EDF < 0.1%
  DD 2-4: EDF 0.1%-1%
  DD 1-2: EDF 1%-5%
  DD < 1: EDF > 5%
```

### 中国固收数据源

| 数据类型 | 推荐来源 |
|----------|----------|
| 国债收益率曲线 | 中央结算公司（CCDC）、财政部官网 |
| 信用债行情 | Wind、DM数据 |
| 城投财务数据 | 发债主体年报、Wind |
| 评级报告 | 中诚信、联合资信、东方金诚官网 |
| 违约数据 | Wind、中国债券信息网（chinamoney.com.cn） |
| ABS数据 | CNABS（中国资产证券化分析网） |
