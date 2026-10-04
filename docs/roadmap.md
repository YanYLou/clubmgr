# 路线图与进度

标记说明：

- ✅ **已完成**：有对应测试
- 🟡 **部分完成**
- ❌ **未开始**
- ⏸️ **未改动**：保留原样

---

## 开工前拍板的业务结论（2026-10）

| 问题 | 结论 | 落地位置 |
| --- | --- | --- |
| 额度不足能否打印 | **允许透支**（余额可为负），但**只有社长 / 副社长能记** | `permissions.MATRIX["allow_overdraft"]`、`RecordService.record_print` |
| `records.fee` / `is_charged` 语义 | 语义未定 → **两个字段直接删除**，打印记录不记钱 | `domain/models.py`、`infrastructure/schema.sql`（结构版本 2） |
| 耗材关联 | `records` 增加 **`filament_id` 外键**，`filament_name` 保留为历史快照 | 同上 |
| `consumption` 单位 | 按**克**处理（字段注释与文档统一写"克"） | `Record.consumption` |
| 打印失败 / 废件 | 暂不记录（没有对应字段），只记成功件 | — |
| Web 端如何确定操作人 | **做用户表 + 登录界面**：账号关联社员，权限仍取自社员角色；本地测试账号 `admin / admin123` | `users` 表、`UserService`、`interfaces/views/auth.py` |
| 预约规则 | **谁都能提交预约；只有社长 / 副社长 / 运维（op1、op2）审核通过后才进排班表**。同一天同一人只能有一条已通过的排班（部分唯一索引兜底），提交本身不受限 | `reservations` 表、`ReservationService`、`permissions.MATRIX["review_reservation"]` |

仍未定的问题见文末。

---

## 阶段 0 · 让骨架真正能跑（✅ 已完成）

| # | 任务 | 标记 | 提交 | 验收结果 |
| --- | --- | --- | --- | --- |
| 0.1 | 修 `ROOT_DIR`、统一 `data/club.db`、自动建目录 | ♻️ `main.py` · ♻️ `infrastructure/db.py` | `8c36129` | `DB_PATH` = `<仓库根>\data\club.db`；连续两次连接都不再抛 `OperationalError` |
| 0.2 | `transaction()` 改 SAVEPOINT 嵌套 + `isolation_level=None` + WAL/`busy_timeout` | ♻️ `infrastructure/db.py` | `9ad3b2d` | 4 个事务用例：外层失败时内层数据消失；内层失败被外层捕获后外层仍可提交 |
| 0.3 | `close()` / `__enter__` / `__exit__` | ✅ `infrastructure/db.py` | `9ad3b2d` | 有未结束事务时 `close()` 抛 `RuntimeError` |
| 0.4 | 类型还原钩子 `_from_row` | ✅ `infrastructure/repositories.py` · ♻️ `domain/models.py` | `f9177b8` | 读回 `Member.role is Role.HR`、`join_date == date(2026, 9, 1)` |
| 0.5 | 依赖与测试配置 | ✅ `requirements.txt` · ✅ `pytest.ini` · ✅ 四个 `__init__.py` | `696a8c4` | 仓库根与 `tests/` 子目录运行均通过 |
| 0.6 | `.gitignore` 补 `data/`、`*.db`、IDE 产物；新增 `.gitattributes` | ✅ `.gitignore` · ✅ `.gitattributes` | `0a1f3ff` | `git check-ignore -v data/club.db` 命中 |
| 0.7 | README 恢复项目说明，建议原文移入 `docs/` | ♻️ `README.md` · ✅ `docs/design-notes.md` | `1aff5bc` | 新人按 README 三步可跑起来 |

### 阶段 0 顺带修正的既有缺陷

1. **`date` 字段的注解被自身遮蔽**（`domain/models.py`，`f9177b8`）：
   `date: date = field(...)` 里 CPython 先存值再求值注解，注解取到的是 `Field` 对象，
   导致 `Record` 等 5 个模型的 `date` 字段无法按类型还原。现统一注解为 `datetime.date`。
2. **重复连接已存在的数据库报错**（`infrastructure/db.py`，`36ec84d`）：
   `_init_schema` 每次连接都无条件建表，第二次连接同一个库会抛 `table members already exists`。
   现改为"库里已有表就跳过建表"。

---

## 阶段 1 · 打通一条业务闭环（✅ 已完成）

| # | 任务 | 标记 | 提交 |
| --- | --- | --- | --- |
| 1.0 | `records` 加 `filament_id`、删 `fee`/`is_charged`、补索引、结构版本 2 | ♻️ `models.py` · ♻️ `schema.sql` · ✅ `SCHEMA_VERSION` | `bd86273` |
| 1.1 | 7 个具体仓储（社员 / 打印 / 额度 / 耗材 / 库存 / 经费 / 贡献）+ `_first`/`_scalar` 等工具 | ✅ `infrastructure/repositories.py` | `65d1f3d` |
| 1.2 | 权限矩阵（11 个动作，含 `allow_overdraft`） | ✅ `domain/permissions.py` | `dd7f3cb` |
| 1.3 | 服务层：`record_print`（三表同事务）、`init_semester`、`adjust`、`purchase`、`income/expense`、贡献、报表 | ✅ `domain/services.py` | `ac42b7c` |
| 1.4 | 装配：`build_repositories` / `build_services` / `open_services` | ✅ `main.py` | `ac42b7c` |
| 1.5 | 测试：`services` / `club` fixture，权限被拒、三表联动、失败整单回滚、报表可见性 | ✅ `tests/services_test.py` | `ac42b7c` |

**阶段 1 验收**（`tests/cli_test.py::test_phase1_acceptance_via_cli` 自动跑，也可手工执行）：
建社员 → 学期初发额度 → 记录打印 → 额度 / 库存 / 经费报表。

## 阶段 2 · 接口与运维（✅ 已完成）

| # | 任务 | 标记 | 提交 |
| --- | --- | --- | --- |
| 2.1 | **CLI**：`python main.py ...`，覆盖全部业务动作，`--json` 可脚本化 | ✅ `interfaces/cli.py` | `11523bc` |
| 2.2a | **登录账号**：`users` 表 + pbkdf2 口令哈希 + `UserService`（结构版本 3） | ✅ `domain/security.py` · ✅ `interfaces/…` | `b5bc63c` |
| 2.2b | **Web 界面**：应用工厂 + 8 个蓝图 + 11 个模板 + `main.py web` | ✅ `interfaces/app.py` · ✅ `interfaces/views/` | `09b5056` |
| 2.3a | **预约数据层与服务层**：结构版本 4、`SQLiteReservationRepo`、`ReservationService`、新权限 `review_reservation` | ✅ `infrastructure/schema.sql` · ✅ `domain/services.py` | `967e448` |
| 2.3b | **预约 CLI 与 Web 页面**：`reservation` 子命令组、`/reservations`（排班表 + 提交 + 我的 + 审核队列） | ✅ `interfaces/cli.py` · ✅ `interfaces/views/reservations.py` | `8ea2297` · `6149ef9` |
| 2.4 | **体检与热备份**：`doctor`（版本/完整性/外键/可疑数据）、`backup`（在线备份 + 校验 + 保留份数） | ✅ `infrastructure/backup.py` · ✅ CLI | `a4862e1` |
| 2.5 | **公示报表与维护页**：`report export`（Markdown + CSV）、Web `/admin`（备份 + 下载）、CI | ✅ `interfaces/reports.py` · ✅ `interfaces/views/admin.py` · ✅ `.github/workflows/tests.yml` | `8bba930` |

**阶段 2 完成**：社员 / 打印 / 额度 / 库存 / 经费 / 贡献 / 预约 / 公示 / 备份 / 体检 全部打通，
命令行与 Web 双入口，123 个测试 + CI。剩下的是"上生产"（换 WSGI 服务器）与文末的可选优化。

Web 端要点：账号只是"证明你是哪个社员"，权限仍取自该社员的角色；会话里只放 `user_id`，
每个请求重新取角色；SQLite 单连接跨线程 + 一把请求锁串行化；会话密钥取
`CLUBMGR_SECRET_KEY`，否则生成 `data/secret_key` 复用。

## 阶段 3 · 排班与权限改造（🟡 进行中）

按 2026-10-04 的 9 个选择题答案实施（原话与完整结论见本地笔记 `.agent-notes/handoff/03-待实现需求.md`）。

| # | 任务 | 标记 | 提交 |
| --- | --- | --- | --- |
| 3.1 | **角色与权限**：副社长分 1/2 号（管理页只给 1 号）、新增 `teacher`（与社长同级）、两位运营权限完全共享、`Role.parse` 兼容旧值 | ✅ `domain/models.py` · ✅ `domain/permissions.py` | `b310cdb` |
| 3.2 | **全局低库存阈值 + 站内通知**：`settings` + `notifications` 两张表、出库跨阈值告警两位运营、通知页与告警条、`notify`/`settings` 命令、`doctor` 提示 | ✅ `domain/services.py` · ✅ `interfaces/views/notifications.py` · ✅ CLI | `b064f37` · `f2ef237` |
| 3.3 | **打印机资源**：3 台，状态 空闲 / 使用中 / 维修中；老师与运营可标记使用、社长副社长老师可标维修；可用台数实时可见并供排班算容量 | ✅ `printers` 表 · ✅ `PrinterService` · ✅ Web `/printers` · ✅ CLI `printer` | `b0f5563` |
| 3.4 | **紧急任务**：`reservation urgent`（提到本周 + 插到最前面，当天其他人顺延并收到通知）、`bump`（挤掉 → 待重排 + 通知本人）、留痕 `urgent_by/reason/at`、Web 紧急区与待重排区 | ✅ `ReservationService` · ✅ Web · ✅ CLI | `1eca770` |
| 3.5 | **自助注册**：`/signup` 填资料 → 待人事审核 → 通过后才能登录；`approve_signup` 权限（人事 + 社长 / 副社长 / 老师）；驳回保留记录 | ✅ `UserService.signup/approve_signup` · ✅ Web · ✅ CLI | `8455814` |
| 3.6 | **时间格排班**：可编辑时间格（默认 16:55–17:40）、容量按可用打印机台数、手工排 + 一键填充 | ❌ | — |

### 阶段 3 的权限现状（3.1 完成后）

| 角色 | 业务权限 | 管理页 / 账号页 |
| --- | --- | --- |
| `president` 社长 | 全部 | ✅ |
| `vice_president_1` 副社长1号 | 全部 | ✅ |
| `vice_president_2` 副社长2号 | 全部 | ❌ |
| `teacher` 老师 | 全部（与社长同级） | ✅ |
| `op1` / `op2` 两位运营 | 完全一致：记打印、审核预约、排班、看库存与打印记录 | ❌ |
| `hr` 人事 | 成员增改 / 退社 / 看名册 | ❌ |
| `member` 社员 | 自己的额度与记录、自己提交预约 | ❌ |

## 待决策 / 可选的后续问题

1. 经费与库存要不要**月度快照表**？目前一律实时 `SUM`，数据量小够用。
2. 社员自助查额度已经能用 Web 登录实现（`member` 角色只能看自己）；
   是否还需要"不登录也能查自己额度"的匿名入口？
3. **耗材停用的边界**：删除还是加 `status` 字段（社员退社已定为只改 `status`）。
4. 打印**失败 / 废件**要不要记（若要记，需要加字段并定"是否扣额度"）。
5. 预约要不要**跨周限制**（例如只能约本周 / 下周）与**取消时限**？现在是随时可约、随时可撤。
