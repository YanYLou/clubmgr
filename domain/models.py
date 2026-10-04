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
"""

import datetime
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
    id: Optional[int] = None
    member_id: int = 0
    week_start: date = field(default_factory=date.today)
    activity_day: str = ""            # mon/wed/fri
    order_no: int = 0
    status: str = "pending"
    operator_id: int = 0
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
