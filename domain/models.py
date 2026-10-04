"""领域模型（数据类 + 枚举）。

阶段 0.4 修正（既有缺陷）：字段名与类型名同名时，注解会被字段本身遮蔽。
``date: date = field(default_factory=date.today)`` 这种写法里，CPython 会先把
右边的值存进类命名空间，再求值左边的注解，于是注解拿到的是 ``Field`` 对象
而不是 ``datetime.date``：写库不受影响，但 ``get_type_hints()`` /
``dataclasses.fields().type`` 会得到错误类型，读回时无法按类型还原。
因此凡是名为 ``date`` 的字段，注解统一写成 ``datetime.date``。

阶段 1 变更（按拍板结论）：``Record`` 去掉 ``is_charged`` / ``fee`` 两个字段
（收费语义未定，先不在打印记录里记钱），新增 ``filament_id`` 外键，
``filament_name`` 保留作为历史快照。结构版本同步升到 2，见 ``infrastructure/db.py``。

阶段 2.2 变更：新增 ``User``（登录账号），一个账号关联一个社员，
权限仍然取自该社员的 ``role``，所以权限判断逻辑不用改。结构版本升到 3。

阶段 2.3 变更：``Reservation`` 增加 ``reviewer_id`` / ``reviewed_at``；
规则是"谁都能提交，社长 / 副社长 / 运维审核通过后才进排班表"。结构版本升到 4。

阶段 3.1 变更（按选择题确认的答案）：``Role`` 拆出副社长1号 / 2号，新增 ``teacher``
（社团老师，权限与社长同级），两位运营权限完全一致。旧值 ``vice_president`` 由
:meth:`Role.parse` 兼容为副社长1号（`members.role` 是 TEXT，无需改表结构）。
"""

import datetime
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

class Role(str, Enum):
    PRESIDENT = "president"
    VICE_PRESIDENT_1 = "vice_president_1"     # 副社长1号（有管理页权限）
    VICE_PRESIDENT_2 = "vice_president_2"
    TEACHER = "teacher"                       # 社团老师：权限与社长同级
    OP1 = "op1"                               # 运营1（与运营2 权限完全一致）
    OP2 = "op2"
    HR = "hr"
    MEMBER = "member"

    @classmethod
    def parse(cls, value) -> "Role":
        """把字符串 / 旧值转成 Role。

        兼容阶段 2.3 之前的 ``vice_president``（那时还没区分 1 号 / 2 号）：
        统一当作副社长1号。
        """
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        if text == "vice_president":
            return cls.VICE_PRESIDENT_1
        return cls(text)

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
class User:
    """登录账号（阶段 2.2 新增）。权限来自 ``member_id`` 对应社员的角色。"""

    id: Optional[int] = None
    username: str = ""
    password_hash: str = ""     # pbkdf2_sha256$...，见 domain/security.py
    member_id: int = 0
    status: str = "active"      # active / disabled
    note: Optional[str] = None

@dataclass
class Record:
    id: Optional[int] = None
    member_id: int = 0          # 打印的社员
    printer_name: str = ""
    filament_id: int = 0        # 耗材，外键 filaments.id（阶段 1 新增）
    filament_name: str = ""     # 历史快照：耗材改名不影响旧记录
    consumption: float = 0.0    # 消耗，单位：克
    date: datetime.date = field(default_factory=date.today)
    operator_id: int = 0        # 记录人，运营2
    reservation_id: Optional[int] = None
    comments: Optional[str] = None

@dataclass
class QuotaTransaction:
    id: Optional[int] = None
    member_id: int = 0
    amount: float = 0.0
    type: str = ""                    # init / print / contribution_reward / manual_adjust
    related_record_id: Optional[int] = None
    operator_id: int = 0
    date: datetime.date = field(default_factory=date.today)
    note: Optional[str] = None

@dataclass
class Filament:
    id: Optional[int] = None
    name: str = ""
    material: Optional[str] = None
    color: Optional[str] = None
    unit_price: Optional[float] = None
    note: Optional[str] = None

@dataclass
class InventoryTransaction:
    id: Optional[int] = None
    filament_id: int = 0
    amount: float = 0.0
    type: str = ""                    # purchase / print / adjust
    related_record_id: Optional[int] = None
    operator_id: int = 0
    date: datetime.date = field(default_factory=date.today)
    note: Optional[str] = None

@dataclass
class FundTransaction:
    id: Optional[int] = None
    amount: float = 0.0
    type: str = ""                    # income / expense
    date: datetime.date = field(default_factory=date.today)
    operator_id: int = 0
    note: Optional[str] = None

@dataclass
class Reservation:
    """预约（阶段 2.3）。谁都能提交（pending），审核通过后才进排班表（approved）。"""

    id: Optional[int] = None
    member_id: int = 0
    week_start: date = field(default_factory=date.today)   # 所在周的周一
    activity_day: str = ""            # mon / wed / fri
    order_no: int = 0                 # 0 = 未排班；通过时分配 1..n
    status: str = "pending"           # pending / approved / rejected / cancelled
    operator_id: int = 0              # 提交人
    reviewer_id: Optional[int] = None # 审核（或撤销）的人
    reviewed_at: Optional[datetime.datetime] = None
    note: Optional[str] = None

@dataclass
class Contribution:
    id: Optional[int] = None
    member_id: int = 0
    amount: float = 0.0
    type: str = ""                    # money / material
    material_desc: Optional[str] = None
    reward_quota: float = 0.0
    date: datetime.date = field(default_factory=date.today)
    operator_id: int = 0
    note: Optional[str] = None
