from models import *

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")

class Repository(ABC, Generic[T]):
    @abstractmethod
    def create(self, entity: T) -> T: ...
    @abstractmethod
    def get(self, entity_id: int) -> T | None: ...
    @abstractmethod
    def update(self, entity: T) -> None: ...
    @abstractmethod
    def delete(self, entity_id: int) -> None: ...
    @abstractmethod
    def list(self, **filters) -> list[T]: ...

class MemberRepository(Repository[Member]):
    @abstractmethod
    def find_by_student_id(self, student_id: str) -> Member | None: ...
    @abstractmethod
    def list_by_role(self, role: Role) -> list[Member]: ...
    # Operator 就是 role in (OP1, OP2, PRESIDENT, ...) 的 Member，不再单独建仓库

class RecordRepository(Repository[Record]):
    @abstractmethod
    def list_by_member(self, member_id: int) -> list[Record]: ...
    @abstractmethod
    def list_by_date_range(self, start: date, end: date) -> list[Record]: ...

class QuotaTransactionRepository(Repository[QuotaTransaction]):
    @abstractmethod
    def balance_of(self, member_id: int) -> float: ...
    @abstractmethod
    def list_by_member(self, member_id: int) -> list[QuotaTransaction]: ...

class FilamentRepository(Repository[Filament]): ...
class InventoryTransactionRepository(Repository[InventoryTransaction]):
    @abstractmethod
    def stock_of(self, filament_id: int) -> float: ...

class FundTransactionRepository(Repository[FundTransaction]):
    @abstractmethod
    def balance(self) -> float: ...

class ReservationRepository(Repository[Reservation]):
    @abstractmethod
    def list_by_week(self, week_start: date) -> list[Reservation]: ...

class ContributionRepository(Repository[Contribution]):
    @abstractmethod
    def list_by_member(self, member_id: int) -> list[Contribution]: ...