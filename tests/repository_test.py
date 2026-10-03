"""阶段 0.4：仓储读回时的类型还原。

原实现是 ``entity_cls(*row)``，写进去是 ``Role`` / ``date``，读出来变成 ``str``：

    role is Role.HR              -> False
    join_date == date(2026, 9, 1) -> False

现在由 ``SQLite3Repository._from_row`` 按字段类型注解还原。具体仓储属于阶段 1，
这里用最小的测试用仓储验证通用实现。
"""

import datetime
from dataclasses import replace
from datetime import date
from typing import get_type_hints

from domain.models import (
    Contribution,
    FundTransaction,
    InventoryTransaction,
    Member,
    QuotaTransaction,
    Record,
    Role,
)
from infrastructure.db import Database
from infrastructure.repositories import SQLite3Repository


class MemberRepo(SQLite3Repository[Member]):
    table = "members"
    entity_cls = Member


class RecordRepo(SQLite3Repository[Record]):
    table = "records"
    entity_cls = Record


def test_member_role_and_date_are_restored():
    db = Database(":memory:")
    repo = MemberRepo(db)

    with db.transaction():
        created = repo._create(Member(
            name="Alice",
            role=Role.HR,
            join_date=date(2026, 9, 1),
        ))

    got = repo._get(created.id)
    assert isinstance(got.role, Role)
    assert got.role is Role.HR
    assert isinstance(got.join_date, date)
    assert got.join_date == date(2026, 9, 1)
    db.close()


def test_list_also_restores_types():
    db = Database(":memory:")
    repo = MemberRepo(db)

    with db.transaction():
        repo._create(Member(name="Alice", role=Role.OP2, join_date=date(2026, 9, 1)))

    got = repo._list(role=Role.OP2)[0]
    assert got.role is Role.OP2
    assert got.join_date == date(2026, 9, 1)
    db.close()


def test_record_bool_and_float_are_restored():
    db = Database(":memory:")
    member_repo = MemberRepo(db)
    record_repo = RecordRepo(db)

    with db.transaction():
        member = member_repo._create(Member(name="Alice"))
        record_repo._create(Record(
            member_id=member.id,
            printer_name="P1",
            filament_name="PLA 白",
            consumption=12.5,
            date=date(2026, 9, 1),
            operator_id=member.id,
            is_charged=True,
            fee=3.0,
        ))

    got = record_repo._list(member_id=member.id)[0]
    assert got.is_charged is True                     # 原来是 1（int）
    assert got.date == date(2026, 9, 1)               # 原来是 "2026-09-01"
    assert isinstance(got.consumption, float)
    assert got.consumption == 12.5
    db.close()


def test_null_optional_field_stays_none():
    db = Database(":memory:")
    repo = MemberRepo(db)

    with db.transaction():
        created = repo._create(Member(name="Bob"))     # join_date 默认 None

    assert repo._get(created.id).join_date is None
    db.close()


def test_from_row_hook_can_be_overridden():
    """子类可以覆盖 _from_row 做特殊处理，钩子保持可扩展。"""

    class UpperNameRepo(MemberRepo):
        def _from_row(self, row):
            member = super()._from_row(row)
            return replace(member, name=member.name.upper())

    db = Database(":memory:")
    repo = UpperNameRepo(db)

    with db.transaction():
        repo._create(Member(name="alice"))

    assert repo._list()[0].name == "ALICE"
    db.close()


def test_date_field_annotation_is_not_shadowed_by_field_name():
    """既有缺陷回归：字段名为 ``date`` 时，注解必须是 datetime.date。

    ``date: date = field(...)`` 会让注解取到 ``Field`` 对象（见 domain/models.py
    模块说明），那样这个字段就永远无法按类型还原。
    """
    for cls in (Record, QuotaTransaction, InventoryTransaction, FundTransaction, Contribution):
        assert get_type_hints(cls)["date"] is datetime.date, cls.__name__
