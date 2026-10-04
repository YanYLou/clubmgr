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

## 阶段 2 · 接口（🟡 进行中）

| # | 任务 | 标记 | 提交 |
| --- | --- | --- | --- |
| 2.1 | **CLI**：`python main.py ...`，覆盖全部业务动作，`--json` 可脚本化 | ✅ `interfaces/cli.py` | `11523bc` |
| 2.2 | **Web**：Flask 应用工厂 `create_app()` + 蓝图 + 模板 | ❌ | — |
| 2.3 | `reservations` 预约排期（仓储 + 服务 + CLI 子命令） | ❌ | — |
| 2.4 | 备份脚本（`Connection.backup()` 热备份，按日期保留） | ❌ | — |

Web 注意事项：`.flaskenv` 里的 `FLASK_APP=app` 只在 `interfaces/` 目录下成立，
且需要 `python-dotenv`（已写进 `requirements.txt`，开发机尚未安装）；
建议改用 `flask --app interfaces.app:create_app run`。

## 待决策的业务问题

1. **一个人一天能约几件**？决定 `reservations` 的唯一约束（阶段 2.3 开工前需要）。
2. 经费与库存要不要**月度快照表**？目前一律实时 `SUM`，数据量小够用。
3. 是否需要**真正的登录**？现在只在本机用，服务层校验 `operator_id` 的角色即可；
   要让社员自己上网页查额度就必须做身份认证。
4. **耗材停用的边界**：删除还是加 `status` 字段（社员退社已定为只改 `status`）。
5. 打印**失败 / 废件**要不要记（若要记，需要加字段并定"是否扣额度"）。
