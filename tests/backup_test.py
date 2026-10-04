"""阶段 2.4：数据库备份测试。"""

import sqlite3

import pytest

from infrastructure.backup import (create_backup, default_backup_dir,
                                   list_backups, prune_backups, verify_backup)
from infrastructure.db import Database


@pytest.fixture
def db_file(tmp_path):
    """一个带数据的真实库文件（备份不能用 :memory:）。"""
    path = tmp_path / "club.db"
    db = Database(path)
    with db.transaction():
        db.conn.execute("INSERT INTO members (name, student_id) VALUES ('社长', '10001')")
    db.close()
    return path


def test_create_backup_is_readable_and_complete(db_file):
    backup = create_backup(db_file)

    assert backup.exists()
    assert backup.parent == default_backup_dir(db_file)

    connection = sqlite3.connect(backup)
    try:
        assert connection.execute("SELECT name FROM members").fetchone()[0] == "社长"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_create_backup_rejects_missing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_backup(tmp_path / "nope.db")


def test_backup_keeps_working_database_untouched(db_file):
    create_backup(db_file)
    db = Database(db_file)          # 备份之后原库照样能打开、能写
    try:
        with db.transaction():
            db.conn.execute("INSERT INTO members (name) VALUES ('张三')")
        count = db.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        assert count == 2
    finally:
        db.close()


def test_prune_keeps_newest(db_file, tmp_path):
    out_dir = tmp_path / "backups"
    made = [create_backup(db_file, out_dir, keep=100) for _ in range(3)]
    assert len(list_backups(out_dir)) == 3

    removed = prune_backups(out_dir, keep=1)

    assert removed == made[:2]
    assert list_backups(out_dir) == [made[-1]]


def test_list_backups_is_sorted_and_tolerates_missing_dir(tmp_path):
    assert list_backups(tmp_path / "nope") == []


def test_verify_backup_deletes_broken_file(tmp_path):
    broken = tmp_path / "club-broken.db"
    broken.write_text("not a database", encoding="utf-8")

    with pytest.raises(RuntimeError):
        verify_backup(broken)

    assert not broken.exists()


def test_verify_backup_rejects_empty_database(tmp_path):
    empty = tmp_path / "club-empty.db"
    sqlite3.connect(empty).close()          # 合法但一张表都没有

    with pytest.raises(RuntimeError):
        verify_backup(empty)
