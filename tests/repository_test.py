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
from typing import Optional, get_type_hints

from domain.models import (
    Contribution,
    Filament,
    FundTransaction,
    InventoryTransaction,
    Member,
    QuotaTransaction,
    Record,
    Role,
)
from infrastructure.db import Database
from infrastructure.repositories import SQLite3Repository, _coerce_value


class MemberRepo(SQLite3Repository[Member]):
    table = "members"
    entity_cls = Member


class RecordRepo(SQLite3Repository[Record]):
    table = "records"
    entity_cls = Record


class FilamentRepo(SQLite3Repository[Filament]):
    table = "filaments"
    entity_cls = Filament


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


def test_record_date_and_float_are_restored():
    db = Database(":memory:")
    member_repo = MemberRepo(db)
    filament_repo = FilamentRepo(db)
    record_repo = RecordRepo(db)

    with db.transaction():
        member = member_repo._create(Member(name="Alice"))
        filament = filament_repo._create(Filament(name="PLA 白", material="PLA"))
        record_repo._create(Record(
            member_id=member.id,
            printer_name="P1",
            filament_id=filament.id,
            filament_name=filament.name,
            consumption=12.5,
            date=date(2026, 9, 1),
            operator_id=member.id,
        ))

    got = record_repo._list(member_id=member.id)[0]
    assert got.date == date(2026, 9, 1)               # 原来是 "2026-09-01"
    assert isinstance(got.consumption, float)
    assert got.consumption == 12.5
    assert got.filament_id == filament.id             # 阶段 1 新增的外键
    db.close()


def test_coerce_value_bool_and_optional():
    """模型里已没有 bool 字段（is_charged 已删），直接测通用还原函数。"""
    assert _coerce_value(1, bool) is True
    assert _coerce_value(0, bool) is False
    assert _coerce_value(None, datetime.date) is None
    assert _coerce_value("2026-09-01", Optional[datetime.date]) == date(2026, 9, 1)
    assert _coerce_value("hr", Role) is Role.HR


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
