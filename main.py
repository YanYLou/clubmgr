"""项目路径、数据库位置与服务装配。

阶段 0.1 修正：
- ``ROOT_DIR`` 原来用了两层 ``dirname``，指到的是仓库的**父目录**
  （例如 ``E:\\clubmgr.worktrees``），导致 ``DB_PATH`` 落在仓库之外且目录不存在。
  现在改为 ``main.py`` 所在目录，即仓库根。
- 数据库文件统一为 ``data/club.db``：原来 ``main.py`` 写 ``data/data.db``，
  而 README 写 ``data/club.db``，两处不一致。
- 目录创建交给 ``infrastructure.db.Database``（连接前自动 mkdir），
  这里保留 :func:`ensure_data_dir` 供入口脚本显式调用。

阶段 1.4 新增：:func:`build_repositories` / :func:`build_services` —— 这是**唯一的
组装点**。``domain`` 只依赖抽象接口，把 SQLite 实现注入进去只能在这里做。
"""

from pathlib import Path
from types import SimpleNamespace

from domain.services import (
    ContributionService,
    FilamentService,
    FundService,
    MemberService,
    NotificationService,
    PrinterService,
    QuotaService,
    RecordService,
    ReportService,
    ReservationService,
    Services,
    SettingsService,
    StockAlertService,
    UserService,
)
from infrastructure.db import Database
from infrastructure.repositories import (
    SQLiteContributionRepo,
    SQLiteFilamentRepo,
    SQLiteFundRepo,
    SQLiteInventoryRepo,
    SQLiteMemberRepo,
    SQLiteNotificationRepo,
    SQLitePrinterRepo,
    SQLiteQuotaRepo,
    SQLiteRecordRepo,
    SQLiteReservationRepo,
    SQLiteSettingRepo,
    SQLiteUserRepo,
)

ROOT_DIR = Path(__file__).resolve().parent
DOMAIN_DIR = ROOT_DIR / "domain"
DATA_DIR = ROOT_DIR / "data"

DB_FILENAME = "club.db"
DB_PATH = DATA_DIR / DB_FILENAME


def ensure_data_dir() -> Path:
    """确保 ``data/`` 目录存在并返回它（首次运行、备份脚本等入口可调用）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def build_repositories(db: Database) -> SimpleNamespace:
    """构造具体仓储（阶段 1.4 起，逐步加入 users / reservations / settings / notifications）。"""
    return SimpleNamespace(
        member=SQLiteMemberRepo(db),
        record=SQLiteRecordRepo(db),
        quota=SQLiteQuotaRepo(db),
        filament=SQLiteFilamentRepo(db),
        inventory=SQLiteInventoryRepo(db),
        fund=SQLiteFundRepo(db),
        contribution=SQLiteContributionRepo(db),
        user=SQLiteUserRepo(db),
        reservation=SQLiteReservationRepo(db),
        setting=SQLiteSettingRepo(db),
        notification=SQLiteNotificationRepo(db),
        printer=SQLitePrinterRepo(db),
    )


def build_services(db: Database) -> Services:
    """把仓储注入服务层（阶段 1.4 起）。"""
    repos = build_repositories(db)

    # 阶段 3.2：这几个服务互相引用，先建好再注入
    settings = SettingsService(db, repos.member, repos.setting)
    notification = NotificationService(db, repos.member, repos.notification)
    stock_alert = StockAlertService(db, repos.member, settings, repos.inventory,
                                    repos.filament, notification)

    return Services(
        member=MemberService(db, repos.member),
        quota=QuotaService(db, repos.member, repos.quota),
        record=RecordService(db, repos.member, repos.record, repos.quota,
                             repos.filament, repos.inventory, alerts=stock_alert),
        filament=FilamentService(db, repos.member, repos.filament,
                                 repos.inventory, repos.fund),
        fund=FundService(db, repos.member, repos.fund),
        contribution=ContributionService(db, repos.member, repos.contribution,
                                         repos.quota),
        report=ReportService(db, repos.member, repos.record, repos.quota,
                             repos.filament, repos.inventory, repos.fund,
                             repos.contribution),
        user=UserService(db, repos.member, repos.user),
        reservation=ReservationService(db, repos.member, repos.reservation,
                                        notifications=notification),
        settings=settings,
        notification=notification,
        stock_alert=stock_alert,
        printer=PrinterService(db, repos.member, repos.printer),
    )


def open_services(db_path: str | Path | None = None) -> tuple[Database, Services]:
    """便捷入口：打开（必要时自动创建）数据库并装配服务。"""
    db = Database(db_path or DB_PATH)
    return db, build_services(db)


if __name__ == "__main__":
    # 阶段 2.1：命令行入口，见 interfaces/cli.py
    from interfaces.cli import main as cli_main

    raise SystemExit(cli_main())
