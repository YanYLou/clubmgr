# Suggestions from DeepSeek
*Reference purpose only*

你们社团的流程其实已经比较清晰了，核心是 **“人、额度、耗材、经费、打印记录、预约安排”** 六件事。数据库不用一次做得很复杂，但要把关键字段和权限留好，后面扩展才不痛苦。

下面我按 **“先设计数据库 → 再定权限 → 最后给运营建议”** 来帮你统筹。

---

## 一、先明确核心实体和关系

你描述的业务里，主要实体有：

1. **社员**：有学期免费额度、已用额度、贡献奖励额度、剩余额度。
2. **管理人员**：社长、副社长、运营1、运营2、人事，都是社员，但角色不同。
3. **打印机**：社团有几台机器。
4. **耗材**：PLA、PETG、特殊耗材等，按克统计库存。
5. **打印记录**：谁、什么时候、用了哪台打印机、哪种耗材、多少克、谁记录的。
6. **预约安排**：运营1整理的每周一/三/五活动日打印顺序。
7. **贡献/捐款**：社员捐钱或捐耗材，对应额度奖励。
8. **经费**：社团资金收支，用来买耗材。
9. **额度变动流水**：每次额度增减都要有记录，不能直接改余额。

关系大概是：

- 一个社员有多条打印记录、多条额度变动、多条贡献记录。
- 一条打印记录对应一个社员、一台打印机、一种耗材、一个记录人。
- 一条预约安排对应一个社员、一个活动日、一个顺序号、一个安排人（运营1）。
- 耗材库存通过“入库/出库”流水计算。
- 经费通过“收入/支出”流水计算。

---

## 二、推荐数据库表结构

你现在用的是 SQLite，自用完全够。建议至少建下面这些表。字段名我统一用英文，避免和 Python 关键字冲突。

### 1. `members` 社员表

```sql
CREATE TABLE members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qq TEXT,
    student_id TEXT,
    role TEXT NOT NULL DEFAULT 'member',  -- member/op1/op2/hr/vice_president/president
    join_date TEXT,
    status TEXT NOT NULL DEFAULT 'active', -- active/left
    semester_quota REAL NOT NULL DEFAULT 200.0, -- 学期免费额度
    extra_quota REAL NOT NULL DEFAULT 0.0,       -- 贡献奖励等额外额度
    used_quota REAL NOT NULL DEFAULT 0.0,        -- 已用额度（可由流水计算）
    note TEXT
);
```

> 剩余额度 = `semester_quota + extra_quota - used_quota`。  
> 但更推荐用“额度流水”表来算，避免直接改 `used_quota` 出错。

### 2. `quota_transactions` 额度流水表

```sql
CREATE TABLE quota_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,          -- 正数增加，负数消耗
    type TEXT NOT NULL,            -- init/print/contribution_reward/manual_adjust
    related_record_id INTEGER,     -- 如果是打印消耗，关联 records.id
    operator_id INTEGER NOT NULL,  -- 谁操作的
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

这样每次打印扣额度、贡献加额度，都写一条流水，剩余额度 = `SUM(amount)`。

### 3. `printers` 打印机表

```sql
CREATE TABLE printers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'available', -- available/busy/maintenance
    note TEXT
);
```

### 4. `filaments` 耗材表

```sql
CREATE TABLE filaments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,          -- 如 PLA 白色
    material TEXT,               -- PLA/PETG/ABS...
    color TEXT,
    unit_price REAL,             -- 每克成本
    stock REAL NOT NULL DEFAULT 0.0,  -- 当前库存(g)，可由流水算，也可缓存
    note TEXT
);
```

### 5. `inventory_transactions` 耗材库存流水

```sql
CREATE TABLE inventory_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filament_id INTEGER NOT NULL,
    amount REAL NOT NULL,        -- 正数入库，负数出库
    type TEXT NOT NULL,          -- purchase/print/adjust
    related_record_id INTEGER,
    operator_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (filament_id) REFERENCES filaments(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 6. `records` 打印记录表

```sql
CREATE TABLE records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,      -- 打印的社员
    printer_id INTEGER NOT NULL,
    filament_id INTEGER NOT NULL,
    consumption REAL NOT NULL,       -- 消耗克数
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,    -- 记录人（运营2）
    is_charged INTEGER NOT NULL DEFAULT 0, -- 是否收费
    fee REAL NOT NULL DEFAULT 0.0,   -- 收费金额
    comments TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (printer_id) REFERENCES printers(id),
    FOREIGN KEY (filament_id) REFERENCES filaments(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

> 你原来的 `Record` 里叫 `op_id`，这里建议统一叫 `member_id`，因为打印的人是社员，不是操作员。操作员是 `operator_id`。

### 7. `reservations` 预约安排表

```sql
CREATE TABLE reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,       -- 那一周的周一日期
    activity_day TEXT NOT NULL,     -- 'mon'/'wed'/'fri'
    order_no INTEGER NOT NULL,      -- 活动日内的顺序
    status TEXT NOT NULL DEFAULT 'pending', -- pending/done/cancelled
    operator_id INTEGER NOT NULL,   -- 安排人（运营1）
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 8. `contributions` 贡献/捐款表

```sql
CREATE TABLE contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,           -- 捐款金额
    type TEXT NOT NULL,             -- money/material
    material_desc TEXT,             -- 如果捐耗材，描述
    reward_quota REAL NOT NULL DEFAULT 0.0, -- 奖励额度(g)
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

### 9. `funds` 经费流水表

```sql
CREATE TABLE funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,           -- 正数收入，负数支出
    type TEXT NOT NULL,             -- income/expense
    date TEXT NOT NULL,
    operator_id INTEGER NOT NULL,
    note TEXT,
    FOREIGN KEY (operator_id) REFERENCES members(id)
);
```

> 经费余额 = `SUM(amount)`。买耗材时，写一条 `funds` 支出，同时写一条 `inventory_transactions` 入库。

---

## 三、权限设计

你要求：社长、副社长有所有数据更改权；管理人员只有所属部分权限，不得越权。  
最简单的做法是在代码里做 **角色检查**，而不是在数据库里做复杂权限表。因为你们人少，硬编码角色+权限矩阵就够。

### 角色定义

| 角色 | 说明 |
|---|---|
| `president` | 社长，所有权限 |
| `vice_president` | 副社长，所有权限 |
| `op1` | 运营1，负责预约安排 |
| `op2` | 运营2，负责打印记录、资源使用统计 |
| `hr` | 人事，负责成员名单 |
| `member` | 普通社员，只能查看自己的额度、记录 |

### 权限矩阵

| 功能 | 社长/副社长 | 运营1 | 运营2 | 人事 | 普通社员 |
|---|---|---|---|---|---|
| 查看所有数据 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 修改成员名单 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 写入预约安排 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 写入打印记录 | ✅ | ❌ | ✅ | ❌ | ❌ |
| 管理耗材库存 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 管理经费 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 调整额度 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 查看自己额度 | ✅ | ✅ | ✅ | ✅ | ✅ |

实现时，每个写操作函数都传入 `operator_id`，先查这个人的 `role`，再判断是否允许。

例如：

```python
def can_edit_members(role: str) -> bool:
    return role in ("president", "vice_president", "hr")

def can_write_schedule(role: str) -> bool:
    return role in ("president", "vice_president", "op1")

def can_write_record(role: str) -> bool:
    return role in ("president", "vice_president", "op2")
```

---

## 四、关键业务规则建议

1. **额度不要直接改余额，用流水计算**  
   每次打印扣额度，写一条 `quota_transactions`，`amount = -消耗克数`。  
   贡献奖励写 `amount = +奖励克数`。  
   学期初初始化写 `amount = +200`。  
   剩余额度 = `SUM(amount)`。这样对账清晰。

2. **耗材库存也用流水**  
   买耗材入库写 `inventory_transactions` 正数，打印出库写负数。  
   库存 = `SUM(amount)`。避免直接改 `stock` 字段导致对不上。

3. **经费和耗材购买联动**  
   买耗材时：
   - `funds` 写一条支出（负数）
   - `inventory_transactions` 写一条入库（正数）
   - 备注写清楚买了什么、单价、数量。

4. **收费规则明确**  
   每学期 200g 免费，超出部分按每克多少钱收费。  
   可以在 `records` 里记录 `is_charged` 和 `fee`，方便统计谁还欠费。

5. **预约安排标准化**  
   运营1每周整理群里的“我要预约”，填入 `reservations`。  
   活动日安排顺序可以按预约时间或社员等级排。  
   打印完成后，运营2在 `records` 里记录实际消耗，并关联预约。

6. **贡献奖励规则固定**  
   比如捐 10 元奖励 20g 额度，或者捐特殊耗材奖励等值额度。  
   规则写进社团章程，数据库只记录结果。

---

## 五、代码结构建议

你现在的结构是：

```text
main.py
models.py
repositories.py
```

建议扩展成：

```text
spoolmgr/
  main.py
  models.py          # 数据类
  repositories.py    # 仓储接口 + SQLite 实现
  services.py        # 业务逻辑 + 权限检查
  permissions.py     # 权限矩阵
  cli.py             # 命令行菜单（如果要做界面）
  data/
    data.db
```

`services.py` 是核心，比如：

```python
class MemberService:
    def __init__(self, member_repo, quota_repo):
        ...
    def add_member(self, operator_id, name, qq, ...):
        if not can_edit_members(get_role(operator_id)):
            raise PermissionError("无权限")
        ...
```

这样数据库层只管增删改查，业务层管规则和权限。

---

## 六、日常运营管理建议

1. **所有操作留痕**  
   每张表都有 `operator_id` 和 `date`，谁改的、什么时候改的，一目了然。防止滥用。

2. **定期备份数据库**  
   每周活动结束后，把 `data.db` 复制一份到网盘或另一台电脑。SQLite 文件很小，备份成本低。

3. **财务和库存每月公示**  
   社长/财务导出经费余额、耗材库存、社员额度使用情况，发到群里。透明能减少矛盾。

4. **额度变动必须走流水**  
   不允许直接改 `used_quota`。任何调整都写 `quota_transactions`，备注原因。

5. **预约和记录分离**  
   运营1只管安排，运营2只管记录实际消耗。互相核对，避免一个人既安排又记录导致错误。

6. **退社成员处理**  
   人事把 `status` 改为 `left`，但不要删除记录。历史数据保留，方便查账。

7. **特殊耗材单独管理**  
   如果社员捐钱买特殊耗材，可以单独建一个 `filaments` 记录，库存和普通耗材分开统计。

8. **先做 MVP，再迭代**  
   第一版先做：成员管理、打印记录、额度流水、耗材库存。  
   第二版加：预约安排、贡献、经费。  
   第三版加：统计报表、导出 Excel。

---

## 七、给你和副社长的具体行动清单

1. 统一字段名：`Record.op_id` → `member_id`，`operator_id` 单独表示操作人。
2. 把 `repositories.py` 里的 `read` 改成 `get`，或补上 `read` 方法。
3. 补 `_row_to_record` 和 `SQLiteOpRepo`。
4. 建 `members`、`records`、`quota_transactions`、`filaments`、`inventory_transactions` 五张核心表。
5. 写一个 `permissions.py`，定义角色和权限检查函数。
6. 写一个简单的 CLI，让不同角色登录后只看到自己能用的功能。
7. 每次活动后，运营2录入记录，系统自动扣额度、减库存。
8. 每月导出一次经费、库存、额度报表。

这样你们社团的数据库就能真正支撑日常运营，而且不会因为管理员误操作导致数据混乱。如果需要，我可以帮你把 `models.py`、`repositories.py` 按上面的设计重写一版能跑的代码。
