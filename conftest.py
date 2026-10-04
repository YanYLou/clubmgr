"""pytest 共享 fixture（阶段 0.5 起本文件不再承担 sys.path 锚点，见 pytest.ini）。

阶段 1 新增：``db``（内存库 + 事务泄漏检查）、``services``（装配好的服务层）、
``club``（最小社团：社长 / 运营2 / 人事 / 普通社员 + 一种耗材 + 每人 200 克额度）。
"""

from types import SimpleNamespace

import pytest

from domain.models import Role
from infrastructure.db import Database
from main import build_services


@pytest.fixture
def db():
    """内存库；测试结束时检查没有忘记退出的事务。"""
    database = Database(":memory:")
    yield database
    assert not database.in_transaction, "有测试/服务忘记退出 with db.transaction()"
    database.close()


@pytest.fixture
def services(db):
    """装配好的服务层（与 CLI 用的是同一套 main.build_services）。"""
    return build_services(db)


@pytest.fixture
def club(services):
    """最小社团：社长 / 运营2 / 人事 / 普通社员 + 一种耗材 + 每人 200 克额度。"""
    president = services.member.bootstrap("社长", student_id="10001")
    op2 = services.member.create_member(president.id, "运营2",
                                        role=Role.OP2, student_id="10002")
    hr = services.member.create_member(president.id, "人事",
                                       role=Role.HR, student_id="10003")
    member = services.member.create_member(hr.id, "普通社员", student_id="10004")
    filament = services.filament.create_filament(
        president.id, "PLA 白", material="PLA", color="白", unit_price=0.1)
    services.quota.init_semester(president.id, 200)
    return SimpleNamespace(president=president, op2=op2, hr=hr,
                           member=member, filament=filament)
