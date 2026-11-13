from datetime import date

import pytest

from domain.models import Member, Record, Reservation, Role
from domain.permissions import Action, PermissionDenied, can, require
from domain.services import MemberService, RecordService, ReservationService
from infrastructure.db import Database
from infrastructure.repositories import (
    MemberRepository,
    RecordRepository,
    ReservationRepository,
)


def _seed_member(db, name, role=Role.MEMBER, student_id=None):
    with db.transaction():
        return MemberRepository(db)._create(
            Member(name=name, role=role, student_id=student_id)
        )


def test_permission_matrix_basics():
    assert can(Role.PRESIDENT, Action.MANAGE_RECORDS)
    assert can(Role.OP2, Action.MANAGE_RECORDS)
    assert can(Role.HR, Action.MANAGE_MEMBERS)
    assert can(Role.OP1, Action.MANAGE_RESERVATIONS)
    assert not can(Role.OP2, Action.MANAGE_MEMBERS)
    assert not can(Role.MEMBER, Action.MANAGE_RECORDS)
    # 从数据库读出的是 str，也能正确判断
    assert can("op2", Action.MANAGE_RECORDS)


def test_require_raises():
    with pytest.raises(PermissionDenied):
        require(Role.MEMBER, Action.MANAGE_MEMBERS)


def test_member_register_requires_permission():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    svc = MemberService(member_repo, db)
    operator = _seed_member(db, name="Op", role=Role.MEMBER)
    with pytest.raises(PermissionDenied):
        svc.register(Member(name="Bob"), operator.id)


def test_hr_can_register_member():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    svc = MemberService(member_repo, db)
    hr = _seed_member(db, name="HR", role=Role.HR)
    member = svc.register(Member(name="Carol", student_id="S001"), hr.id)
    assert member.id is not None
    found = svc.find_by_student_id("S001")
    assert found is not None and found.name == "Carol"


def test_duplicate_student_id_rejected():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    svc = MemberService(member_repo, db)
    hr = _seed_member(db, name="HR", role=Role.HR)
    svc.register(Member(name="D", student_id="S001"), hr.id)
    with pytest.raises(ValueError):
        svc.register(Member(name="E", student_id="S001"), hr.id)


def test_op2_can_add_record():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    record_repo = RecordRepository(db)
    svc = RecordService(record_repo, member_repo, db)
    op2 = _seed_member(db, name="Op2", role=Role.OP2)
    alice = _seed_member(db, name="Alice")
    record = svc.add(
        Record(
            member_id=alice.id,
            printer_name="P1",
            filament_name="PLA",
            consumption=10.5,
        ),
        op2.id,
    )
    assert record.id is not None
    assert svc.list_by_member(alice.id)[0].consumption == 10.5


def test_hr_cannot_add_record():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    record_repo = RecordRepository(db)
    svc = RecordService(record_repo, member_repo, db)
    hr = _seed_member(db, name="HR", role=Role.HR)
    alice = _seed_member(db, name="Alice")
    with pytest.raises(PermissionDenied):
        svc.add(
            Record(
                member_id=alice.id,
                printer_name="P1",
                filament_name="PLA",
                consumption=1.0,
            ),
            hr.id,
        )


def test_op1_can_create_reservation():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    reservation_repo = ReservationRepository(db)
    svc = ReservationService(reservation_repo, member_repo, db)
    op1 = _seed_member(db, name="Op1", role=Role.OP1)
    alice = _seed_member(db, name="Alice")
    r = svc.create(Reservation(member_id=alice.id, date=date(2026, 11, 16)), op1.id)
    assert r.id is not None


def test_reservation_week_list():
    db = Database(":memory:")
    member_repo = MemberRepository(db)
    reservation_repo = ReservationRepository(db)
    svc = ReservationService(reservation_repo, member_repo, db)
    op1 = _seed_member(db, name="Op1", role=Role.OP1)
    alice = _seed_member(db, name="Alice")
    svc.create(Reservation(member_id=alice.id, date=date(2026, 11, 16)), op1.id)
    svc.create(Reservation(member_id=alice.id, date=date(2026, 11, 20)), op1.id)
    svc.create(Reservation(member_id=alice.id, date=date(2026, 11, 23)), op1.id)
    week = svc.list_by_week(date(2026, 11, 16))
    assert len(week) == 2
