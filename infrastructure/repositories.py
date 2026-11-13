from domain.repositories import (
    Repository,
    MemberRepository as MemberRepositoryABC,
    RecordRepository as RecordRepositoryABC,
    ReservationRepository as ReservationRepositoryABC,
)
from domain.models import *
from infrastructure.db import Database
from typing import Any, TypeVar, cast
from datetime import date, timedelta
from dataclasses import fields, replace

import sqlite3

T = TypeVar("T")


def _dc_fields(obj: Any) -> tuple[Any, ...]:
    """dataclasses.fields 的宽松类型包装，规避 dataclass 协议的严格检查。"""
    return fields(obj)


def _dc_replace(obj: Any, **changes: Any) -> Any:
    """dataclasses.replace 的宽松类型包装。"""
    return replace(obj, **changes)

PRIMARY_KEY = "id"

class SQLite3Repository(Repository[T]):
    table: str
    entity_cls: type[T]

    def __init__(self, db : Database) -> None:
        self.db = db
        self.conn = db.conn


    # CREATE METHOD
    def _create(self, entity: T) -> T:

        all_cols = [f.name for f in _dc_fields(entity)]
        insert_cols = [c for c in all_cols if c != PRIMARY_KEY]
        cols_clause = ", ".join(col for col in insert_cols)
        placeholders = ", ".join("?" for _ in insert_cols)

        sql = f"INSERT INTO {self.table} ({cols_clause}) VALUES ({placeholders})"
        params = tuple(getattr(entity, c) for c in insert_cols)

        cur = self.conn.execute(sql, params)

        newid = cur.lastrowid
        return cast(T, _dc_replace(entity, **{PRIMARY_KEY: newid}))


    # GET METHOD
    def _get(self, entity_id: int) -> T | None:

        cols = ", ".join(f.name for f in _dc_fields(self.entity_cls))
        sql = f"SELECT {cols} FROM {self.table} WHERE {PRIMARY_KEY} = ?"
        row = self.conn.execute(sql, (entity_id,)).fetchone()
        return self.entity_cls(*row) if row else None


    # UPDATE METHOD
    def _update(self, entity: T) -> None:

        if getattr(entity, PRIMARY_KEY) is None:
            raise ValueError(f"UPDATE method needs '{PRIMARY_KEY}'!")

        all_cols = [f.name for f in _dc_fields(entity)]
        set_cols = [c for c in all_cols if c != PRIMARY_KEY]
        if not set_cols:
            return
        
        set_clause = ", ".join(f"{c} = ?" for c in set_cols)

        params = [getattr(entity, c) for c in set_cols]
        params.append(getattr(entity, PRIMARY_KEY))
        params = tuple(params)

        sql = f"UPDATE {self.table} SET {set_clause} WHERE {PRIMARY_KEY} = ?"
        self.conn.execute(sql, params)


    # DELETE METHOD
    def _delete(self, entity_id: int) -> None:

        sql = f"DELETE FROM {self.table} WHERE {PRIMARY_KEY} = ?"
        self.conn.execute(sql, (entity_id,))


    # LIST METHOD
    def _list(self, **filters) -> list[T]:
        cols = ", ".join(f.name for f in _dc_fields(self.entity_cls))

        where_clause = ""
        params: tuple = ()

        if filters:
            valid_cols = {f.name for f in _dc_fields(self.entity_cls)}
            bad = set(filters) - valid_cols
            if bad:
                raise ValueError(f"Illegal filter(s): {bad}")

            where_clause = " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
            params = tuple(filters.values())

        sql = f"SELECT {cols} FROM {self.table}{where_clause}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self.entity_cls(*row) for row in rows]


    # HELPERS FOR CONCRETE REPOSITORIES
    def _select_cols(self) -> str:
        return ", ".join(f.name for f in _dc_fields(self.entity_cls))

    def _from_rows(self, rows) -> list[T]:
        return [self.entity_cls(*row) for row in rows]

    def _find_by_date_range(self, start: date, end: date) -> list[T]:
        sql = f"SELECT {self._select_cols()} FROM {self.table} WHERE date BETWEEN ? AND ?"
        rows = self.conn.execute(sql, (start.isoformat(), end.isoformat())).fetchall()
        return self._from_rows(rows)


# Concrete SQLite repositories

class MemberRepository(SQLite3Repository[Member], MemberRepositoryABC):
    table = "members"
    entity_cls = Member

    def find_by_student_id(self, student_id: str) -> Member | None:
        rows = self._list(student_id=student_id)
        return rows[0] if rows else None

    def list_by_role(self, role: Role) -> list[Member]:
        return self._list(role=role.value)

    def find_by_student_name(self, student_name: str) -> Member | None:
        rows = self._list(name=student_name)
        return rows[0] if rows else None

    def register_student(self, student: Member) -> Member:
        return self._create(student)


class RecordRepository(SQLite3Repository[Record], RecordRepositoryABC):
    table = "records"
    entity_cls = Record

    def list_by_member(self, member_id: int) -> list[Record]:
        return self._list(member_id=member_id)

    def list_by_date_range(self, start: date, end: date) -> list[Record]:
        return self._find_by_date_range(start, end)


class ReservationRepository(SQLite3Repository[Reservation], ReservationRepositoryABC):
    table = "reservations"
    entity_cls = Reservation

    def list_by_week(self, week_start: date) -> list[Reservation]:
        end = week_start + timedelta(days=6)
        return self._find_by_date_range(week_start, end)
