# Clubmgr: A convenient tool to manage Zaomeng 3D Printing Club

![Static Badge](https://img.shields.io/badge/Status-In_development-blue)

> We take no responsibilities for any crashes.

造梦 3D 打印社团的运营管理工具：用 SQLite 记账，管理**社员、打印记录、额度、耗材库存、经费**，
另规划了预约排期与贡献奖励。定位是单机 / 局域网内部工具，不是多租户 Web 服务。

## 项目状态

标记说明：✅ 已实现并有测试 · 🟡 部分实现 · ❌ 尚未实现。

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 领域模型 `domain/models.py` | ✅ | 8 个 dataclass + `Role` 枚举；`records` 用 `filament_id` 外键（结构版本 2） |
| 建表 `infrastructure/schema.sql` | ✅ | 8 张表 + 8 个索引；额度 / 库存 / 经费全部走流水 |
| 连接与事务 `infrastructure/db.py` | ✅ | 自动建目录、WAL、可嵌套事务（SAVEPOINT）、`close()` 守卫、结构版本校验 |
| 泛型仓储 `SQLite3Repository` | ✅ | 反射 dataclass 字段生成 CRUD；读回时按类型注解还原 `Role` / `date` / `bool` |
| 具体仓储（7 个） | ✅ | `infrastructure/repositories.py`：社员 / 打印 / 额度 / 耗材 / 库存 / 经费 / 贡献 |
| 权限矩阵 `domain/permissions.py` | ✅ | 11 个动作，含"额度不足只有社长/副社长能记" |
| 业务服务 `domain/services.py` | ✅ | 社员 / 额度 / 打印（三表同事务）/ 耗材 / 经费 / 贡献 / 报表 |
| 命令行 `interfaces/cli.py` | ✅ | `python main.py ...`，覆盖全部业务动作 |
| Web 界面 `interfaces/app.py` + `interfaces/views/` | ✅ | 登录 + 首页概览 + 社员 / 打印 / 耗材 / 额度 / 经费 / 账号页面 |
| 登录与账号（`users` 表） | ✅ | pbkdf2 口令哈希 + 会话登录；账号权限仍取自关联社员的角色 |
| 装配 `main.py` | ✅ | `build_repositories` / `build_services` / `open_services` + CLI / Web 入口 |
| 测试 | ✅ | 83 个用例：数据层、仓储、权限、服务、CLI、Web |
| 预约排期 `reservations` | ❌ | 表已建好，仓储与服务未写（等"一人一天能约几件"定下来） |

一句话：**额度、打印、库存、经费的闭环已经能用命令行完整操作；Web 界面与预约排期还没做。**
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

# 3. 初始化数据库并创建第一个社长（首次运行会自动创建 data/club.db）
python main.py member bootstrap --name 社长 --student-id 10001

# 4. 建一个登录账号（Web 界面需要；本地测试账号就用 admin / admin123）
python main.py --operator 10001 user add --username admin --password admin123 --member 10001

# 5. 启动 Web 界面，浏览器打开 http://127.0.0.1:5000/ 用上面的账号登录
python main.py web
```

## Web 界面

```powershell
python main.py web                      # 默认 127.0.0.1:5000
python main.py web --host 0.0.0.0 --port 8080   # 让同社团的人在内网访问
flask --app interfaces.app:create_app run --debug   # 等价写法（开发模式）
```

页面：首页概览（自己的额度 + 社长视角的全社额度 / 库存 / 经费）、我的额度单、
社员名册与增改退社、打印记录与「记打印」、耗材与库存、额度发放与调整、经费流水与贡献、账号管理。

要点：

- **必须先建账号**：`user add`（见上面第 4 步）或让社长在「账号」页面创建；
  账号只是"证明你是哪个社员"，权限仍然取自该社员的角色。
- 会话密钥优先读环境变量 `CLUBMGR_SECRET_KEY`，没有就在 `data/secret_key` 里生成一个并复用。
- 服务是 Flask 开发服务器，只适合社团内网 / 本机使用；页面写入全部走服务层，
  权限、事务、额度规则与 CLI 完全一致。

## 命令行用法

`--operator` 指定操作人，可以用 **id / 学号 / 姓名**；权限判断在服务层，越权会报错并返回退出码 1。
加 `--json`（放在子命令之前）可输出机器可读结果。

```powershell
# 社员
python main.py --operator 10001 member add --name 张三 --student-id 10005
python main.py --operator 10001 member list
python main.py --operator 10001 member left --member 10005

# 耗材与库存
python main.py --operator 10001 filament add --name "PLA 白" --material PLA --unit-price 0.12
python main.py --operator 10001 filament purchase --filament "PLA 白" --grams 1000 --cost 150 --note "采购 1kg"
python main.py --operator 10001 filament stock

# 额度
python main.py --operator 10001 quota init --amount 200          # 学期初发给全体在社社员
python main.py --operator 10001 quota adjust --member 张三 --amount -30 --note "上学期欠额度"
python main.py --operator 10005 quota balance                    # 查自己

# 记录打印（额度不足时只有社长 / 副社长能记）
python main.py --operator 10002 record print --member 10005 --filament "PLA 白" --grams 42.5 --printer P1
python main.py --operator 10005 report statement                 # 个人额度单

# 经费与贡献
python main.py --operator 10001 fund income --amount 500 --note "会费收入"
python main.py --operator 10001 fund list
python main.py --operator 10001 contribution add --member 10005 --amount 100 --reward-quota 50 --note "捐赠耗材费"

# 报表
python main.py --operator 10001 report quota
python main.py --operator 10001 report stock
python main.py --operator 10001 report fund
```

数据库文件固定为 `data/club.db`（见 `main.py` 的 `DB_PATH`），已被 `.gitignore` 忽略，请勿提交。

## 目录结构

```text
clubmgr/
├─ main.py                     # 路径常量 + 服务装配 + CLI 入口
├─ requirements.txt  pytest.ini  .gitattributes
├─ domain/                     # 领域层：不依赖 SQLite
│   ├─ models.py               # dataclass 与枚举
│   ├─ repositories.py         # 仓储抽象接口 + 事务边界（端口）
│   ├─ permissions.py          # 角色权限矩阵
│   ├─ security.py             # 口令哈希（pbkdf2）
│   └─ services.py             # 业务逻辑与事务边界
├─ infrastructure/             # 基础设施层
│   ├─ db.py                   # 连接、PRAGMA、建表、可嵌套事务、结构版本
│   ├─ repositories.py         # 泛型 SQLite 仓储 + 8 个具体仓储 + 类型还原
│   └─ schema.sql              # 建表语句与索引
├─ interfaces/                 # 接口层
│   ├─ cli.py                  # 命令行
│   ├─ app.py                  # Flask 应用工厂
│   ├─ views/                  # 8 个蓝图（auth/dashboard/members/records/filaments/quota/fund/users）
│   └─ templates/              # Jinja 模板
├─ tests/                      # pytest 测试（83 个用例）
└─ docs/                       # 设计文档与路线图
```

## 角色与权限

| 角色 | 职责 |
| --- | --- |
| `president` / `vice_president` | 全部权限：经费、额度调整、耗材采购、**记透支** |
| `op1` | 预约安排（阶段 2.3 使用） |
| `op2` | 打印记录、查看库存 |
| `hr` | 成员增改、退社 |
| `member` | 只看自己的额度与记录 |

权限判断放在服务层（`domain/permissions.py` + `domain/services.py`），接口层不重复判断
（Web 页面只用 `can()` 隐藏入口，CLI 完全不判断）。除了上表的职责，还有几个细分的读权限：
`view_members`（人事看名册）、`view_records`（运营2 看打印记录做统计）、
`view_inventory`（运营2 选耗材）、`view_funds`（经费只给社长 / 副社长）、
`manage_users`（登录账号管理）。

## 数据模型（8 张表）

| 表 | 语义 |
| --- | --- |
| `members` | 社员（管理员也是社员，靠 `role` 区分） |
| `records` | 一条 = 一次打印（`member_id` 打印者、`operator_id` 记录人、`filament_id` 外键 + `filament_name` 快照） |
| `quota_transactions` | 额度流水（`SUM(amount)` = 剩余额度） |
| `filaments` | 耗材目录 |
| `inventory_transactions` | 库存流水 |
| `fund_transactions` | 经费流水 |
| `reservations` | 活动日排期（周一 / 周三 / 周五，待实现） |
| `contributions` | 贡献 / 捐款与额度奖励 |

## 设计约定

- **一切走流水**：额度、库存、经费余额都由 `SUM(amount)` 实时算出，不存余额字段，不允许直接改余额。
- **事务边界在服务层**：仓储只执行 SQL、不提交；一次业务操作（记录打印要同时写 `records`、
  `quota_transactions`、`inventory_transactions`）必须包在 `with db.transaction():` 里，事务可嵌套。
- **额度不足允许透支，但只有社长 / 副社长能记**（`allow_overdraft`）：现场不阻塞打印，
  欠的额度事后用缴款 / 贡献奖励补上；报表里余额为负即为透支。
- **打印记录不记钱**：`records` 没有 `fee` / `is_charged`（收费规则未定，先不猜），
  与钱有关的内容只走 `fund_transactions` 与 `contributions`。
- **类型还原**：写库用 `date` / `Role`，读回时由 `SQLite3Repository._from_row` 按字段类型注解还原。
- **结构版本**：改 `schema.sql` 必须同时把 `infrastructure/db.py` 的 `SCHEMA_VERSION` 加 1；
  打开旧版本的库会直接报错并提示重建（开发阶段没有迁移脚本）。
- **账号与权限分离**：`users` 表只回答"你是哪个社员"，所有权限都按该社员的 `role` 判断；
  口令用 pbkdf2 + 每人随机盐存储（`domain/security.py`），会话里只放账号 id。

## 文档

- [`docs/roadmap.md`](docs/roadmap.md)：分阶段路线图、完成情况与待决策问题
- [`docs/design-notes.md`](docs/design-notes.md)：早期设计建议原文（历史文档，部分已实现）
- `AGENTS.md`：协作与提交规范（本地文件，未纳入版本库）
