import sqlite3
from contextlib import contextmanager
from pathlib import Path

from datetime import date, datetime

sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda dt: dt.isoformat())

MEMORY = ":memory:"

class Database:
    def __init__(self, path: str | Path):
        path = str(path)
        # 阶段 0.1 新增：数据库文件所在目录不存在时先创建，
        # 否则 sqlite3 会抛 "unable to open database file"。
        if path != MEMORY:
            Path(path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):        
        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        self.conn.executescript(schema_sql)
        self.conn.commit()

    @contextmanager
    def transaction(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise