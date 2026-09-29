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
    ...

class SQLiteRecordRepo(RecordRepository):
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.row_factory = sqlite3.Row

        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operator_id INTEGER NOT NULL,
                printer_name TEXT NOT NULL,
                filament TEXT NOT NULL,
                consumption REAL NOT NULL,
                date TEXT NOT NULL,
                comments TEXT
            )
        """)
        self.conn.commit()

    def create(self, record: Record) -> Record:
        cur = self.conn.execute(
            """INSERT INTO records
               (operator_id, printer_name, filament, consumption, date, comments)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record.operator_id, record.printer_name, record.filament,
             record.consumption, record.date.isoformat(), record.comments),
        )
        self.conn.commit()
        record.id = cur.lastrowid
        return record

    def get(self, record_id: int) -> Record | None:
        row = self.conn.execute(
            "SELECT * FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def update(self, record: Record) -> None:
        self.conn.execute(
            """UPDATE records SET operator_id=?, printer_name=?, filament=?,
               consumption=?, date=?, comments=? WHERE id=?""",
            (record.operator_id, record.printer_name, record.filament,
             record.consumption, record.date.isoformat(),
             record.comments, record.id),
        )
        self.conn.commit()

    def delete(self, record_id: int) -> None:
        self.conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
        self.conn.commit()

    def list(self, **filters) -> list[Record]:
        sql = "SELECT * FROM records"
        params: list = []
        if filters:
            conditions = [f"{k} = ?" for k in filters]
            sql += " WHERE " + " AND ".join(conditions)
            params = list(filters.values())
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_record(r) for r in rows]