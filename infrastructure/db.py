from infrastructure.repositories import *

import sqlite3

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

    