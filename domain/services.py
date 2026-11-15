"""业务服务层。

所有写操作都在这里做权限校验和业务校验，再调用仓储。
本层只依赖 domain 内的抽象（repositories 接口 + permissions），
不依赖 infrastructure 的 SQLite 实现。
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import date
from typing import Protocol

from domain.models import Member, Record, Reservation, Role
from domain.permissions import Action, require
from domain.repositories import (
    MemberRepository,
    RecordRepository,
    ReservationRepository,
)


class TransactionManager(Protocol):
    """领域层对事务的最小抽象，由 infrastructure 的 Database 结构满足。"""

    def transaction(self) -> AbstractContextManager: ...


def _require_operator(
    member_repo: MemberRepository, operator_id: int, action: Action
) -> Member:
    """取操作员并校验其角色是否拥有执行 action 的权限。"""
    operator = member_repo._get(operator_id)
    if operator is None:
        raise ValueError(f"操作员 {operator_id} 不存在")
    require(operator.role, action)
    return operator


class MemberService:
    def __init__(self, member_repo: MemberRepository, tx: TransactionManager) -> None:
        self._repo = member_repo
        self._tx = tx

    # ---- 查询 ----
    def get(self, member_id: int) -> Member | None:
        return self._repo._get(member_id)

    def list_members(self, **filters) -> list[Member]:
        return self._repo._list(**filters)

    def find_by_student_id(self, student_id: str) -> Member | None:
        return self._repo.find_by_student_id(student_id)

    def find_by_name(self, name: str) -> Member | None:
        return self._repo.find_by_student_name(name)

    def list_by_role(self, role: Role) -> list[Member]:
        return self._repo.list_by_role(role)

    # ---- 写操作 ----
    def register(self, member: Member, operator_id: int) -> Member:
        """注册新社员。需要 MANAGE_MEMBERS 权限。"""
        _require_operator(self._repo, operator_id, Action.MANAGE_MEMBERS)
        self._validate(member)
        if member.student_id and self._repo.find_by_student_id(member.student_id):
            raise ValueError(f"学号 {member.student_id} 已存在")
        with self._tx.transaction():
            return self._repo._create(member)

    def update(self, member: Member, operator_id: int) -> None:
        """更新社员资料。需要 MANAGE_MEMBERS 权限。"""
        _require_operator(self._repo, operator_id, Action.MANAGE_MEMBERS)
        if member.id is None:
            raise ValueError("更新社员需要提供 id")
        if self._repo._get(member.id) is None:
            raise ValueError(f"社员 {member.id} 不存在")
        with self._tx.transaction():
            self._repo._update(member)

    def leave(self, member_id: int, operator_id: int) -> Member:
        """退社：把 status 置为 left，保留历史记录。需要 MANAGE_MEMBERS 权限。"""
        _require_operator(self._repo, operator_id, Action.MANAGE_MEMBERS)
        with self._tx.transaction():
            member = self._repo._get(member_id)
            if member is None:
                raise ValueError(f"社员 {member_id} 不存在")
            member.status = "left"
            self._repo._update(member)
            return member

    @staticmethod
    def _validate(member: Member) -> None:
        if not member.name or not member.name.strip():
            raise ValueError("社员姓名不能为空")


class RecordService:
    def __init__(
        self,
        record_repo: RecordRepository,
        member_repo: MemberRepository,
        tx: TransactionManager,
    ) -> None:
        self._repo = record_repo
        self._members = member_repo
        self._tx = tx

    # ---- 查询 ----
    def list_records(self) -> list[Record]:
        return self._repo._list()

    def list_by_member(self, member_id: int) -> list[Record]:
        return self._repo.list_by_member(member_id)

    def list_by_date_range(self, start: date, end: date) -> list[Record]:
        return self._repo.list_by_date_range(start, end)

    # ---- 写操作 ----
    def add(self, record: Record, operator_id: int) -> Record:
        """记录一次打印。需要 MANAGE_RECORDS 权限。"""
        _require_operator(self._members, operator_id, Action.MANAGE_RECORDS)
        self._validate(record)
        record.operator_id = operator_id
        with self._tx.transaction():
            return self._repo._create(record)

    def _validate(self, record: Record) -> None:
        if not record.member_id:
            raise ValueError("缺少打印社员 member_id")
        if self._members._get(record.member_id) is None:
            raise ValueError(f"社员 {record.member_id} 不存在")
        if not record.printer_name.strip():
            raise ValueError("打印机名称不能为空")
        if record.consumption < 0:
            raise ValueError("耗材消耗量不能为负")


class ReservationService:
    def __init__(
        self,
        reservation_repo: ReservationRepository,
        member_repo: MemberRepository,
        tx: TransactionManager,
    ) -> None:
        self._repo = reservation_repo
        self._members = member_repo
        self._tx = tx

    # ---- 查询 ----
    def list_reservations(self) -> list[Reservation]:
        return self._repo._list()

    def list_by_week(self, week_start: date) -> list[Reservation]:
        return self._repo.list_by_week(week_start)

    # ---- 写操作 ----
    def create(self, reservation: Reservation, operator_id: int) -> Reservation:
        """创建预约。需要 MANAGE_RESERVATIONS 权限。"""
        _require_operator(self._members, operator_id, Action.MANAGE_RESERVATIONS)
        self._validate(reservation)
        reservation.operator_id = operator_id
        with self._tx.transaction():
            return self._repo._create(reservation)

    def update_status(
        self, reservation_id: int, status: str, operator_id: int
    ) -> Reservation:
        """更新预约状态。需要 MANAGE_RESERVATIONS 权限。"""
        _require_operator(self._members, operator_id, Action.MANAGE_RESERVATIONS)
        with self._tx.transaction():
            reservation = self._repo._get(reservation_id)
            if reservation is None:
                raise ValueError(f"预约 {reservation_id} 不存在")
            reservation.status = status
            self._repo._update(reservation)
            return reservation

    def _validate(self, reservation: Reservation) -> None:
        if not reservation.member_id:
            raise ValueError("缺少预约社员 member_id")
        if self._members._get(reservation.member_id) is None:
            raise ValueError(f"社员 {reservation.member_id} 不存在")
