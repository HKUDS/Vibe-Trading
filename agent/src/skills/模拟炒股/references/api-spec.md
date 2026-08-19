# 模拟炒股API接口规范

## 目录
1. [接口基础信息](#接口基础信息)
2. [开户相关接口](#开户相关接口)
3. [交易接口](#交易接口)
4. [查询接口](#查询接口)
5. [错误码说明](#错误码说明)

## 接口基础信息

### 基础URL
- 正式环境：`http://trade.10jqka.com.cn:8088`
- 测试环境：`http://mntest.10jqka.com.cn:8088`

### 通用参数
- `yybid`（营业部ID）：默认值 `997376`
- `datatype`：固定值 `json`
- `Content-Type`：固定值 `application/json`

### 通用返回格式
所有接口返回JSON格式，包含以下字段：
- `code` / `errorcode`：状态码（0表示成功）
- `msg` / `errormsg`：状态信息

## 开户相关接口

### 1. 资金账号开户

**接口路径**：`GET /pt_add_user`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrname | string | 是 | 用户名 |
| yybid | string | 是 | 营业部ID（默认997376） |
| datatype | string | 否 | 固定值json |

**请求示例**：
```
http://trade.10jqka.com.cn:8088/pt_add_user?usrname=skill_1705399200000&yybid=997376&datatype=json
```

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | number | 状态码（0成功） |
| errormsg | string | 资金账号 |

**示例**：
```json
{
    "errorcode": 0,
    "errormsg": "51695817"
}
```

### 2. 股东账号查询

**接口路径**：`GET /pt_qry_stkaccount_dklc`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrid | string | 是 | 资金账号 |
| yybid | string | 是 | 营业部ID（默认997376） |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | string | 状态码（0成功） |
| errormsg | string | 错误信息 |
| result | array | 股东账号列表 |
| result[].usrid | string | 资金账号 |
| result[].gddm | string | 股东账号 |
| result[].scdm | string | 市场代码（1：深圳；2：上海） |

**示例**：
```json
{
    "errorcode": 0,
    "errormsg": "",
    "result": [
        {
            "usrid": "51695817",
            "gddm": "A427829832",
            "scdm": "2",
            "wfjg": "1",
            "notice": ""
        },
        {
            "usrid": "51695817",
            "gddm": "00102550407",
            "scdm": "1",
            "wfjg": "1",
            "notice": ""
        }
    ]
}
```

## 交易接口

### 1. 委托下单

**接口路径**：`GET /pt_stk_weituo_dklc`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrid | string | 是 | 资金账号 |
| zqdm | string | 是 | 股票代码 |
| gddh | string | 是 | 股东账号 |
| scdm | string | 是 | 市场代码（1：深圳；2：上海） |
| yybd | string | 是 | 营业部ID（默认997376） |
| wtjg | string | 是 | 委托价格 |
| wtsl | string | 是 | 委托数量（必须是100的整数倍） |
| mmlb | string | 是 | 买卖类别（B：买入；S：卖出） |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | number | 状态码（0成功） |
| errormsg | string | 错误信息 |
| result | object | 委托结果 |
| result.userid | string | 资金账号 |
| result.gdh | string | 股东账号 |
| result.scdm | string | 市场代码 |

**注意事项**：
- 委托数量必须是100的整数倍
- 委托价格不能超过涨跌停价格

## 查询接口

### 1. 持仓查询

**接口路径**：`GET /pt_web_qy_stock`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 资金账号 |
| yybid | string | 是 | 营业部ID（默认997376） |
| type | string | 是 | 1表示资金账号 |
| datatype | string | 是 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | number | 状态码（0成功） |
| errormsg | string | 错误信息 |
| data | array | 持仓列表 |
| data[].zqdm | string | 股票代码 |
| data[].zqmc | string | 股票名称 |
| data[].gpsl | number | 股票数量 |
| data[].kysl | number | 可用数量 |
| data[].gpcb | string | 股票成本 |
| data[].fdyk | string | 浮动盈亏 |
| data[].ydl | string | 盈亏率 |
| data[].gpz | string | 股票市值 |

### 2. 个人盈利情况查询

**接口路径**：`GET /pt_qry_userinfo_v1`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrname | string | 是 | 用户名 |
| yybid | string | 是 | 营业部ID（默认997376） |
| type | string | 否 | 是否仅查询用户资金账号 |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| error_no | string | 状态码（0成功） |
| error_info | string | 错误信息 |
| list | array | 盈利信息列表 |
| list[].syyk | string | 实现盈亏 |
| list[].zzc | number | 总资产 |
| list[].syl | string | 总收益率 |
| list[].syl0 | string | 日收益率 |
| list[].syl1 | string | 周收益率 |
| list[].syl2 | string | 月收益率 |
| list[].dw | string | 段位 |
| list[].cw | string | 仓位 |

### 3. 用户资金查询

**接口路径**：`GET /pt_qry_fund_t`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usid | string | 是 | 资金账号 |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errormsg | string | 错误信息 |
| result | object | 资金信息 |
| result.list | array | 资金列表 |
| result.list[].usrid | string | 资金账号 |
| result.list[].zjye | string | 资金余额 |
| result.list[].kyje | string | 可用金额 |
| result.list[].dje | string | 冻结金额 |

### 4. 当日成交查询

**接口路径**：`GET /pt_qry_busin_nocache`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrid | string | 是 | 资金账号 |
| kind | integer | 是 | 1表示资金账号，2表示userid |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| ret.code | string | 状态码（0成功） |
| ret.msg | string | 错误信息 |
| ret.item | array | 成交记录列表 |
| ret.item[].zqdm | string | 股票代码 |
| ret.item[].zqmc | string | 股票名称 |
| ret.item[].mmlb | string | 买卖类别 |
| ret.item[].cjg | string | 成交价格 |
| ret.item[].cje | string | 成交金额 |
| ret.item[].cjsj | string | 成交时间 |
| ret.item[].fee | string | 手续费 |

### 5. 历史成交查询

**接口路径**：`GET /pt_qry_busin1`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrid | string | 是 | 资金账号 |
| start | string | 是 | 开始日期（格式：YYYYMMDD） |
| end | string | 是 | 结束日期（格式：YYYYMMDD） |
| yhbId | string | 是 | 营业部ID（默认997376） |
| kind | string | 是 | 1表示资金账号 |
| datatype | string | 否 | 固定值json |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | number | 状态码（0成功） |
| errormsg | string | 错误信息 |
| list | array | 成交记录列表 |
| list[].zqdm | string | 股票代码 |
| list[].zqmc | string | 股票名称 |
| list[].mmlb | string | 买入/卖出 |
| list[].cjj | string | 成交价格 |
| list[].cje | string | 成交金额 |
| list[].cjsl | string | 成交数量 |
| list[].cjsj | string | 成交时间 |
| list[].fee | string | 手续费 |

### 6. 近30天收益查询

**接口路径**：`GET /pt_qry_gainstat`

**请求参数**：
| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| usrid | string | 是 | 资金账号 |

**返回参数**：
| 参数名 | 类型 | 说明 |
|--------|------|------|
| errorcode | string | 状态码（0成功） |
| erromsg | string | 错误信息 |
| data | object | 收益信息 |
| data.sy30 | string | 近30日收益率 |
| data.syk | string | 总盈亏 |
| data.ssyk | string | 实现盈亏 |
| data.fdyk | string | 浮动盈亏 |
| data.zjye | string | 资金余额 |
| data.zzc | string | 总资产 |
| data.syl | string | 总收益率 |
| data.sy0 | string | 日收益率 |
| data.sy1 | string | 周收益率 |
| data.sy2 | string | 月收益率 |

## 请求头配置

所有请求需要设置以下请求头：

```
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
```

## 错误码说明

### 通用错误码
| 错误码 | 说明 |
|--------|------|
| 0 | 成功 |
| -1 | 失败 |

### 注意事项
1. 所有接口调用需要确保网络连通性
2. 营业部ID（yybid）默认使用997376
3. 委托数量必须是100的整数倍
4. 日期格式统一使用YYYYMMDD
5. 市场代码：1表示深圳，2表示上海
