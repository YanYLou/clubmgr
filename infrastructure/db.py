"""SQLite 连接、建表与事务边界。

阶段 0.2 / 0.3（本次改动，代码里已逐处标注）：
- 修改：``transaction()`` 从"退出即 commit / rollback"改为 SAVEPOINT 嵌套。
  原实现里内层退出就会 commit，会把外层未完成的改动一起提交；内层失败也会
  连带回滚外层已写入的数据。修复后的行为见 ``tests/transaction_test.py``。
- 修改：连接使用 ``isolation_level=None``（关闭 sqlite3 的隐式事务），
  事务边界完全由 ``transaction()`` 掌握。
- 新增：``PRAGMA journal_mode=WAL`` / ``busy_timeout``，便于读写并发。
- 新增：``close()`` / ``__enter__`` / ``__exit__``，有未结束的事务时拒绝关闭。
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from itertools import count
from pathlib import Path

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

        # 阶段 0.2 修改：isolation_level=None 关闭 sqlite3 的隐式事务，
        # 事务边界完全由 transaction() 决定（原来用默认的隐式 BEGIN）。
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != MEMORY:
            # 阶段 0.2 新增：WAL 让读写可以并发（:memory: 不支持，跳过）。
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

        self._savepoint_ids = count(1)
        self._open_transactions = 0
        self._init_schema()

    def _init_schema(self):
        """建表：只在空库上执行 ``schema.sql``。

        阶段 0 修复（既有缺陷）：原来每次连接都无条件执行建表脚本，第二次连接
        一个已存在的数据库文件时会抛 ``table members already exists``
        （``CREATE TABLE`` 不带 ``IF NOT EXISTS``）。这里改成"库里已有表就跳过"。

        注意：这只负责初始化。后续若要**修改**已有表结构，需要迁移脚本或重建
        数据库文件，不能指望重跑 schema.sql。
        """
        existing = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        if existing is not None:
            return

        schema_path = Path(__file__).with_name("schema.sql")
        schema_sql = schema_path.read_text(encoding="utf-8")
        # 阶段 0.2 修改：autocommit 模式下 executescript 自身即落盘，无需再 commit。
        self.conn.executescript(schema_sql)

    @property
    def in_transaction(self) -> bool:
        """当前是否正处在 ``transaction()`` 块内。"""
        return self._open_transactions > 0

    @contextmanager
    def transaction(self):
        """事务边界，可嵌套：内层失败只回滚内层（SAVEPOINT）。

        最外层 RELEASE 时才真正提交。任一层的块内抛出异常，该层开始时
        之后的所有改动都会被丢弃，但不会影响外层更早的写入。
        """
        name = f"sp_{next(self._savepoint_ids)}"
        self.conn.execute(f"SAVEPOINT {name}")
        self._open_transactions += 1
        try:
            yield self.conn
        except Exception:
            # 个别 SQLite 错误（例如 ON CONFLICT ROLLBACK）会连带回滚整个事务，
            # 此时 savepoint 已不存在：忽略回滚本身的报错，保留原始异常。
            try:
                self.conn.execute(f"ROLLBACK TO {name}")
                self.conn.execute(f"RELEASE {name}")
            except sqlite3.Error:
                pass
            raise
        else:
            self.conn.execute(f"RELEASE {name}")
        finally:
            self._open_transactions -= 1

    def close(self) -> None:
        """关闭连接。

        阶段 0.3 新增：仍有未结束的事务时直接报错（而不是静默丢弃写入）。
        注意 isolation_level=None 之后，没包在 ``transaction()`` 里的写入会
        立即提交，因此这个守卫拦的是"事务没退出就关连接"，不是"忘记开事务"。
        """
        if self.in_transaction:
            raise RuntimeError(
                "仍有未结束的事务，拒绝关闭连接（请先退出 with db.transaction() 块）"
            )
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
