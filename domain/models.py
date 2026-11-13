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
    reservation_id: Optional[int] = None
    comments: Optional[str] = None

@dataclass
class Reservation:
    id: Optional[int] = None
    member_id: int = 0
    date: date = field(default_factory=date.today)
    status: str = "pending"
    operator_id: int = 0
    note: Optional[str] = None
