import os

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DOMAIN_DIR = os.path.join(ROOT_DIR, "domain")
DATA_DIR = os.path.join(ROOT_DIR, "data")

DB_PATH = os.path.join(DATA_DIR, "data.db")


def build_services(db_path: str = DB_PATH):
    """组合根：创建 Database 与具体仓储，注入 Service。

    interfaces 层只依赖这里返回的 Service 对象，不自己 new 仓储或写 SQL。
    """
    from infrastructure.db import Database
    from infrastructure.repositories import (
        MemberRepository,
        RecordRepository,
        ReservationRepository,
    )
    from domain.services import MemberService, RecordService, ReservationService

    db = Database(db_path)
    member_repo = MemberRepository(db)
    record_repo = RecordRepository(db)
    reservation_repo = ReservationRepository(db)

    return {
        "db": db,
        "members": MemberService(member_repo, db),
        "records": RecordService(record_repo, member_repo, db),
        "reservations": ReservationService(reservation_repo, member_repo, db),
    }


def seed_president(name: str, db_path: str = DB_PATH):
    """初始化：在空库中直接写入一名社长（首个操作员）。

    系统首次使用时没有可校验权限的操作员，因此绕过 service 的权限校验
    直接落库；之后所有写操作都应走 service 的权限校验。
    """
    from infrastructure.db import Database
    from infrastructure.repositories import MemberRepository
    from domain.models import Member, Role

    db = Database(db_path)
    repo = MemberRepository(db)
    with db.transaction():
        return repo._create(Member(name=name, role=Role.PRESIDENT))