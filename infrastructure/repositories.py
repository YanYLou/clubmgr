from abc import ABC, abstractmethod
from domain.models import Record, Operator

class OperatorRepository(ABC):
    @abstractmethod
    def create(self, operator: Operator) -> Operator: ...

    @abstractmethod
    def get(self, op_id: int) -> Operator | None: ...

    @abstractmethod
    def delete(self, op_id: int) -> None: ...

    @abstractmethod
    def list(self, **filters) -> list[Operator]: ...


class RecordRepository(ABC):
    @abstractmethod
    def create(self, record: Record) -> Record: ...

    @abstractmethod
    def read(self, record_id: int) -> Record | None: ...

    @abstractmethod
    def update(self, record: Record) -> None: ...

    @abstractmethod
    def delete(self, record_id: int) -> None: ...

    @abstractmethod
    def list(self, **filters) -> list[Record]: ...

