# 路线图与进度

标记说明：

- ✅ **本次新增**：阶段 0 新写的代码 / 配置
- ♻️ **本次修改**：原本存在，阶段 0 改动了行为
- ⏸️ **原本已可用**：阶段 0 未改动，保持原样
- ❌ **未开始**：属于后续阶段

---

## 阶段 0 · 让骨架真正能跑（已完成）

| # | 任务 | 标记 | 提交 | 验收结果 |
| --- | --- | --- | --- | --- |
| 0.1 | 修 `ROOT_DIR`、统一 `data/club.db`、自动建目录 | ♻️ `main.py` · ♻️ `infrastructure/db.py` | `8c36129` | `DB_PATH` = `<仓库根>\data\club.db`；`Database(DB_PATH)` 连续两次连接均不再抛 `OperationalError`（第二次原会失败，见下方缺陷 2） |
| 0.2 | `transaction()` 改 SAVEPOINT 嵌套 + `isolation_level=None` + WAL/`busy_timeout` | ♻️ `infrastructure/db.py` | `9ad3b2d` | 新增 4 个事务用例：外层失败时内层数据消失；内层失败被外层捕获后外层仍可提交 |
| 0.3 | `close()` / `__enter__` / `__exit__` | ✅ `infrastructure/db.py` | `9ad3b2d` | 有未结束事务时 `close()` 抛 `RuntimeError`；`with Database(...)` 退出后连接已关闭 |
| 0.4 | 类型还原钩子 `_from_row` | ✅ `infrastructure/repositories.py` · ♻️ `domain/models.py` | `f9177b8` | 读回 `Member.role is Role.HR`、`join_date == date(2026, 9, 1)`；旧断言已改回 `date` |
| 0.5 | 依赖与测试配置 | ✅ `requirements.txt` · ✅ `pytest.ini` · ✅ 四个 `__init__.py` | `696a8c4` | `pytest` 从仓库根与 `tests/` 子目录运行均 16 passed |
| 0.6 | `.gitignore` 补 `data/`、`*.db`、IDE 产物；新增 `.gitattributes` | ✅ `.gitignore` · ✅ `.gitattributes` | `0a1f3ff` | `git check-ignore -v data/club.db` 命中；`git status` 干净 |
| 0.7 | README 恢复项目说明，建议原文移入 `docs/` | ♻️ `README.md` · ✅ `docs/design-notes.md` · ✅ `docs/roadmap.md` | 本次提交 | 新人按 README 三步可跑起来 |

### 阶段 0 没有改动的部分（原本已可用 ⏸️）

- `domain/models.py` 的 8 个 dataclass 与 `Role` 枚举（除 0.4 的注解修正外）
- `infrastructure/schema.sql` 的 8 张表结构
- `infrastructure/repositories.py` 的 CRUD 主体（`_create` / `_update` / `_delete` / `_list` 过滤逻辑）
- `domain/repositories.py` 的仓储抽象接口

### 阶段 0 顺带修正的既有缺陷

1. **`date` 字段的注解被自身遮蔽**（`domain/models.py`，提交 `f9177b8`）：
   `date: date = field(default_factory=date.today)` 中，CPython 会先把右边的值存入类命名空间，
   再求值左边的注解，于是注解取到的是 `Field` 对象而不是 `datetime.date`，
   导致 `Record` / `QuotaTransaction` / `InventoryTransaction` / `FundTransaction` /
   `Contribution` 的 `date` 字段无法按类型还原。现统一注解为 `datetime.date`，并加了回归测试。
2. **重复连接已存在的数据库报错**（`infrastructure/db.py`，提交 `36ec84d`）：
   `_init_schema` 每次连接都无条件执行 `schema.sql`，而建表语句不带 `IF NOT EXISTS`，
   因此第二次连接同一个库文件会抛 `table members already exists`。
   现改为「库里已有表就跳过建表」，只负责空库初始化；**修改已有表结构仍需迁移脚本或重建库文件**。

### 阶段 0 验收命令

```powershell
python -m pytest -q          # 17 passed
python -c "from main import DB_PATH; from infrastructure.db import Database; Database(DB_PATH).close()"
git diff --stat
```

---

## 阶段 1 · 打通一条业务闭环（未开始 ❌）

目标：**"记录一次打印"从头到尾能跑通，三张表严格同事务。**

1. **具体仓储**（`infrastructure/repositories.py`）：`SQLiteMemberRepo`、`SQLiteRecordRepo`、
   `SQLiteQuotaRepo`、`SQLiteFilamentRepo`、`SQLiteInventoryRepo`、`SQLiteFundRepo`，
   实现 `domain/repositories.py` 里的专用查询（`balance_of` / `stock_of` / `list_by_week` 等）；
   可在泛型基类补 `_first()` / `_scalar()` 两个小工具减少重复。
2. **权限矩阵**（`domain/permissions.py`）：表驱动 `MATRIX: dict[str, set[Role]]` + `can(role, action)`。
3. **服务层**（`domain/services.py`）：`record_print` / `purchase_filament` / `add_contribution` /
   `init_semester` / `adjust_quota` + 只读查询；所有写操作包在 `with db.transaction():` 里。
4. **装配**（`main.py`）：`build_services(db) -> dict`，供 CLI / Web / 测试复用。
5. **测试**：内存库 fixture；权限被拒、三表联动、异常后三表不留痕。

## 阶段 2 · 接口（未开始 ❌）

1. 先做 **CLI**（`interfaces/cli.py`）：活动日现场最快可用。
2. 再做 **Web**（Flask 应用工厂 `create_app()` + 蓝图 + 模板）：`flask --app interfaces.app:create_app run`。
   注意 `.flaskenv` 需要 `python-dotenv`（已写进 `requirements.txt`，当前开发机尚未安装），
   且 `FLASK_APP=app` 只有在 `interfaces/` 目录下才成立，建议改用应用工厂。
3. 最后补 `reservations`（预约排期）、`contributions`（贡献公示）与报表。

## 待决策的业务问题（不决定就没法写死服务层逻辑）

1. 额度不足时能否打印（允许透支还是拒绝）？透支后怎么补？
2. `fee` 怎么算？`is_charged` 表示已收钱还是已记账到经费？
3. `consumption` 单位与精度（克 / 米），打印失败要不要记账？
4. 一个人一天能预约几件（决定 `reservations` 的唯一约束）？
5. 经费与库存是否需要月度快照，还是永远实时 `SUM`？
6. 是否需要真正的登录（只在本机用 → 服务层校验 `operator_id` 角色即可）？
7. 退社 / 耗材停用的边界：保留历史还是加 `status` 字段？
