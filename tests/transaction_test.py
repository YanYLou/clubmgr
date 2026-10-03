"""阶段 0.2：事务嵌套（SAVEPOINT）行为测试。

原实现的 ``transaction()`` 每次退出都直接 commit / rollback，实测有两个坏情况：

1. 外层业务失败，但内层已经 commit 过，数据仍留在库里；
2. 内层失败会把外层**已经写入**的数据一起回滚。

这里把修复后的行为锁死，避免回归。
"""

import sqlite3

import pytest

from domain.models import Member
from infrastructure.db import Database
from infrastructure.repositories import SQLite3Repository


class MemberRepo(SQLite3Repository[Member]):
    """测试用的最小具体仓储；正式的具体仓储属于阶段 1。"""

    table = "members"
    entity_cls = Member


def names(db: Database) -> list[str]:
    rows = db.conn.execute("SELECT name FROM members ORDER BY id").fetchall()
    return [row["name"] for row in rows]


def test_outer_failure_rolls_back_inner_release():
    """外层失败时，内层已 RELEASE 的写入也必须消失（原实现会残留）。"""
    db = Database(":memory:")
    repo = MemberRepo(db)

    with pytest.raises(RuntimeError):
        with db.transaction():
            repo._create(Member(name="Outer"))
            with db.transaction():
                repo._create(Member(name="Inner"))
            raise RuntimeError("外层业务失败")

    assert names(db) == []
    db.close()


def test_inner_failure_keeps_outer_write_and_allows_commit():
    """内层失败被外层捕获后，外层已写入的数据保留，且仍能继续提交。"""
    db = Database(":memory:")
    repo = MemberRepo(db)

    with db.transaction():
        repo._create(Member(name="Outer"))
        with pytest.raises(RuntimeError):
            with db.transaction():
                repo._create(Member(name="Inner"))
                raise RuntimeError("内层失败")
        repo._create(Member(name="AfterInner"))

    assert names(db) == ["Outer", "AfterInner"]
    db.close()


def test_write_outside_transaction_is_committed_immediately(tmp_path):
    """阶段 0.2 的行为说明：不包 transaction() 的写入会立即提交。

    这正是"写入必须包在 ``with db.transaction()`` 里"的原因：不包事务不会
    丢数据，但会失去原子性（业务失败时前面的写入无法回滚）。
    """
    path = tmp_path / "autocommit.db"
    db = Database(path)
    MemberRepo(db)._create(Member(name="NoTx"))

    other = sqlite3.connect(path)
    try:
        assert other.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    finally:
        other.close()
    db.close()


def test_in_transaction_flag_tracks_nesting():
    """transaction() 块内 ``in_transaction`` 为真，退出后恢复为假。"""
    db = Database(":memory:")
    assert db.in_transaction is False

    with db.transaction():
        assert db.in_transaction is True
        with db.transaction():
            assert db.in_transaction is True
        assert db.in_transaction is True

    assert db.in_transaction is False
    db.close()
