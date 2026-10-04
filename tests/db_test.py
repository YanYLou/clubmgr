
def test_db_create_table():

    from infrastructure.db import Database

    db = Database(":memory:")

    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()

    names = {r["name"] for r in row}
    print(names)                        

    assert "members" in names 


def test_transaction_rollback_with_repo():
    from infrastructure.db import Database
    from infrastructure.repositories import SQLite3Repository
    from dataclasses import dataclass

    @dataclass
    class Member:
        name: str
        id: int | None = None

    class MemberRepo(SQLite3Repository[Member]):
        table = "members"
        entity_cls = Member

    db = Database(":memory:")
    repo = MemberRepo(db)

    try:
        with db.transaction():
            repo._create(Member(name="Alice"))   # 内部 commit，落库
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    count = db.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    assert count == 0, "应该回滚，但现在不会"

def test_repo_create():
    from infrastructure.db import Database
    from infrastructure.repositories import SQLite3Repository
    from domain.models import Member, Role
    from datetime import date

    # @dataclass
    # class Member:
    #     id: Optional[int] = None
    #     name: str = ""
    #     qq: Optional[str] = None
    #     student_id: Optional[str] = None
    #     role: Role = Role.MEMBER
    #     status: str = "active"      # active / left
    #     join_date: Optional[date] = None
    #     note: Optional[str] = None

    class MemberRepo(SQLite3Repository[Member]):
        table = "members"
        entity_cls = Member

    db = Database(":memory:")
    repo = MemberRepo(db)

    with db.transaction():
        repo._create(Member(
            name= "Alice",
            qq= "123456789",
            student_id= "10101",
            role= Role.MEMBER,
            status= "active",
            join_date= date(2026, 9, 1),
            note= "No notes"
        ))

    rows = repo._list()
    member = rows[0]
    assert member.name == "Alice"
    assert member.qq == "123456789"
    assert member.student_id == "10101"
    assert member.role is Role.MEMBER                   # 阶段 0.4：枚举被还原成 Role
    assert member.join_date == date(2026, 9, 1)         # 阶段 0.4：原来是 "2026-09-01" 字符串
    assert member.note == "No notes"


# ---------------------------------------------------------------------------
# 阶段 0.1 / 0.3 新增：Database 的目录创建与生命周期
# ---------------------------------------------------------------------------

def test_database_creates_missing_parent_directory(tmp_path):
    """阶段 0.1 新增：数据库文件所在目录不存在时自动创建（原来抛 OperationalError）。"""

    from infrastructure.db import Database

    db_path = tmp_path / "nested" / "data" / "club.db"
    assert not db_path.parent.exists()

    db = Database(db_path)
    try:
        assert db_path.exists()
    finally:
        db.close()


def test_close_rejects_open_transaction():
    """阶段 0.3 新增：仍有未结束的事务时拒绝关闭连接（避免静默丢弃写入）。"""

    import pytest

    from infrastructure.db import Database

    db = Database(":memory:")
    with db.transaction():
        with pytest.raises(RuntimeError):
            db.close()

    db.close()          # 事务退出后可以正常关闭


def test_context_manager_closes_connection():
    """阶段 0.3 新增：with Database(...) 退出后连接已关闭。"""

    import sqlite3

    import pytest

    from infrastructure.db import Database

    with Database(":memory:") as db:
        assert db.conn.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError):
        db.conn.execute("SELECT 1")


def test_reopen_existing_database_keeps_data(tmp_path):
    """阶段 0 修复（既有缺陷）：重复连接已存在的库不再抛 table already exists。"""

    from infrastructure.db import Database

    db_path = tmp_path / "club.db"

    db = Database(db_path)
    with db.transaction():
        db.conn.execute("INSERT INTO members (name) VALUES (?)", ("Alice",))
    db.close()

    again = Database(db_path)          # 原来这里会抛 OperationalError
    try:
        count = again.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        assert count == 1
    finally:
        again.close()


def test_outdated_schema_version_is_rejected(tmp_path):
    """阶段 1 新增：结构版本不符时明确报错，而不是等到查询报 no such column。"""

    import pytest

    from infrastructure.db import SCHEMA_VERSION, Database

    db_path = tmp_path / "club.db"
    db = Database(db_path)
    db.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
    db.close()

    with pytest.raises(RuntimeError) as excinfo:
        Database(db_path)

    assert "结构版本" in str(excinfo.value)


def test_fresh_database_records_schema_version(tmp_path):
    """阶段 1 新增：新建的库会写入当前结构版本。"""

    from infrastructure.db import SCHEMA_VERSION, Database

    db = Database(tmp_path / "club.db")
    try:
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
    finally:
        db.close()
