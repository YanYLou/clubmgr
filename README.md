# Clubmgr: A convenient tool to manage Zaomeng 3D Printing Club

![Static Badge](https://img.shields.io/badge/Status-In_development-blue)

> We take no responsibilities for any crashes.

造梦 3D 打印社团的运营管理工具：用 SQLite 记账，管理**社员、打印记录、额度、耗材库存、经费**，
另规划了预约排期与贡献奖励。定位是单机 / 局域网内部工具，不是多租户 Web 服务。

## 项目状态

标记说明：✅ 已实现并有测试 · 🟡 部分实现 · ❌ 尚未实现。

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 领域模型 `domain/models.py` | ✅ | 8 个 dataclass + `Role` 枚举，字段与建表语句一一对应 |
| 建表 `infrastructure/schema.sql` | ✅ | 8 张表；额度 / 库存 / 经费全部走流水 |
| 连接与事务 `infrastructure/db.py` | ✅ | 自动建目录、WAL、可嵌套事务（SAVEPOINT）、`close()` 守卫 |
| 泛型仓储 `SQLite3Repository` | ✅ | 反射 dataclass 字段生成 CRUD；读回时按类型还原 `Role` / `date` / `bool` |
| 具体仓储（Member / Record / 额度 / 库存 / 经费） | ❌ | 抽象接口已定义在 `domain/repositories.py`，实现属阶段 1 |
| 权限矩阵 `domain/permissions.py` | ❌ | 空文件 |
| 业务服务 `domain/services.py` | ❌ | 空壳 |
| 接口 `interfaces/app.py` | ❌ | 仅 Hello World |
| 装配 `main.py` | 🟡 | 目前只有路径常量，尚未做依赖注入 |
| 测试 | 🟡 | 数据层 17 个用例（建表与重复连接 / 事务嵌套 / 类型还原），服务层测试待补 |
| 预约、贡献、报表 | ❌ | 表已建好，逻辑未写 |

一句话：**数据层可用，业务层与界面尚未接上，应用暂时还不能对外使用。**
进度与后续计划见 [`docs/roadmap.md`](docs/roadmap.md)。

## 快速开始

```powershell
# 0. 建议先建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 1. 安装依赖
pip install -r requirements.txt

# 2. 跑测试
python -m pytest -q

# 3. 初始化数据库（首次运行会自动创建 data/club.db）
python -c "from main import DB_PATH; from infrastructure.db import Database; Database(DB_PATH).close()"
```

数据库文件固定为 `data/club.db`（见 `main.py` 的 `DB_PATH`），已被 `.gitignore` 忽略，请勿提交。

## 目录结构

```text
clubmgr/
├─ main.py                     # 路径常量，以及（阶段 1 的）依赖装配入口
├─ requirements.txt  pytest.ini  .gitattributes
├─ domain/                     # 领域层：不依赖 SQLite
│   ├─ models.py               # dataclass 与枚举
│   ├─ repositories.py         # 仓储抽象接口（ABC）
│   ├─ permissions.py          # 角色权限矩阵（待实现）
│   └─ services.py             # 业务逻辑与事务边界（待实现）
├─ infrastructure/             # 基础设施层
│   ├─ db.py                   # 连接、PRAGMA、建表、可嵌套事务
│   ├─ repositories.py         # 泛型 SQLite 仓储 + 类型还原
│   └─ schema.sql              # 建表语句
├─ interfaces/                 # 接口层（CLI / Web）
│   └─ app.py                  # Flask 骨架
├─ tests/                      # pytest 测试
└─ docs/                       # 设计文档与路线图
```

## 角色与权限

| 角色 | 职责 |
| --- | --- |
| `president` / `vice_president` | 全部权限：经费、额度调整、耗材采购 |
| `op1` | 预约安排 |
| `op2` | 打印记录、资源统计 |
| `hr` | 成员增改、退社 |
| `member` | 只看自己的额度与记录 |

权限判断放在服务层（`domain/permissions.py` + `domain/services.py`），接口层不重复判断。

## 数据模型（8 张表）

| 表 | 语义 |
| --- | --- |
| `members` | 社员（管理员也是社员，靠 `role` 区分） |
| `records` | 一条 = 一次打印（`member_id` 打印者、`operator_id` 记录人） |
| `quota_transactions` | 额度流水（`SUM(amount)` = 剩余额度） |
| `filaments` | 耗材目录 |
| `inventory_transactions` | 库存流水 |
| `fund_transactions` | 经费流水 |
| `reservations` | 活动日排期（周一 / 周三 / 周五） |
| `contributions` | 贡献 / 捐款与额度奖励 |

## 设计约定

- **一切走流水**：额度、库存、经费余额都由 `SUM(amount)` 实时算出，不存余额字段，不允许直接改余额。
- **事务边界在服务层**：仓储只执行 SQL、不提交；一次业务操作（例如记录打印要同时写 `records`、
  `quota_transactions`、`inventory_transactions`）必须包在 `with db.transaction():` 里，事务可嵌套。
- **类型还原**：写库用 `date` / `Role`，读回时由 `SQLite3Repository._from_row` 按字段类型注解还原，
  不要依赖「读出来仍是字符串」的旧行为。
- **权限**：所有写操作都要校验操作人的角色。

## 文档

- [`docs/roadmap.md`](docs/roadmap.md)：分阶段路线图与完成情况（含标记）
- [`docs/design-notes.md`](docs/design-notes.md)：早期设计建议原文（历史文档，部分已实现）
- `AGENTS.md`：协作与提交规范（本地文件，未纳入版本库）
