
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
    assert member.role == Role.MEMBER
    assert member.join_date == "2026-09-01"
    assert member.note == "No notes"
    