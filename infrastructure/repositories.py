"""SQLite 仓储的通用实现。

阶段 0.4（本次改动）：
- 新增 ``_from_row`` 钩子：默认按 dataclass 字段的类型注解还原类型
  （``Role`` 枚举 / ``date`` / ``datetime`` / ``bool`` / ``int`` / ``float``）。
  原实现是 ``entity_cls(*row)``：写进去是 ``Role``、``date``，读出来却变成
  ``str`` / ``int``，``member.join_date == date(2026, 9, 1)`` 直接为 False。
- 修改 ``_get`` / ``_list``：改为经由 ``_from_row`` 构造实体。
其余 CRUD 实现未改动。
"""

import sqlite3
import types as _types
from dataclasses import dataclass, fields, replace
from datetime import date, datetime
from enum import Enum
from typing import Any, ClassVar, Protocol, TypeVar, Union, get_args, get_origin, get_type_hints

from domain.repositories import Repository
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

        cols = ", ".join(f.name for f in fields(self.entity_cls))
        sql = f"SELECT {cols} FROM {self.table} WHERE {PRIMARY_KEY} = ?"
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
        cols = ", ".join(f.name for f in fields(self.entity_cls))

        where_clause = ""
        params: tuple = ()

        if filters:
            valid_cols = {f.name for f in fields(self.entity_cls)}
            bad = set(filters) - valid_cols
            if bad:
                raise ValueError(f"Illegal filter(s): {bad}")

            where_clause = " WHERE " + " AND ".join(f"{k} = ?" for k in filters)
            params = tuple(filters.values())

        sql = f"SELECT {cols} FROM {self.table}{where_clause}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]      # 阶段 0.4 修改：原为 entity_cls(*row)