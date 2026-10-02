from domain.repositories import Repository
from infrastructure.db import Database
from typing import Protocol, TypeVar, Any, ClassVar
from dataclasses import dataclass, fields, replace

import sqlite3

class DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]

T = TypeVar("T", bound=DataclassInstance)

PRIMARY_KEY = "id"

class SQLite3Repository(Repository[T]):
    table: str
    entity_cls: type[T]

    def __init__(self, db : Database) -> None:
        self.db = db
        self.conn = db.conn


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
        return self.entity_cls(*row) if row else None


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
        return [self.entity_cls(*row) for row in rows]