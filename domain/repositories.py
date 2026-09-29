from abc import ABC, abstractmethod
from models import Record, Operator

import sqlite3


class OperatorRepository(ABC):
    @abstractmethod
    def create(self, oprator: Operator) -> Operator: ...

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


class SQLiteOpRepo(OperatorRepository):
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS ops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_name TEXT NOT NULL,
            )
        """)
        self.conn.commit()



class SQLiteRecordRepo(RecordRepository):
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                op_id INTEGER NOT NULL,
                printer_name TEXT NOT NULL,
                filament TEXT NOT NULL,
                consumption REAL NOT NULL,
                date TEXT NOT NULL,
                comments TEXT
            )
        """)
        self.conn.commit()

    