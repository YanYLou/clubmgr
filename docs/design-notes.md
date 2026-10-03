# 设计建议原文（历史文档）

> 这是早前提交进 `README.md` 的一版结构与业务设计建议，现移到 `docs/` 存档；
> 仓库根的 `README.md` 已恢复为项目说明。
>
> **注意：本文写于骨架阶段，其中一部分建议已经实现**，请以下表和 `docs/roadmap.md` 为准。

## 建议 vs 现状

| 建议 | 现状 |
| --- | --- |
| 分层：`domain` / `infrastructure` / `interfaces` | ✅ 已按此分层 |
| `Operator` → `Member`，拆分 `member_id` / `operator_id` | ✅ `domain/models.py` 已是 Member 与 Record(member_id, operator_id) |
| 仓储抽象接口移到 `domain/repositories.py` | ✅ 已移 |
| 统一 `Database`、`conn.row_factory`、`transaction()` | ✅ 已实现；阶段 0 把事务改成可嵌套 SAVEPOINT |
| 三张流水表 quota / inventory / fund_transactions | ✅ 建表完成 |
| 具体仓储实现（`SQLiteOpRepo` 一类） | ❌ 未实现，属阶段 1 |
| 权限矩阵在 `services.py` 判断 | ❌ 未实现，属阶段 1 |
| `interfaces/api.py` 只调 service、不写 SQL | ❌ 接口层仍是 Hello World，属阶段 2 |
| 每周备份 `data/club.db` | ❌ 未实现 |

---

## 以下为原文（未改动）

# New Suggestions from DeepSeek

> *Reference purpose only*

你这版新结构比之前好，**分层方向是对的**：`domain` 放模型和业务，`infrastructure` 放数据库，`interfaces` 放接口，`main.py` 组装。  
但目前还只是骨架，而且有几个关键问题：`Operator` 概念混乱、`Record.op_id` 指代不清、仓储抽象方法没实现、`db.py` 里 `row_factory` 写错、每个 Repo 各自连接不利于事务。下面我按你的新结构重新给一版规划。

---

## 一、先修正分层：接口应该放 domain，实现放 infrastructure

建议改成：

```text
E:\CLUBMGR
│  main.py
│  LICENSE
├─data
│      club.db
├─domain
│      models.py          # 数据类 + 枚举
│      repositories.py    # 仓储抽象接口 ABC
│      permissions.py     # 角色权限矩阵
│      services.py        # 业务逻辑
├─infrastructure
│      db.py              # Database、建表、事务
│      repositories.py    # SQLite 具体实现
└─interfaces
       api.py             # 给 CLI/GUI 调用的薄接口
```

关键原则：

- `domain/services.py` 只依赖 `domain/repositories.py` 的抽象接口，不依赖 SQLite。
- `infrastructure/repositories.py` 实现抽象接口。
- `interfaces/api.py` 不写 SQL，只调用 service。
- `main.py` 负责组装：创建 `Database`、创建具体 Repo、注入 Service。

你现在的 `infrastructure/repositories.py` 里同时放 ABC 接口，会让 `domain` 反向依赖 `infrastructure`，建议把 ABC 移到 `domain/repositories.py`。

---

## 二、领域模型要重做：不要用 Operator 混指社员和操作员

你现在的：

```python
@dataclass
class Operator:
    id: int
    op_name: str
```

但表里又有 `quota`，说明它其实是“社员”。  
`Record.op_id` 也容易混淆：它到底是“打印的社员”，还是“记录的操作员”？

建议明确：

- `Member`：社员，有额度、角色、状态。
- `Record.member_id`：谁打印的。
- `Record.operator_id`：谁记录的。
- 管理员也是 `Member`，只是 `role` 不同。

`domain/models.py` 建议这样：

```python
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

class Role(str, Enum):
    PRESIDENT = "president"
    VICE_PRESIDENT = "vice_president"
    OP1 = "op1"
    OP2 = "op2"
    HR = "hr"
    MEMBER = "member"

@dataclass
class Member:
    id: Optional[int] = None
    name: str = ""
    qq: Optional[str] = None
    student_id: Optional[str] = None
    role: Role = Role.MEMBER
    status: str = "active"      # active / left
    join_date: Optional[date] = None
    note: Optional[str] = None

@dataclass
class Record:
    id: Optional[int] = None
    member_id: int = 0          # 打印的社员
    printer_name: str = ""
    filament_name: str = ""
    consumption: float = 0.0
    date: date = field(default_factory=date.today)
    operator_id: int = 0        # 记录人，运营2
    is_charged: bool = False
    fee: float = 0.0
    reservation_id: Optional[int] = None
    comments: Optional[str] = None
```

额度不要直接放 `Member` 里改余额，要用流水算。

---

## 三、数据库表重新规划

核心表至少这些：

### 1. `members` 社员表

```sql
CREATE TABLE members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qq TEXT,
    student_id TEXT UNIQUE,
    role TEXT NOT NULL DEFAULT 'member',
    status TEXT NOT NULL DEFAULT 'active',
    join_date TEXT,
    note TEXT
);
```

### 2. `quota_transactions` 额度流水

```sql
CREATE TABLE quota_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- 正数增加，负数消耗
    type TEXT NOT NULL,            -- init/print/contribution_reward/manual_adjust
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

剩余额度 = `SUM(amount)`。  
学期初每人写一条 `+200`，打印写 `-消耗`，贡献奖励写 `+奖励`。

### 3. `records` 打印记录

```sql
CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    printer_name TEXT NOT NULL,
    filament_name TEXT NOT NULL,
    consumption REAL NOT NULL,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    is_charged INTEGER NOT NULL DEFAULT 0,
    fee REAL NOT NULL DEFAULT 0,
    reservation_id INTEGER,
    comments TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 4. `filaments` 耗材表

```sql
CREATE TABLE filaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    material TEXT,
    color TEXT,
    unit_price REAL,
    note TEXT
);
```

### 5. `inventory_transactions` 库存流水

```sql
CREATE TABLE inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filament_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- 正数入库，负数出库
    type TEXT NOT NULL,            -- purchase/print/adjust
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (filament_id) REFERENCES filaments(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 6. `fund_transactions` 经费流水

```sql
CREATE TABLE fund_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,          -- 正数收入，负数支出
    type TEXT NOT NULL,            -- income/expense
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 7. `reservations` 预约安排

```sql
CREATE TABLE reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    activity_day TEXT NOT NULL,    -- mon/wed/fri
    order_no INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 8. `contributions` 贡献/捐款

```sql
CREATE TABLE contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL,            -- money/material
    material_desc TEXT,
    reward_quota REAL NOT NULL DEFAULT 0,
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

---

## 四、你当前代码的具体问题

### 1. `SQLiteOpRepo` 无法实例化

`OperatorRepository` 有抽象方法：

```python
create / get / delete / list
```

但 `SQLiteOpRepo` 一个都没实现。Python 会报：

```text
TypeError: Can't instantiate abstract class SQLiteOpRepo with abstract methods ...
```

`SQLiteRecordRepo` 同理。

### 2. `row_factory` 写错

你写的是：

```python
self.row_factory = sqlite3.Row
```

应该是：

```python
self.conn.row_factory = sqlite3.Row
```

### 3. 每个 Repo 各自 `sqlite3.connect`

这样多个 Repo 各自连接，事务很难统一。  
打印一次要同时写：

- `records`
- `quota_transactions`
- `inventory_transactions`

如果三个 Repo 各自提交，中途失败就会数据不一致。

建议 `infrastructure/db.py` 提供统一 `Database`：

```python
import sqlite3
from contextlib import contextmanager

class Database:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        # 建表 SQL 放这里
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
```

Repo 不要自己 `connect`，而是接收 `Database`。

### 4. `Operator` 和 `ops` 表命名要改

建议：

- `Operator` → `Member`
- `ops` 表 → `members`
- `Record.op_id` → `Record.member_id`
- 新增 `Record.operator_id`

---

## 五、权限设计

角色：

| 角色 | 说明 |
| --- | --- |
| president | 社长，全部权限 |
| vice_president | 副社长，全部权限 |
| op1 | 运营1，预约安排 |
| op2 | 运营2，打印记录、资源统计 |
| hr | 人事，成员管理 |
| member | 普通社员，只看自己 |

权限矩阵：

| 功能 | 社长/副社长 | 运营1 | 运营2 | 人事 | 普通社员 |
| --- | --- | --- | --- | --- | --- |
| 查看所有数据 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 成员增改/退社 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 预约安排 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 打印记录 | ✅ | ❌ | ✅ | ❌ | ❌ |
| 耗材入库/采购 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 打印出库记录 | ✅ | ❌ | ✅ | ❌ | ❌ |
| 经费管理 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 额度调整 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 查看自己额度 | ✅ | ✅ | ✅ | ✅ | ✅ |

实现上不要只在 `api.py` 判断，要在 `services.py` 判断：

```python
def can_edit_members(role: Role) -> bool:
    return role in (Role.PRESIDENT, Role.VICE_PRESIDENT, Role.HR)

def can_write_record(role: Role) -> bool:
    return role in (Role.PRESIDENT, Role.VICE_PRESIDENT, Role.OP2)
```

---

## 六、业务逻辑应该放在 services.py

例如 `RecordService.record_print`：

```python
def record_print(self, operator_id, member_id, printer_name, filament_name, consumption, date):
    operator = self.member_repo.get(operator_id)
    if not can_write_record(operator.role):
        raise PermissionError("无权限记录打印")

    with self.db.transaction():
        record = Record(
            member_id=member_id,
            printer_name=printer_name,
            filament_name=filament_name,
            consumption=consumption,
            date=date,
            operator_id=operator_id,
        )
        record = self.record_repo.create(record)

        self.quota_repo.add(
            member_id=member_id,
            amount=-consumption,
            type="print",
            related_record_id=record.id,
            operator_id=operator_id,
            date=date,
        )

        self.inventory_repo.add_by_filament_name(
            filament_name=filament_name,
            amount=-consumption,
            type="print",
            related_record_id=record.id,
            operator_id=operator_id,
            date=date,
        )
    return record
```

买耗材时：

```python
def purchase_filament(self, operator_id, filament_id, amount, total_cost, date, note):
    # 1. funds 写支出：-total_cost
    # 2. inventory_transactions 写入库：+amount
```

贡献奖励时：

```python
def add_contribution(self, operator_id, member_id, amount, reward_quota, date, note):
    # 1. contributions 写一条
    # 2. quota_transactions 写 +reward_quota
```

---

## 七、日常运营管理建议

1. **群预约和数据库分开**  
   群里说“我要预约”只是来源，运营1最终录入 `reservations`。不要让群消息直接当数据。

2. **运营1只管安排，运营2只管记录**  
   互相核对，避免一个人既安排又记录。

3. **额度、库存、经费全部走流水**  
   不允许直接改余额。任何调整都写流水，备注原因和操作人。

4. **每周固定流程**
   - 周一/周三/周五前：运营1录预约。
   - 活动日：运营2录实际打印。
   - 周末：社长/副社长导出额度、库存、经费。
   - 备份 `data/club.db`。

5. **每月公示**
   - 经费余额
   - 耗材库存
   - 社员额度使用
   - 贡献名单

6. **退社不删除**
   人事把 `members.status` 改成 `left`，历史记录保留。

7. **特殊耗材单独建 filament**
   比如“红色 PETG 特殊料”，库存和普通 PLA 分开。

8. **先做 MVP**
   第一版只做：
   - members
   - records
   - quota_transactions
   - filaments
   - inventory_transactions
   - fund_transactions

   第二版再加 reservations、contributions、报表。

---

## 八、给你的行动清单

1. 把 `Operator` 改成 `Member`。
2. `ops` 表改成 `members`，加 `role/status/student_id/qq`。
3. `Record.op_id` 拆成 `member_id` 和 `operator_id`。
4. 把仓储 ABC 移到 `domain/repositories.py`。
5. `infrastructure/repositories.py` 只放 SQLite 实现。
6. `db.py` 改成统一 `Database`，设置 `self.conn.row_factory = sqlite3.Row`。
7. 建 `quota_transactions`、`inventory_transactions`、`fund_transactions` 三张流水表。
8. 所有写操作走 `services.py`，并检查 `operator_id` 的权限。
9. `interfaces/api.py` 只调用 service，不写 SQL。
10. 每周备份 `data/club.db`。

如果你愿意，我下一步可以直接按这个新结构，帮你写一版能跑的骨架代码：`domain/models.py`、`domain/repositories.py`、`domain/permissions.py`、`domain/services.py`、`infrastructure/db.py`、`infrastructure/repositories.py`、`interfaces/api.py`、`main.py`。
