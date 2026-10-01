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

@dataclass
class QuotaTransaction:
    id: Optional[int] = None
    member_id: int = 0
    amount: float = 0.0
    type: str = ""                    # init / print / contribution_reward / manual_adjust
    related_record_id: Optional[int] = None
    operator_id: int = 0
    date: date = field(default_factory=date.today)
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
    date: date = field(default_factory=date.today)
    note: Optional[str] = None

@dataclass
class FundTransaction:
    id: Optional[int] = None
    amount: float = 0.0
    type: str = ""                    # income / expense
    date: date = field(default_factory=date.today)
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
    date: date = field(default_factory=date.today)
    operator_id: int = 0
    note: Optional[str] = None