"""数据库备份（阶段 2.4 新增）。

用 sqlite3 的在线备份 API（``Connection.backup``）做**热备份**：备份期间数据库
可以继续读写，不会出现"复制到一半的坏文件"。备份完成后立刻做完整性校验，
不合格的备份会被删掉而不是留着当救命稻草。

    python main.py backup                     # 备份到 data/backups/，默认保留最近 10 份
    python main.py backup --keep 30 --list    # 看现有备份

恢复步骤（手工，程序不自动做）：

1. 停掉 Web 服务与正在跑的 CLI；
2. 把 ``data/club.db`` 改名留底；
3. 把选定的备份复制成 ``data/club.db``，并删掉 ``club.db-wal`` / ``club.db-shm``；
4. 重新启动：程序会校验结构版本，版本不符会明确报错。
"""

import sqlite3
from datetime import datetime
from pathlib import Path

BACKUP_PREFIX = "club-"
BACKUP_SUFFIX = ".db"
DEFAULT_KEEP = 10


def default_backup_dir(db_path: str | Path) -> Path:
    """默认备份目录：数据库同级的 ``backups/``。"""
    return Path(db_path).parent / "backups"


def create_backup(db_path: str | Path, out_dir: str | Path | None = None, *,
                  keep: int = DEFAULT_KEEP) -> Path:
    """热备份数据库，返回备份文件路径；``keep`` 为保留份数。"""
    source = Path(db_path)
    if not source.exists():
        raise FileNotFoundError(f"数据库不存在：{source}")

    target_dir = Path(out_dir) if out_dir else default_backup_dir(source)
    target_dir.mkdir(parents=True, exist_ok=True)
    # 序号固定三位：同一秒内多次备份不会互相覆盖，文件名排序 = 时间排序
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    index = 1
    while True:
        target = target_dir / f"{BACKUP_PREFIX}{stamp}-{index:03d}{BACKUP_SUFFIX}"
        if not target.exists():
            break
        index += 1

    src = sqlite3.connect(source)
    try:
        dest = sqlite3.connect(target)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()

    verify_backup(target)
    prune_backups(target_dir, keep=keep)
    return target


def verify_backup(path: str | Path) -> None:
    """校验备份可用；不合格就删掉并报错。"""
    file = Path(path)
    try:
        connection = sqlite3.connect(file)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:            # 根本不是数据库文件
        file.unlink(missing_ok=True)
        raise RuntimeError(f"备份文件无法读取（{exc}），已删除：{file}") from None

    if integrity != "ok" or tables == 0:
        file.unlink(missing_ok=True)
        raise RuntimeError(
            f"备份校验失败（integrity={integrity}，表数={tables}），已删除：{file}")


def list_backups(out_dir: str | Path) -> list[Path]:
    """按时间从旧到新列出备份文件。"""
    directory = Path(out_dir)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"))


def prune_backups(out_dir: str | Path, *, keep: int = DEFAULT_KEEP) -> list[Path]:
    """只保留最近 ``keep`` 份，返回被删除的文件（keep < 0 表示不清理）。"""
    files = list_backups(out_dir)
    if keep < 0 or len(files) <= keep:
        return []
    removed = files[:len(files) - keep]
    for path in removed:
        path.unlink()
    return removed
