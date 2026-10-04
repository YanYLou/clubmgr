"""仓储抽象接口与事务边界（领域层端口）。

阶段 1.1 新增：把具体仓储要用到的查询，以及事务边界 ``TransactionManager``，
一并声明在这里 —— 这样 ``domain/services.py`` 只依赖抽象接口，不依赖 SQLite
实现（实现分别在 ``infrastructure/repositories.py`` 与 ``infrastructure/db.py``）。
"""

from domain.models import *

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Generic, Protocol, TypeVar

T = TypeVar("T")

class TransactionManager(Protocol):
    """事务边界（结构类型）。

    ``infrastructure.db.Database`` 天然满足它：``transaction()`` 返回可嵌套的
    上下文管理器，``in_transaction`` 表示当前是否有未结束的事务。
    """

    def transaction(self) -> AbstractContextManager[Any]: ...
    @property
    def in_transaction(self) -> bool: ...

class Repository(ABC, Generic[T]):
    @abstractmethod
    def _create(self, entity: T) -> T: ...
    @abstractmethod
    def _get(self, entity_id: int) -> T | None: ...
    @abstractmethod
    def _update(self, entity: T) -> None: ...
    @abstractmethod
    def _delete(self, entity_id: int) -> None: ...
    @abstractmethod
    def _list(self, **filters) -> list[T]: ...

class MemberRepository(Repository[Member]):
    @abstractmethod
    def find_by_student_id(self, student_id: str) -> Member | None: ...
    @abstractmethod
    def list_by_role(self, role: Role) -> list[Member]: ...
    @abstractmethod
    def find_by_student_name(self, student_name: str) -> Member | None: ...
    @abstractmethod
    def list_active(self) -> list[Member]: ...               # 阶段 1 新增：在社社员

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
    @abstractmethod
    def has_type(self, member_id: int, txn_type: str) -> bool: ...   # 阶段 1 新增

class FilamentRepository(Repository[Filament]):
    @abstractmethod
    def find_by_name(self, name: str) -> Filament | None: ...        # 阶段 1 新增

class InventoryTransactionRepository(Repository[InventoryTransaction]):
    @abstractmethod
    def stock_of(self, filament_id: int) -> float: ...
    @abstractmethod
    def list_by_filament(self, filament_id: int) -> list[InventoryTransaction]: ...  # 阶段 1 新增

class FundTransactionRepository(Repository[FundTransaction]):
    @abstractmethod
    def balance(self) -> float: ...
    @abstractmethod
    def list_by_date_range(self, start: date, end: date) -> list[FundTransaction]: ...  # 阶段 1 新增

class ReservationRepository(Repository[Reservation]):
    @abstractmethod
    def list_by_week(self, week_start: date) -> list[Reservation]: ...

class ContributionRepository(Repository[Contribution]):
    @abstractmethod
    def list_by_member(self, member_id: int) -> list[Contribution]: ...
