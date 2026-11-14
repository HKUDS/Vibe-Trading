# 网关复杂场景验收（2026-11-14）

本轮约束：8 MiB 内存缓存、64 MiB 磁盘缓存、4 个源工作槽、16 个待处理请求、256 MiB 历史空间均不增加。真实网络结果与可控故障回归分开；本机可用不代表所有地区可用。行内的真实分项并不代表该行全部并发条件都已通过；v15 的 114.81 分钟整轮 26 项验收检查通过；额外历史子任务仍有 4 次未在 90 秒测试窗口完成；以下仍区分真实结果、受控故障和能力边界，不等于所有地区/行情类型无条件可用。

| # | 难度递增的用户场景 | 验收重点 | 本轮结果 |
|---|---|---|---|
| 1 | 美股双标的跨五年下载月线，同时读取日线和已有缓存 | 大跨度分块、实际来源、端点日期 | v14 重新下载并通过生产日历校验：122 条/12 块，双标的各 61 个应有月份；8.962 s，状态 complete。旧 v13 仅独立核对，现已接入生产；日历校验不冒充价格审计 |
| 2 | 港股、加拿大、英国混合下载，两客户端重复读取 | 各自路由、币种保持、重复请求不重复拉源 | v14 重新下载通过：158 条，HK/CA/UK 各 52/52/54 个交易日，4.530 s，生产状态 complete；HK 的 Tencent/Eastmoney 失败后 Yahoo 接续。API/CLI/Agent/MCP 跨 CAD→GBP 页面与日历元数据一致，未知单位仍为 null |
| 3 | 双美股跨周一分钟线，含周末与非交易时段 | 不制造周末空块，不拿近期尾部代替请求历史 | v14 重新下载 11700 条/12 页，6.564 s，生产状态 complete；每标的 5850 个常规分钟全部匹配。两个 21:00 UTC、OHLC 相等且零成交量的收盘点明确排除并记录；有成交量的额外点仍拒绝 |
| 4 | BTC 与 ETH 一分钟整日下载，并分页读取 | 连续时间网格、全量条数、非抽样 | 真实：2880 条/3 页，2.593 s；连续网格通过 |
| 5 | 日线、周线、月线混合订阅及重复打开图表 | 大小写周期正确、共享底层日线、不重复累积 | 首次实测超时；修后 8×3 全部返回，8.006/6.386/6.366 s |
| 6 | 多客户端同时首次请求同一期权链，随后各自修改展示结果 | 请求合并、结果互不污染、完整到期链 | 真实：12/12 成功，1 次采集，330 合约；另有隔离性回归 |
| 7 | 期权缓存过期时十个客户端同时刷新，源响应较慢 | 立即返回标明过期的快照，只启动一次刷新 | 真实 SPY 链：10 个读取约 42 ms 返回，仅 1 次后台刷新；缩短 TTL 计时 |
| 8 | 重启后读磁盘缓存，再持续写入直到触及配额 | 冷启动复用、逐出、字节与条数双上限 | 真实子进程重启命中缓存，0 次拉源；另用 2880 条真实记录重放填满默认缓存，178 项/63.66 MiB 时逐出，内存 ≤8 MiB，闲置归零 |
| 9 | 所有页面关闭后无任何新请求，磁盘仍新鲜 | 内存静默删除；磁盘故障也不妨碍清理 | 真实链缓存从 98525 B 清到 0，磁盘保留；缩短闲置计时，磁盘故障为受控分项 |
| 10 | 一批八只中部分缺失，但后面还有健康批次 | 成功数据保留、失败独立重试、不冻结全队列 | 真实：首只无数据，其他 7 只保留；队列独立重试回归通过 |
| 11 | 首选源断线、备用成功，随后换标的并恢复首选源 | 熔断范围正确、健康记忆过期、重新探测 | 真实：Stooq 不可用后双美股转 Yahoo，来源明确；恢复分项通过 |
| 12 | 各源都失败，退避累积后网络恢复 | 不请求风暴、半开探测、旧冷却不永久锁死 | 真实源故障注入：保留 2 块，恢复 1 次后 122 条；半开/限流分项通过 |
| 13 | WebSocket 断线但 REST 可用，随后推送恢复 | REST 接续、恢复后停止重复轮询、来源一致 | 真实 WS/REST 恢复通过：v13 混合客户端 BTC/ETH 各 10 次 REST 快照及 121/120 次 WS 快照；长测 65 次真实上游连接全部关闭，故障错误明确呈现 |
| 14 | 新请求超过待处理上限，同时有超时但未退出的 SDK | 队列有限、实际源槽不提前归还、不补线程 | 受控边界通过（3 项），不以模拟数据代替真实下载成绩 |
| 15 | 重复订阅/退订时请求还在排队或运行 | 取消排队项、运行中保留槽、释放快照对象 | 受控取消边界及真实长测通过：1447 次订阅/1447 次退订，最后客户端、主题、待推送更新全部为 0；在途源退出前不提前归还容量 |
| 16 | 慢客户端不读取，其他客户端正常订阅同主题 | 只保留最新快照、共享采集、容量拒绝原子性 | 受控慢消费者/原子容量拒绝通过；v13 全程另挂不消费客户端，其他 64 主题仍刷新，结束后积压归零 |
| 17 | 大批后台扫描和历史下载同时运行，前台继续刷新 | 前台协调资源保留、串行 SDK 公平调度 | 真实 v15 重叠负载通过：587 个采样点同时有 64 主题、扫描、历史下载；前台无非预期 HTTP/读取错误。后台仍有排队：一次月线分块等协调槽约 11–12 秒，累计超过子任务 90 秒窗口，明确保留为暂停，不算完整成功 |
| 18 | 同一链里混入错标的、错到期、交叉报价、NaN 或布尔价格 | 拒绝脏数据、不缓存为有效行情、不污染其他标的 | 受控脏数据拒绝通过（9 项）；这是输入防护测试，无需污染公共源来验证 |
| 19 | 日线源伪装成小时线，或连续市场缺首尾/中间/重复时间 | 周期和时间网格拦截、不以非空冒充完整 | 受控网格/周期拒绝通过（26 项），真实多年数据另作全量校验 |
| 20 | 下载途中切源，出现不同币种、复权、成交量单位或交易所 | 不拼接不兼容序列，保留失败证据 | 受控边界通过（2 项），不宣称公共源自然触发了这些罕见故障 |
| 21 | 加密货币日线跨 UTC/UTC+8 边界，恢复旧格式任务 | 时间相位一致，未收盘日不可标完整 | 真实：未收盘网格缺口明确失败，无假完整；相位恢复分项通过 |
| 22 | 请求几十年历史，或多币多年一分钟造成超多分块 | 长周期可用、4096 分块/100 标的边界仍拦截 | v14 三十年月线重新下载并通过生产日历校验：722 条/62 块，各 361 个应有月份；43.533 s，状态 complete。4096 块/100 标的边界回归仍拒绝超限 |
| 23 | 下载中断后重启，已有分块中有损坏文件 | 校验后跳过好块、重拉坏块、分页无重无漏 | 真实：进程 kill -9 + 坏块修复；64 块/746 条；好块哈希保持，预留归零 |
| 24 | 暂停发生在一个源失败后、切换下个源前 | 停止下一次采集、释放预留、保留已完成前缀 | 受控边界通过（2 项），不宣称公共源自然触发了这些罕见故障 |
| 25 | 固定保留与过期数据混合，空间不足或压缩输出超限 | 不删除固定项、不越配额、不留假完成状态 | 受控边界通过（3 项），不以模拟数据代替真实下载成绩 |
| 26 | 两个进程同时写、恢复或删除同一历史任务 | 文件租约、跨实例预留、锁等待有界 | 真实 spawn 双进程通过：在途任务不被新实例回收、重复运行/删除被拒绝、跨进程暂停保留 1 块，再续传全部 6 块；数据为受控 fixture，另有配额/锁等待回归 |
| 27 | API/CLI/Agent 同时访问大任务清单、分页与非法路径 | 认证、入口一致、输出受限、本地路径拒绝 | 真实 HTTP、应用 CLI、Agent 工具并发读取，以及真实注册表的 MCP 协议会话：v14 的 25 条跨 CAD→GBP 分块记录、interval 与 provenance（含 calendar/version/coverage）完全一致，非法路径均拒绝；同一哈希 286f7d05702a8467…；大记录分页不截 JSON，单行超预算明确拒绝 |
| 28 | 同一客户端混合六市场股票/加密币、不同周期、期权和多年下载，并持续接收部分行情 | 身份币种不混淆、不同时间范围并行、WS/REST 故障隔离 | v15 三类并发冷请求 90/90 首次完整，全部缓存未命中、无客户端重试；六市场中位 6.796 s / 最慢 11.519 s，月线最慢 8.890 s，分钟线最慢 11.217 s。另一次真实源预置冷却实测在原请求内补齐 A 股缺项，6 市场 5.841 s；长测 45 次额外历史子任务中 41 完整、4 超时窗暂停，保留队列/源故障证据，不声称全部尝试成功 |
| 29 | 64 主题 + 新路由历史 + 30 轮断网/退订持续至少一小时 | 整进程及子进程内存、读取错误、闲置释放 | v15 同一 PID 活跃 114.81 分钟：64 主题、30 轮故障、1449 对订阅/退订；前台读取/驱动/清理错误 0。主进程峰值 197.49 MiB、闲置 170.41 MiB，进程树实测峰值 567.85 MiB；后 30 分钟斜率 -0.234 MiB/min，但第 30 分钟以来整体仍 +0.166，不能称全程平坦。闲置 190 秒后 RAM 缓存/订阅/上游 WS/源请求/历史预留清零；36 个记录 PID 全部退出 |
| 30 | 同上述负载同时扫描 5224 只，小时结束仍未完成就继续 | 5224 实际获取、失败清单、耗时拆分、不增限额 | v15 5224/5224 实际获取、最终失败 0；729 批、606 次重试，采集 89.03 分钟 + 退避 25.67 分钟。十只股票五年 5m 完成 610 块 / 581760 条，退出后新查日历并逐块/逐条/582 页独立核对通过；15m 在收尾主动暂停于 145 块 / 46128 条，不能计为完整。8/64 MiB 缓存、4 个源工作槽、16 待处理、256 MiB 历史配额均未增加 |

测试方法说明：能够稳定构造的罕见故障采用受控注入；不是人为向公共数据源发送坏请求。跨地区真实连通性需要对应地区运行节点，本机源失败/恢复仅验证路由机制。

场景 28 的客户端传输为 SSE；加密上游为 WebSocket，股票/期权仍为轮询快照。场景 27 验证新增历史入口，未声称旧研究/回测全部迁移；MCP 使用内存协议传输，未另测 stdio/TCP。缓存填充使用真实数据重放，不代表 288 次独立行情采集；闲置阈值 120 秒未改，逐出方法手动每秒调用，定时线程另有独立实测。


2026-11-15 v16 短测补充（没有重复一小时验收）：针对 17/28 的后台排队与恢复，
扫描在源调用之间协作让出协调线程，历史与行情共用源级冷却，移除重复的请求失败缓存；
五年月线减少冗余分块。64 主题 + 扫描队列 + 多年历史持续 9.53 分钟、4 轮故障：
5/5 路由历史任务完整，月线 10.039/3.138 s，HK/CA/UK 日线 3.238 s，
BTC/ETH 分钟线 4.027 s，美股分钟线含断网恢复 41.437 s；均低于原 90 秒窗口。
12/12 并发冷请求首次完整，最长 12.960 s；166 项不同自动回归通过。
扫描只获取 318/5224 后主动取消，大历史仅保留 76 块且最终断网失败状态未补跑，
不能替代 29/30 的 v15 全量结果；限额未增加，三分钟自然清理及七个 PID 退出已核对。

### v17 follow-up: automatic historical recovery

A separate 46.53-second real-source probe now covers the previously missing
product behavior: one initial start, transient failure after a committed chunk,
transport restoration, and production-owned continuation with no further resume
API calls. Both five-year monthly symbols completed (122 verified rows), the
first chunk was unchanged, and 64 topics plus the full scan queue remained active
as background load. The short scan ended at 112/5,224 intentionally. This adds
recovery coverage; it is not another full scan/hour acceptance. See VALIDATION.md
v17 for limits, classified failures, UI/build checks and raw evidence.

### v18 follow-up: application close and reopen

Production startup now resumes eligible unfinished work without a history-page
visit. Real-source normal-close and forced-kill tests completed in 6.54 and 5.69
seconds total; both restarted services completed acquisition about 3.6 seconds
after launch. Each returned 183 verified monthly rows, reused the committed
prefix, and made no source calls for manually paused or never-started jobs.
No post-restart resume API call or resource-limit increase was used. See v18 in
VALIDATION.md for the shutdown race found and fixed, scope and raw evidence.

### v19 follow-up: multi-year minute data and mixed restart load

One complete five-year 5m series survived four alternating normal/forced restarts
while default-budget 16-topic streaming and a 5,224-symbol scan queue were active.
The 3m19s test verified all 61 chunks / 58,176 rows against independent full-range
calendar/status data and all HTTP pages. No committed chunk was re-fetched; only
four uncommitted interrupted results were reacquired. The manually paused task
made zero history calls. Every process delivered live WebSocket updates and scan
progress. Resource limits were unchanged; scan prefixes are not full scan coverage.
See VALIDATION.md v19 for the exact scope and evidence.

### v20 follow-up: ten separate jobs, bounded admission and fairness

The old implementation rejected starts 5–10 and monopolized its worker for a
whole dataset. Accepted work now waits in the existing 32-job catalog, with one
chunk per turn and unchanged one-worker/four-future bounds. In a 4m24s mixed test,
all ten five-year requests made progress; after pausing one running, one executor-
queued and one disk-waiting job, all seven others advanced after each of three
restarts. Verified 58/610 planned chunks (51,600 rows) across ten continuous
prefixes, zero committed re-fetches and zero post-pause calls. This is not a full
ten-dataset completion claim. Real WebSocket updates continued, but scanning had
missing-symbol and 15-second-deadline retries; see v20 VALIDATION.md for retained
errors, resource observations and exact evidence.
