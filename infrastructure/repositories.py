"""SQLite 仓储：通用 CRUD + 具体仓储。

阶段 0.4：
- 新增 ``_from_row`` 钩子：默认按 dataclass 字段的类型注解还原类型
  （``Role`` 枚举 / ``date`` / ``datetime`` / ``bool`` / ``int`` / ``float``）。
  原实现是 ``entity_cls(*row)``：写进去是 ``Role``、``date``，读出来却变成
  ``str`` / ``int``，``member.join_date == date(2026, 9, 1)`` 直接为 False。
- 修改 ``_get`` / ``_list``：改为经由 ``_from_row`` 构造实体。

阶段 1（本次新增）：
- 新增 ``_columns`` / ``_query`` / ``_query_one`` / ``_first`` / ``_scalar`` 复用工具。
- 新增 7 个具体仓储（member / record / quota / filament / inventory / fund /
  contribution），把 ``domain/repositories.py`` 的抽象接口落地；专用查询只写在
  这一层，服务层不写 SQL。预约（reservations）仓储属于阶段 2。
"""

import sqlite3
import types as _types
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from enum import Enum
from typing import Any, ClassVar, Protocol, TypeVar, Union, get_args, get_origin, get_type_hints

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
from domain.repositories import (
    ContributionRepository,
    FilamentRepository,
    FundTransactionRepository,
    InventoryTransactionRepository,
    MemberRepository,
    QuotaTransactionRepository,
    RecordRepository,
    Repository,
)
from infrastructure.db import Database

class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]

T = TypeVar("T", bound=DataclassInstance)

PRIMARY_KEY = "id"

_NONE_TYPE = type(None)


def _coerce_value(value: Any, annotation: Any) -> Any:
    """按字段类型注解，把 SQLite 返回的原始值还原成 Python 类型。"""
    if value is None or annotation is None:
        return value

    origin = get_origin(annotation)
    if origin is Union or origin is _types.UnionType:       # Optional[X] / X | None
        args = [a for a in get_args(annotation) if a is not _NONE_TYPE]
        if len(args) == 1:
            return _coerce_value(value, args[0])
        return value

    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return annotation(value)
        if annotation is bool:
            return bool(value)
        if annotation is date:
            return value if isinstance(value, date) else date.fromisoformat(str(value))
        if annotation is datetime:
            return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if annotation is int:
            return int(value)
        if annotation is float:
            return float(value)
    return value

class SQLite3Repository(Repository[T]):
    table: str
    entity_cls: type[T]

    def __init__(self, db : Database) -> None:
        self.db = db
        self.conn = db.conn
        # 阶段 0.4 新增：缓存字段名与类型注解，供 _from_row 还原类型
        self._field_names = tuple(f.name for f in fields(self.entity_cls))
        self._field_types = self._resolve_field_types()


    # 阶段 0.4 新增：类型还原
    def _resolve_field_types(self) -> dict[str, Any]:
        """取 entity_cls 的字段类型注解；注解无法解析时退化为不还原类型。"""
        try:
            hints = get_type_hints(self.entity_cls)
        except Exception:
            return {}
        return {name: hints.get(name) for name in self._field_names}


    def _from_row(self, row) -> T:
        """把一行记录还原成实体对象（子类可覆盖本钩子做特殊处理）。

        - 行对象带列名（``sqlite3.Row``）时按列名构造，并按类型注解还原类型；
        - 退化成普通元组时按字段顺序构造（与原实现一致）。
        """
        if hasattr(row, "keys"):
            values = {
                name: _coerce_value(row[name], self._field_types.get(name))
                for name in row.keys()
                if name in self._field_types
            }
            return self.entity_cls(**values)
        return self.entity_cls(*row)


    # 阶段 1 新增：给具体仓储复用的查询工具
    @property
    def _columns(self) -> str:
        """实体字段名列表（与表列名一致），供自定义 SQL 使用。"""
        return ", ".join(self._field_names)


    def _query(self, sql: str, params: tuple = ()) -> list[T]:
        """执行自定义 SELECT，并按字段类型还原成实体列表。"""
        return [self._from_row(row) for row in self.conn.execute(sql, params).fetchall()]


    def _query_one(self, sql: str, params: tuple = ()) -> T | None:
        """执行自定义 SELECT，返回第一条实体或 None。"""
        row = self.conn.execute(sql, params).fetchone()
        return self._from_row(row) if row else None


    def _first(self, **filters) -> T | None:
        """按等值条件取第一条，没有则返回 None。"""
        rows = self._list(**filters)
        return rows[0] if rows else None


    def _scalar(self, sql: str, params: tuple = ()) -> float:
        """取单个聚合值（SUM / COUNT），NULL 视为 0。"""
        row = self.conn.execute(sql, params).fetchone()
        return float(row[0]) if row is not None and row[0] is not None else 0.0


    # CREATE METHOD
    def _create(self, entity: T) -> T:

        all_cols = [f.name for f in fields(entity)]
        insert_cols = [c for c in all_cols if c != PRIMARY_KEY]
        cols_clause = ", ".join(col for col in insert_cols)
        placeholders = ", ".join("?" for _ in insert_cols)

        sql = f"INSERT INTO {self.table} ({cols_clause}) VALUES ({placeholders})"
        params = tuple(getattr(entity, c) for c in insert_cols)

        cur = self.conn.execute(sql, params)

        newid = cur.lastrowid
        return replace(entity, **{PRIMARY_KEY: newid})


    # GET METHOD
    def _get(self, entity_id: int) -> T | None:

        sql = f"SELECT {self._columns} FROM {self.table} WHERE {PRIMARY_KEY} = ?"
        row = self.conn.execute(sql, (entity_id,)).fetchone()
        return self._from_row(row) if row else None      # 阶段 0.4 修改：原为 entity_cls(*row)


    # UPDATE METHOD
    def _update(self, entity: T) -> None:

        if getattr(entity, PRIMARY_KEY) is None:
            raise ValueError(f"UPDATE method needs '{PRIMARY_KEY}'!")

        all_cols = [f.name for f in fields(entity)]
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
        where_clause = ""
        params: tuple = ()

        if filters:
            valid_cols = {f.name for f in fields(self.entity_cls)}
            bad = set(filters) - valid_cols
            if bad:
                raise ValueError(f"Illegal filter(s): {bad}")

            where_clause = " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
            params = tuple(filters.values())

        sql = f"SELECT {self._columns} FROM {self.table}{where_clause}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]      # 阶段 0.4 修改：原为 entity_cls(*row)


# ---------------------------------------------------------------------------
# 阶段 1 新增：具体仓储
# 把 domain/repositories.py 的抽象接口落到 SQLite。专用查询只写在这里，
# 服务层不写 SQL。预约（reservations）仓储属于阶段 2。
# ---------------------------------------------------------------------------

class SQLiteMemberRepo(SQLite3Repository[Member], MemberRepository):
    table = "members"
    entity_cls = Member

    def find_by_student_id(self, student_id: str) -> Member | None:
        return self._first(student_id=student_id)

    def find_by_student_name(self, student_name: str) -> Member | None:
        return self._first(name=student_name)

    def list_by_role(self, role: Role) -> list[Member]:
        return self._list(role=role)

    def list_active(self) -> list[Member]:
        """在社社员（阶段 1 新增，学期初发额度时用）。"""
        return self._list(status="active")


class SQLiteRecordRepo(SQLite3Repository[Record], RecordRepository):
    table = "records"
    entity_cls = Record

    def list_by_member(self, member_id: int) -> list[Record]:
        return self._query(
            f"SELECT {self._columns} FROM records WHERE member_id = ? ORDER BY date, id",
            (member_id,),
        )

    def list_by_date_range(self, start: date, end: date) -> list[Record]:
        return self._query(
            f"SELECT {self._columns} FROM records "
            "WHERE date BETWEEN ? AND ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        )


class SQLiteQuotaRepo(SQLite3Repository[QuotaTransaction], QuotaTransactionRepository):
    table = "quota_transactions"
    entity_cls = QuotaTransaction

    def balance_of(self, member_id: int) -> float:
        return self._scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM quota_transactions WHERE member_id = ?",
            (member_id,),
        )

    def list_by_member(self, member_id: int) -> list[QuotaTransaction]:
        return self._query(
            f"SELECT {self._columns} FROM quota_transactions "
            "WHERE member_id = ? ORDER BY date, id",
            (member_id,),
        )

    def has_type(self, member_id: int, txn_type: str) -> bool:
        """该社员是否已有某类流水（阶段 1 新增，防止学期额度重复发放）。"""
        row = self.conn.execute(
            "SELECT 1 FROM quota_transactions WHERE member_id = ? AND type = ? LIMIT 1",
            (member_id, txn_type),
        ).fetchone()
        return row is not None


class SQLiteFilamentRepo(SQLite3Repository[Filament], FilamentRepository):
    table = "filaments"
    entity_cls = Filament

    def find_by_name(self, name: str) -> Filament | None:
        """按名字精确查找（阶段 1 新增，供 CLI 选耗材用）。"""
        return self._first(name=name)


class SQLiteInventoryRepo(SQLite3Repository[InventoryTransaction], InventoryTransactionRepository):
    table = "inventory_transactions"
    entity_cls = InventoryTransaction

    def stock_of(self, filament_id: int) -> float:
        return self._scalar(
            "SELECT COALESCE(SUM(amount), 0) FROM inventory_transactions WHERE filament_id = ?",
            (filament_id,),
        )

    def list_by_filament(self, filament_id: int) -> list[InventoryTransaction]:
        return self._query(
            f"SELECT {self._columns} FROM inventory_transactions "
            "WHERE filament_id = ? ORDER BY date, id",
            (filament_id,),
        )


class SQLiteFundRepo(SQLite3Repository[FundTransaction], FundTransactionRepository):
    table = "fund_transactions"
    entity_cls = FundTransaction

    def balance(self) -> float:
        return self._scalar("SELECT COALESCE(SUM(amount), 0) FROM fund_transactions")

    def list_by_date_range(self, start: date, end: date) -> list[FundTransaction]:
        """按日期区间查流水（阶段 1 新增，报表用；不在抽象接口里）。"""
        return self._query(
            f"SELECT {self._columns} FROM fund_transactions "
            "WHERE date BETWEEN ? AND ? ORDER BY date, id",
            (start.isoformat(), end.isoformat()),
        )


class SQLiteContributionRepo(SQLite3Repository[Contribution], ContributionRepository):
    table = "contributions"
    entity_cls = Contribution

    def list_by_member(self, member_id: int) -> list[Contribution]:
        return self._query(
            f"SELECT {self._columns} FROM contributions "
            "WHERE member_id = ? ORDER BY date, id",
            (member_id,),
        )