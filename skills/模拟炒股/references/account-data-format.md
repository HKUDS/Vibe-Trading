# 账户数据格式规范

## 目录
1. [数据结构](#数据结构)
2. [字段说明](#字段说明)
3. [存储位置](#存储位置)
4. [使用示例](#使用示例)

## 数据结构

账户信息使用JSON格式存储，结构如下：

```json
{
  "username": "用户名",
  "capital_account": "资金账号",
  "department_id": "营业部ID",
  "shareholder_accounts": {
    "sz": "深圳股东账号",
    "sh": "上海股东账号"
  },
  "market_codes": {
    "sz": "1",
    "sh": "2"
  },
  "created_at": "账户创建时间（ISO 8601格式）",
  "updated_at": "账户更新时间（ISO 8601格式）"
}
```

## 字段说明

### 必填字段

#### username
- **类型**：string
- **说明**：用户名，自动生成
- **格式**：`skill_` + 13位时间戳（毫秒级）
- **示例**："skill_1705399200000"
- **生成逻辑**：使用Python的 `int(time.time() * 1000)` 生成13位时间戳
- **用途**：在API调用中使用，作为用户唯一标识

#### capital_account
- **类型**：string
- **说明**：资金账号，由开户接口返回
- **示例**："51695817"
- **用途**：作为交易和查询的主要凭证

#### department_id
- **类型**：string
- **说明**：营业部ID
- **示例**："997376"
- **默认值**："997376"
- **用途**：用于区分不同的营业部/比赛

### 股东账号相关字段

#### shareholder_accounts
- **类型**：object
- **说明**：股东账号映射表
- **结构**：
  ```json
  {
    "sz": "深圳股东账号",
    "sh": "上海股东账号"
  }
  ```
- **说明**：
  - `sz`：深圳交易所股东账号
  - `sh`：上海交易所股东账号
- **示例**：
  ```json
  {
    "sz": "00102550407",
    "sh": "A427829832"
  }
  ```

#### market_codes
- **类型**：object
- **说明**：市场代码映射表
- **结构**：
  ```json
  {
    "sz": "1",
    "sh": "2"
  }
  ```
- **说明**：
  - `sz`：深圳交易所代码（固定为"1"）
  - `sh`：上海交易所代码（固定为"2"）

### 时间戳字段

#### created_at
- **类型**：string
- **说明**：账户创建时间
- **格式**：ISO 8601（YYYY-MM-DDTHH:MM:SS.sssZ）
- **示例**："2024-01-16T10:00:00.000Z"

#### updated_at
- **类型**：string
- **说明**：账户最后更新时间
- **格式**：ISO 8601（YYYY-MM-DDTHH:MM:SS.sssZ）
- **示例**："2024-01-16T10:00:00.000Z"

## 存储位置

### 目录结构
```
./user_accounts/
└── default.json
```

### 文件命名规则
- **格式**：`default.json`
- **说明**：所有账户信息存储在固定的 `default.json` 文件中

### 创建目录
在使用Skill前，需要确保账户目录存在：
```bash
mkdir -p ./user_accounts
```

## 使用示例

### 示例1：完整账户信息

```json
{
  "username": "skill_1705399200000",
  "capital_account": "51695817",
  "department_id": "997376",
  "shareholder_accounts": {
    "sz": "00102550407",
    "sh": "A427829832"
  },
  "market_codes": {
    "sz": "1",
    "sh": "2"
  },
  "created_at": "2024-01-16T10:00:00.000Z",
  "updated_at": "2024-01-16T10:00:00.000Z"
}
```

### 示例2：仅深圳股东账号

```json
{
  "username": "skill_1705399300000",
  "capital_account": "51703074",
  "department_id": "997376",
  "shareholder_accounts": {
    "sz": "00203050506"
  },
  "market_codes": {
    "sz": "1"
  },
  "created_at": "2024-01-16T11:00:00.000Z",
  "updated_at": "2024-01-16T11:00:00.000Z"
}
```

### 示例3：生成用户名

```python
import time

# 生成13位时间戳（毫秒级）
timestamp = int(time.time() * 1000)
username = f"skill_{timestamp}"
print(f"生成的用户名: {username}")
# 输出示例：skill_1705399200000
```

### 示例4：读取账户信息

```python
from scripts.account_manager import AccountManager

manager = AccountManager()
account = manager.read_account()

if account:
    print(f"用户名: {account['username']}")
    print(f"资金账号: {account['capital_account']}")
    print(f"深圳股东账号: {account['shareholder_accounts']['sz']}")
    print(f"上海股东账号: {account['shareholder_accounts']['sh']}")
else:
    print("账户不存在")
```

### 示例5：保存账户信息

```python
from scripts.account_manager import AccountManager
from datetime import datetime
import time

manager = AccountManager()

# 生成用户名
timestamp = int(time.time() * 1000)
username = f"skill_{timestamp}"

account_data = {
    "username": username,
    "capital_account": "51695817",
    "department_id": "997376",
    "shareholder_accounts": {
        "sz": "00102550407",
        "sh": "A427829832"
    },
    "market_codes": {
        "sz": "1",
        "sh": "2"
    },
    "created_at": datetime.now().isoformat(),
    "updated_at": datetime.now().isoformat()
}

manager.save_account(account_data)
```

### 示例6：自动开户流程

```python
from scripts.account_manager import AccountManager
from scripts.open_account import OpenAccountService
from datetime import datetime
import time

# 初始化
account_manager = AccountManager()
open_account_service = OpenAccountService()

# 1. 检查账户是否存在
if not account_manager.check_account_exists():
    # 2. 生成用户名
    username = account_manager.generate_username()
    
    # 3. 开户
    create_result = open_account_service.create_account(username)
    
    # 4. 查询股东账号
    shareholder_result = open_account_service.query_shareholder_account(
        create_result["capital_account"]
    )
    
    # 5. 保存账户信息
    account_data = {
        "username": username,
        "capital_account": create_result["capital_account"],
        "department_id": create_result["department_id"],
        "shareholder_accounts": shareholder_result["shareholder_accounts"],
        "market_codes": shareholder_result["market_codes"],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    account_manager.save_account(account_data)
    print("开户成功")
else:
    print("账户已存在")
```

## 注意事项

1. **用户名生成**：用户名必须遵循 `skill_` + 13位时间戳的格式
2. **单账户模式**：所有操作使用同一个默认账户文件 `default.json`
3. **完整性**：必填字段必须提供，否则脚本可能报错
4. **一致性**：shareholder_accounts和market_codes的字段键必须一致（sz/sh）
5. **时间格式**：created_at和updated_at必须使用ISO 8601格式
6. **文件权限**：确保运行环境对./user_accounts目录有读写权限
7. **备份**：建议定期备份账户数据文件
8. **安全性**：账户信息包含敏感数据，注意保护文件安全

## 验证规则

### 必填字段检查
- username：非空字符串，格式为 `skill_` + 13位数字
- capital_account：非空字符串
- department_id：非空字符串

### 用户名格式验证
```python
import re

def validate_username(username: str) -> bool:
    """验证用户名格式"""
    pattern = r'^skill_\d{13}$'
    return bool(re.match(pattern, username))

# 示例
print(validate_username("skill_1705399200000"))  # True
print(validate_username("skill_123"))  # False
print(validate_username("user_1705399200000"))  # False
```

### 股东账号检查
- shareholder_accounts：至少包含一个市场账号
- market_codes：与shareholder_accounts字段键一致

### 市场代码验证
- sz的市场代码必须是"1"
- sh的市场代码必须是"2"
