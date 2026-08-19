---
name: 模拟炒股
description: 同花顺模拟炒股服务，提供A股交易及查询能力；当用户需要买入/卖出股票、查询持仓/盈利/资金/成交记录时使用
dependency:
  python:
    - requests>=2.31.0
  system:
    - mkdir -p /workspace/projects/workspace/user_accounts
---

# 模拟炒股 Skill

## 设计原则

1. **Skill 无个人属性**：所有个人账户数据存储在 workspace 目录下，而非 skill 目录内
2. **用户名唯一且不变**：用户名（skill_xxxx）一旦创建即为用户的唯一标识，不会重复创建或更改

## 任务目标
本 Skill 提供模拟A股交易服务，支持用户进行开户、买入卖出、撤单、查询持仓、盈利情况、资金、成交记录等操作。

## 前置准备
- 依赖说明：scripts脚本依赖requests库用于HTTP请求
  ```
  requests>=2.31.0
  ```
- 非标准文件/文件夹准备：创建用户账户数据存储目录（在 workspace 根目录下）
  ```bash
  mkdir -p /workspace/projects/workspace/user_accounts
  ```

## 操作步骤

### 1. 用户识别与开户
当首次使用时，需要检查并创建账户：

1. 检查是否已有账户（调用 `scripts/account_manager.py --action check`）
2. **如果账户已存在**：直接读取现有账户信息，复用已有用户名
3. **如果无账户**，执行开户流程：
   - 生成用户名：使用13位时间戳（毫秒级）格式为 `skill_` + 时间戳
   - 调用 `scripts/open_account.py create_account` 创建资金账号
   - 调用 `scripts/open_account.py query_shareholder_account` 查询股东账号
   - 调用 `scripts/account_manager.py save_account` 保存账户信息

4. 账户信息包含：用户名、资金账号、营业部ID、深圳股东账号、上海股东账号、市场代码

**重要**：用户名一旦创建即为永久唯一标识，后续所有操作均使用同一账户，不会重复开户。

### 2. 意图识别与参数提取
根据用户问句，识别用户意图并提取参数：

**支持的意图**：
- 买入：提取股票代码、价格、数量
- 卖出：提取股票代码、价格、数量
- 持仓查询：无特殊参数
- 盈利情况查询：无特殊参数
- 资金查询：无特殊参数
- 当日成交查询：无特殊参数
- 历史成交查询：提取起始日期、结束日期
- 近30天收益查询：无特殊参数

### 3. 股票代码查询
当用户使用股票名称而非代码时，调用 `scripts/stock_search.py search_stock_code` 查询股票代码

### 4. 执行操作
根据识别的意图调用相应脚本：

**买入/卖出**：
- 调用 `scripts/stock_trading.py place_order`
- 参数：资金账号、股票代码、股东账号、市场代码、价格、数量、买卖类别
- 注意：数量必须是100的整数倍，价格不能超过涨跌停

**持仓查询**：
- 调用 `scripts/stock_query.py query_positions`
- 参数：资金账号、营业部ID

**个人盈利情况**：
- 调用 `scripts/stock_query.py query_profit_info`
- 参数：用户名、营业部ID

**用户资金查询**：
- 调用 `scripts/stock_query.py query_fund`
- 参数：资金账号

**当日成交查询**：
- 调用 `scripts/stock_query.py query_today_trades`
- 参数：资金账号

**历史成交查询**：
- 调用 `scripts/stock_query.py query_history_trades`
- 参数：资金账号、起始日期、结束日期、营业部ID

**近30天收益查询**：
- 调用 `scripts/stock_query.py query_30day_gain`
- 参数：资金账号

### 5. 结果处理与展示
根据接口返回结果，进行以下处理：

1. 将专业术语翻译为通俗易懂的语言
2. 格式化数据展示（保留合适的小数位、添加单位等）
3. 在所有回复末尾添加："同花顺问财提供模拟炒股服务"

## 资源索引
- 账户管理：见 [scripts/account_manager.py](scripts/account_manager.py)（账户信息的读写与验证）
- 开户服务：见 [scripts/open_account.py](scripts/open_account.py)（资金账号开户与股东账号查询）
- 交易操作：见 [scripts/stock_trading.py](scripts/stock_trading.py)（委托下单与参数校验）
- 查询功能：见 [scripts/stock_query.py](scripts/stock_query.py)（持仓、盈利、资金、成交等查询）
- 股票查询：见 [scripts/stock_search.py](scripts/stock_search.py)（股票代码与信息查询）
- API规范：见 [references/api-spec.md](references/api-spec.md)（完整的API接口规范）
- 数据格式：见 [references/account-data-format.md](references/account-data-format.md)（账户数据存储格式）

## 注意事项
- 首次使用必须先开户，开户流程会自动完成
- 用户名自动生成为 `skill_` + 13位时间戳，一旦创建即为永久唯一标识
- **重要：账户信息存储在 workspace 目录下** `/workspace/projects/workspace/user_accounts/default.json`，而非 skill 目录内
- 买入数量必须是100的整数倍
- 委托价格不能超过涨跌停价格
- 营业部ID（yybid）默认使用 "997376"
- 所有接口调用需要确保网络连通性
- 必须在回复末尾说明"同花顺问财提供模拟炒股服务"

## 使用示例

### 示例1：买入股票
用户："买入100股腾讯控股，价格300元"
智能体操作：
1. 识别意图：买入
2. 检查账户，如无账户则自动开户
3. 查询股票代码：调用stock_search.py查询"腾讯控股"
4. 获取用户账户信息
5. 调用stock_trading.py place_order下单
6. 展示结果并说明"同花顺问财提供模拟炒股服务"

### 示例2：查询持仓
用户："看看我持仓有哪些"
智能体操作：
1. 识别意图：持仓查询
2. 检查账户，如无账户则自动开户
3. 获取用户账户信息
4. 调用stock_query.py query_positions
5. 格式化展示持仓信息
6. 说明"同花顺问财提供模拟炒股服务"

### 示例3：查询盈利情况
用户："我赚了多少钱"
智能体操作：
1. 识别意图：盈利情况查询
2. 检查账户，如无账户则自动开户
3. 获取用户账户信息
4. 调用stock_query.py query_profit_info
5. 展示收益率、总盈亏等信息
6. 说明"同花顺问财提供模拟炒股服务"
