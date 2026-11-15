# clubmgr

3D 打印社团（俱乐部）管理系统。用于管理社员、打印记录和预约安排。

## 分层架构

依赖方向：`interfaces → services → (repositories 接口 + permissions) → models`；`infrastructure` 实现 `domain` 的接口。

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 领域层 | `domain/` | 数据模型、仓储抽象接口、权限矩阵、业务服务 |
| 基础设施层 | `infrastructure/` | SQLite 连接、建表、仓储具体实现 |
| 接口层 | `interfaces/` | Flask / CLI 薄接口，只调用 service |
| 组合根 | `main.py` | 创建 `Database` 和仓储，注入 service |

## 目录结构

```text
E:\CLUBMGR
│  main.py                    # 路径常量 + 依赖组装 build_services()
├─domain
│      models.py              # 数据类 + 枚举
│      repositories.py        # 仓储抽象接口 ABC
│      permissions.py         # 角色权限矩阵（can / require）
│      services.py            # 业务逻辑 + 权限校验入口
├─infrastructure
│      db.py                  # Database、建表、事务
│      repositories.py        # SQLite 具体实现
│      schema.sql             # 建表 SQL
├─interfaces
│      app.py                 # Flask 薄接口（待接入 service）
└─tests
       db_test.py
       service_test.py
```

## 领域模型

| 实体 | 说明 |
| --- | --- |
| `Member` | 社员，含姓名、QQ、学号、角色、状态（active/left）、入社日期 |
| `Record` | 打印记录，`member_id` 是谁打印，`operator_id` 是谁记录 |
| `Reservation` | 预约安排 |

角色：`president`（社长）、`vice_president`（副社长）、`op1`（运营1，管预约）、`op2`（运营2，管打印记录）、`hr`（人事，管成员）、`member`（普通社员）。

## 权限设计

### 校验写在哪里

- **`domain/permissions.py`**：只放"角色 → 动作"的权限矩阵和纯函数 `can()` / `require()`，不含业务逻辑。
- **`domain/services.py`**：每个**写操作**的入口先取操作员、调用 `require(operator.role, action)`，通过后再做业务校验和落库。这是唯一做权限校验的地方。
- **`interfaces/`**：不感知权限，只调用 service。
- **`main.py`**：不感知权限，只负责组装依赖。

### 权限矩阵

| 动作 | 允许角色 |
| --- | --- |
| `VIEW_ALL` 查看所有数据 | president / vice_president |
| `MANAGE_MEMBERS` 成员增改/退社 | president / vice_president / hr |
| `MANAGE_RESERVATIONS` 预约安排 | president / vice_president / op1 |
| `MANAGE_RECORDS` 打印记录 | president / vice_president / op2 |

操作员角色从 `members` 表读取（数据库里存的是字符串，`as_role()` 会归一化成 `Role` 枚举）。

## 服务层

| Service | 写操作 | 需要权限 |
| --- | --- | --- |
| `MemberService` | `register` / `update` / `leave` | `MANAGE_MEMBERS` |
| `RecordService` | `add` | `MANAGE_RECORDS` |
| `ReservationService` | `create` / `update_status` | `MANAGE_RESERVATIONS` |

查询方法（`get` / `list_*` / `find_*` / `list_by_*`）不做权限拦截，数据可见性由接口层按 `VIEW_ALL` 决定返回范围。

## 数据库

当前 `schema.sql` 只有三张表：`members`、`records`、`reservations`。SQLite 文件默认落在 `data/data.db`。

通用仓储 `SQLite3Repository` 通过 dataclass 字段反射实现 `_create` / `_get` / `_update` / `_delete` / `_list`；具体仓储补充按学号、角色、日期范围、周等查询。

## 使用

```python
from main import build_services, seed_president

services = build_services()
services["members"].register(...)
services["records"].add(...)
services["reservations"].create(...)
```

> **初始化**：空库首次使用前，先 `seed_president("社长姓名")` 写入第一名社长。
> 因为创建第一个操作员时库里还没有任何有权限的账号，这一条绕过 service 的权限校验；
> 之后所有写操作都必须走 service 的权限校验。

运行测试：

```bash
python -m pytest
```

## 路线图

- [x] 领域模型、仓储接口、通用 SQLite 仓储
- [x] 权限矩阵 + 服务层（本次）
- [ ] `interfaces` 接入 service，按 `VIEW_ALL` 控制数据可见性
- [ ] 额度流水 / 耗材 / 库存 / 经费（多表事务）
- [ ] 报表与导出
