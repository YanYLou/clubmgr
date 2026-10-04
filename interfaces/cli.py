"""命令行界面（阶段 2.1 新增）。

操作人用 ``--operator`` 指定，可以是 **id / 学号 / 姓名**。所有权限判断都在服务层，
CLI 只负责解析参数与打印结果。

    python main.py member bootstrap --name 社长 --student-id 10001
    python main.py --operator 10001 member add --name 张三 --student-id 10005
    python main.py --operator 10001 filament add --name "PLA 白" --unit-price 0.1
    python main.py --operator 10001 quota init --amount 200
    python main.py --operator 10002 record print --member 10005 --filament "PLA 白" --grams 42.5
    python main.py --operator 10001 report quota
    python main.py --operator 10005 report statement

``--json`` 放在子命令之前，输出机器可读结果。
"""

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from domain.models import Role
from infrastructure.backup import (DEFAULT_KEEP, create_backup,
                                   default_backup_dir, list_backups)
from infrastructure.db import SCHEMA_VERSION, Database
from main import DB_PATH, build_services


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

@dataclass
class Result:
    """一条命令的结果：标题 + 表格 + 附加文本 + 供 ``--json`` 用的原始数据。"""

    title: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    payload: Any = None
    extra: list[str] = field(default_factory=list)
    exit_code: int = 0


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _table(title: str, items, columns: Sequence[str] | None = None,
           payload: Any = None, extra: Sequence[str] | None = None) -> Result:
    """把 dataclass 列表变成结果表。"""
    items = list(items)
    if not items:
        return Result(title, [], [], payload if payload is not None else [],
                      list(extra or []))
    names = list(columns) if columns else [f.name for f in fields(items[0])]
    rows = [[_fmt(getattr(item, name)) for name in names] for item in items]
    if payload is None:
        payload = [asdict(item) if is_dataclass(item) else item for item in items]
    return Result(title, names, rows, payload, list(extra or []))


def _render(result: Result) -> list[str]:
    lines: list[str] = []
    if result.title:
        lines.append(result.title)
    if result.headers:
        lines.append(" | ".join(result.headers))
        if result.rows:
            lines.extend(" | ".join(row) for row in result.rows)
        else:
            lines.append("（无数据）")
    lines.extend(result.extra)
    return lines


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="造梦 3D 打印社团管理工具（CLI）",
    )
    parser.add_argument("--db", help=f"数据库文件路径（默认 {DB_PATH}）")
    parser.add_argument("--operator", help="操作人：id / 学号 / 姓名")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（放在子命令之前）")

    top = parser.add_subparsers(dest="group", required=True)

    # --- member -----------------------------------------------------------
    member = top.add_parser("member", help="社员管理").add_subparsers(
        dest="action", required=True)

    p = member.add_parser("bootstrap", help="空库初始化：创建第一个社长")
    p.add_argument("--name", required=True)
    p.add_argument("--student-id")
    p.add_argument("--qq")
    p.set_defaults(handler=_member_bootstrap)

    p = member.add_parser("add", help="新增社员")
    p.add_argument("--name", required=True)
    p.add_argument("--student-id")
    p.add_argument("--qq")
    p.add_argument("--role", default=Role.MEMBER.value, choices=[r.value for r in Role])
    p.add_argument("--join-date")
    p.add_argument("--note")
    p.set_defaults(handler=_member_add)

    p = member.add_parser("list", help="社员列表")
    p.add_argument("--status", choices=["active", "left"])
    p.add_argument("--role", choices=[r.value for r in Role])
    p.set_defaults(handler=_member_list)

    p = member.add_parser("left", help="退社（只改状态，历史保留）")
    p.add_argument("--member", required=True)
    p.set_defaults(handler=_member_left)

    # --- filament ---------------------------------------------------------
    filament = top.add_parser("filament", help="耗材与库存").add_subparsers(
        dest="action", required=True)

    p = filament.add_parser("add", help="新增耗材")
    p.add_argument("--name", required=True)
    p.add_argument("--material")
    p.add_argument("--color")
    p.add_argument("--unit-price", type=float)
    p.add_argument("--note")
    p.set_defaults(handler=_filament_add)

    p = filament.add_parser("list", help="耗材目录")
    p.set_defaults(handler=_filament_list)

    p = filament.add_parser("purchase", help="采购入库（可同时记经费支出）")
    p.add_argument("--filament", required=True, help="耗材 id 或名称")
    p.add_argument("--grams", type=float, required=True)
    p.add_argument("--cost", type=float, default=0)
    p.add_argument("--date")
    p.add_argument("--note")
    p.set_defaults(handler=_filament_purchase)

    p = filament.add_parser("stock", help="库存表")
    p.set_defaults(handler=_filament_stock)

    # --- quota ------------------------------------------------------------
    quota = top.add_parser("quota", help="额度").add_subparsers(
        dest="action", required=True)

    p = quota.add_parser("init", help="学期初发放额度")
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--member", action="append", help="只发给指定社员（可多次）")
    p.add_argument("--allow-repeat", action="store_true", help="已发过也再发一次")
    p.add_argument("--date")
    p.add_argument("--note")
    p.set_defaults(handler=_quota_init)

    p = quota.add_parser("adjust", help="手工调整额度（必须写备注）")
    p.add_argument("--member", required=True)
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--date")
    p.set_defaults(handler=_quota_adjust)

    p = quota.add_parser("balance", help="查额度（默认查自己）")
    p.add_argument("--member")
    p.set_defaults(handler=_quota_balance)

    # --- record -----------------------------------------------------------
    record = top.add_parser("record", help="打印记录").add_subparsers(
        dest="action", required=True)

    p = record.add_parser("print", help="记录一次打印")
    p.add_argument("--member", required=True, help="谁打印的：id / 学号 / 姓名")
    p.add_argument("--filament", required=True, help="耗材 id 或名称")
    p.add_argument("--grams", type=float, required=True)
    p.add_argument("--printer", default="")
    p.add_argument("--date")
    p.add_argument("--comments")
    p.set_defaults(handler=_record_print)

    p = record.add_parser("list", help="打印记录列表")
    p.add_argument("--member")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(handler=_record_list)

    # --- fund -------------------------------------------------------------
    fund = top.add_parser("fund", help="经费").add_subparsers(
        dest="action", required=True)

    p = fund.add_parser("income", help="收入")
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--date")
    p.set_defaults(handler=_fund_income)

    p = fund.add_parser("expense", help="支出")
    p.add_argument("--amount", type=float, required=True)
    p.add_argument("--note", required=True)
    p.add_argument("--date")
    p.set_defaults(handler=_fund_expense)

    p = fund.add_parser("list", help="经费流水与余额")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(handler=_fund_list)

    # --- contribution -----------------------------------------------------
    contribution = top.add_parser("contribution", help="贡献 / 捐款").add_subparsers(
        dest="action", required=True)

    p = contribution.add_parser("add", help="登记贡献（可奖励额度）")
    p.add_argument("--member", required=True)
    p.add_argument("--amount", type=float, default=0)
    p.add_argument("--type", default="money", choices=["money", "material"])
    p.add_argument("--material-desc")
    p.add_argument("--reward-quota", type=float, default=0)
    p.add_argument("--date")
    p.add_argument("--note")
    p.set_defaults(handler=_contribution_add)

    # --- report -----------------------------------------------------------
    report = top.add_parser("report", help="报表").add_subparsers(
        dest="action", required=True)

    p = report.add_parser("quota", help="全社额度表")
    p.set_defaults(handler=_report_quota)

    p = report.add_parser("stock", help="耗材库存表")
    p.set_defaults(handler=_filament_stock)

    p = report.add_parser("fund", help="经费余额与流水")
    p.add_argument("--start")
    p.add_argument("--end")
    p.set_defaults(handler=_fund_list)

    p = report.add_parser("statement", help="个人额度单")
    p.add_argument("--member", help="默认自己")
    p.set_defaults(handler=_report_statement)

    # --- user（阶段 2.2）--------------------------------------------------
    user = top.add_parser("user", help="登录账号").add_subparsers(
        dest="action", required=True)

    p = user.add_parser("add", help="创建账号")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--member", required=True, help="关联社员：id / 学号 / 姓名")
    p.add_argument("--note")
    p.set_defaults(handler=_user_add)

    p = user.add_parser("list", help="账号列表")
    p.set_defaults(handler=_user_list)

    p = user.add_parser("passwd", help="重置口令（本人，或社长 / 副社长）")
    p.add_argument("--user", required=True, help="账号 id 或账号名")
    p.add_argument("--password", required=True)
    p.set_defaults(handler=_user_passwd)

    p = user.add_parser("disable", help="停用账号")
    p.add_argument("--user", required=True, help="账号 id 或账号名")
    p.set_defaults(handler=_user_disable)

    # --- 维护（阶段 2.4）--------------------------------------------------
    p = top.add_parser("doctor", help="体检：结构版本、完整性、外键与可疑数据")
    p.set_defaults(handler=_doctor, needs_services=False)

    p = top.add_parser("backup", help="数据库热备份（默认保留最近 10 份）")
    p.add_argument("--out", help="备份目录（默认 data/backups）")
    p.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="保留最近几份")
    p.add_argument("--list", action="store_true", help="只列出已有备份")
    p.set_defaults(handler=_backup, needs_services=False)

    # --- web（阶段 2.2）---------------------------------------------------
    p = top.add_parser("web", help="启动 Web 界面（浏览器里记打印、查额度）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true", help="开发模式（自动重载）")
    p.set_defaults(handler=_web, needs_services=False)

    return parser


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _date(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _operator(args, services):
    if not args.operator:
        raise ValueError("需要 --operator（操作人的 id / 学号 / 姓名）")
    member = services.member.find_by_token(args.operator)
    if member is None:
        raise ValueError(f"找不到操作人: {args.operator}")
    return member


def _member(args, services, token: str):
    member = services.member.find_by_token(token)
    if member is None:
        raise ValueError(f"找不到社员: {token}")
    return member


def _filament(args, services, operator, token: str) -> int:
    """耗材参数既可以是 id，也可以是名称。"""
    if token.isdigit():
        return int(token)
    for filament in services.filament.list_filaments(operator.id):
        if filament.name == token:
            return filament.id
    raise ValueError(f"找不到耗材: {token}")


# ---------------------------------------------------------------------------
# 处理函数
# ---------------------------------------------------------------------------

def _member_bootstrap(args, services) -> Result:
    member = services.member.bootstrap(args.name, qq=args.qq, student_id=args.student_id)
    return _table(f"已创建社长（id={member.id}）", [member])


def _member_add(args, services) -> Result:
    operator = _operator(args, services)
    member = services.member.create_member(
        operator.id, args.name, qq=args.qq, student_id=args.student_id,
        role=args.role, join_date=_date(args.join_date), note=args.note)
    return _table(f"已新增社员（id={member.id}）", [member])


def _member_list(args, services) -> Result:
    operator = _operator(args, services)
    members = services.member.list_members(operator.id, status=args.status, role=args.role)
    return _table("社员列表", members,
                  columns=["id", "name", "student_id", "role", "status", "qq", "join_date"])


def _member_left(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member)
    member = services.member.mark_left(operator.id, target.id)
    return _table(f"{member.name} 已退社（历史记录保留）", [member])


def _filament_add(args, services) -> Result:
    operator = _operator(args, services)
    filament = services.filament.create_filament(
        operator.id, args.name, material=args.material, color=args.color,
        unit_price=args.unit_price, note=args.note)
    return _table(f"已新增耗材（id={filament.id}）", [filament])


def _filament_list(args, services) -> Result:
    operator = _operator(args, services)
    return _table("耗材目录", services.filament.list_filaments(operator.id))


def _filament_purchase(args, services) -> Result:
    operator = _operator(args, services)
    filament_id = _filament(args, services, operator, args.filament)
    txn = services.filament.purchase(
        operator.id, filament_id, args.grams, args.cost,
        date=_date(args.date), note=args.note)
    return _table("已入库", [txn])


def _filament_stock(args, services) -> Result:
    operator = _operator(args, services)
    report = services.report.stock_report(operator.id)
    rows = [[str(f.id), f.name, f"{stock:g}"] for f, stock in report]
    payload = [{"filament_id": f.id, "name": f.name, "stock": stock}
               for f, stock in report]
    return Result("耗材库存", ["id", "名称", "库存(克)"], rows, payload)


def _quota_init(args, services) -> Result:
    operator = _operator(args, services)
    member_ids = ([_member(args, services, token).id for token in args.member]
                  if args.member else None)
    txns = services.quota.init_semester(
        operator.id, args.amount, member_ids=member_ids,
        date=_date(args.date), note=args.note, allow_repeat=args.allow_repeat)
    return _table(f"已给 {len(txns)} 人发放额度", txns)


def _quota_adjust(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member)
    txn = services.quota.adjust(operator.id, target.id, args.amount, args.note,
                                date=_date(args.date))
    return _table(f"已调整 {target.name} 的额度", [txn])


def _quota_balance(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member) if args.member else operator
    balance = services.report.balance_of(operator.id, target.id)
    return Result(f"{target.name} 剩余额度：{balance:g} 克", payload={
        "member_id": target.id, "name": target.name, "balance": balance})


def _record_print(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member)
    filament_id = _filament(args, services, operator, args.filament)
    record = services.record.record_print(
        operator.id, target.id, filament_id, args.grams,
        printer_name=args.printer, date=_date(args.date), comments=args.comments)
    return _table(f"已记录打印 #{record.id}", [record])


def _record_list(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member) if args.member else None
    records = services.record.list_records(
        operator.id, member_id=target.id if target else None,
        start=_date(args.start), end=_date(args.end))
    return _table("打印记录", records,
                  columns=["id", "member_id", "filament_name", "consumption",
                           "printer_name", "date", "operator_id", "comments"])


def _fund_income(args, services) -> Result:
    operator = _operator(args, services)
    txn = services.fund.income(operator.id, args.amount,
                               date=_date(args.date), note=args.note)
    return _table("已记收入", [txn])


def _fund_expense(args, services) -> Result:
    operator = _operator(args, services)
    txn = services.fund.expense(operator.id, args.amount,
                                date=_date(args.date), note=args.note)
    return _table("已记支出", [txn])


def _fund_list(args, services) -> Result:
    operator = _operator(args, services)
    report = services.report.fund_report(operator.id, start=_date(args.start),
                                         end=_date(args.end))
    txns = report["transactions"]
    payload = {"balance": report["balance"],
               "transactions": [asdict(t) for t in txns]}
    return _table(f"经费余额：{report['balance']:g} 元", txns, payload=payload)


def _contribution_add(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member)
    contribution = services.contribution.add(
        operator.id, target.id, args.amount, type=args.type,
        material_desc=args.material_desc, reward_quota=args.reward_quota,
        date=_date(args.date), note=args.note)
    return _table(
        f"已登记 {target.name} 的贡献（奖励额度 {contribution.reward_quota:g} 克）",
        [contribution])


def _report_quota(args, services) -> Result:
    operator = _operator(args, services)
    report = services.report.quota_report(operator.id)
    rows = [[str(m.id), m.name, m.student_id or "-", f"{balance:g}"]
            for m, balance in report]
    payload = [{"member_id": m.id, "name": m.name, "student_id": m.student_id,
                "balance": balance} for m, balance in report]
    return Result("全社额度表（在社社员）", ["id", "姓名", "学号", "剩余额度(克)"],
                  rows, payload)


def _report_statement(args, services) -> Result:
    operator = _operator(args, services)
    target = _member(args, services, args.member) if args.member else operator
    statement = services.report.member_statement(operator.id, target.id)

    quota_rows = [[_fmt(t.date), t.type, f"{t.amount:g}", t.note or "-"]
                  for t in statement["quota"]]
    record_rows = [" | ".join([str(r.id), r.filament_name,
                               f"{r.consumption:g}", _fmt(r.date)])
                   for r in statement["records"]]
    extra = ["", "打印记录（id | 耗材 | 克数 | 日期）"] + (record_rows or ["（无数据）"])
    payload = {
        "member": asdict(statement["member"]),
        "balance": statement["balance"],
        "records": [asdict(r) for r in statement["records"]],
        "quota": [asdict(t) for t in statement["quota"]],
        "contributions": [asdict(c) for c in statement["contributions"]],
    }
    return Result(
        f"{target.name}：剩余额度 {statement['balance']:g} 克"
        f"（共 {len(statement['records'])} 条打印记录）",
        ["日期", "类型", "额度变化(克)", "备注"], quota_rows, payload, extra)


# ---------------------------------------------------------------------------
# 登录账号 / Web（阶段 2.2）
# ---------------------------------------------------------------------------

@dataclass
class UserRow:
    """账号列表的输出行（把社员姓名与角色也带上，便于核对）。"""

    id: int
    username: str
    member_id: int
    member_name: str
    role: str
    status: str


def _user_row(services, user) -> UserRow:
    member = services.user.member_of(user)
    return UserRow(
        id=user.id,
        username=user.username,
        member_id=user.member_id,
        member_name=member.name if member else "?",
        role=member.role.value if member else "?",
        status=user.status,
    )


def _user_token(args, services):
    user = services.user.find_user(args.user)
    if user is None:
        raise ValueError(f"找不到账号: {args.user}")
    return user


def _user_add(args, services) -> Result:
    operator = _operator(args, services)
    member = _member(args, services, args.member)
    user = services.user.add_user(operator.id, args.username, args.password,
                                  member.id, note=args.note)
    return _table(f"已创建账号 {user.username}（关联社员 {member.name}）",
                  [_user_row(services, user)])


def _user_list(args, services) -> Result:
    operator = _operator(args, services)
    users = services.user.list_users(operator.id)
    return _table("登录账号", [_user_row(services, user) for user in users])


def _user_passwd(args, services) -> Result:
    operator = _operator(args, services)
    user = _user_token(args, services)
    updated = services.user.set_password(operator.id, user.id, args.password)
    return _table(f"已重置 {updated.username} 的口令",
                  [_user_row(services, updated)])


def _user_disable(args, services) -> Result:
    operator = _operator(args, services)
    user = _user_token(args, services)
    updated = services.user.disable(operator.id, user.id)
    return _table(f"已停用账号 {updated.username}",
                  [_user_row(services, updated)])


# ---------------------------------------------------------------------------
# 维护命令（阶段 2.4）：体检与备份
# ---------------------------------------------------------------------------

def _doctor(args, services) -> Result:
    """体检：结构版本、完整性、外键、可疑数据。有异常时退出码为 1。"""
    db_path = Path(args.db or DB_PATH)
    headers = ["检查项", "结果", "说明"]
    if not db_path.exists():
        return Result(f"数据库不存在：{db_path}", headers,
                      [["数据库文件", "异常", str(db_path)]],
                      {"ok": False, "database": str(db_path)}, exit_code=1)

    checks: list[list[str]] = []
    warnings: list[str] = []
    connection = sqlite3.connect(db_path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        checks.append(["结构版本", "OK" if version == SCHEMA_VERSION else "异常",
                       f"user_version={version}"
                       if version == SCHEMA_VERSION
                       else f"库={version}，程序需要={SCHEMA_VERSION}（开发阶段删库重建）"])

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        checks.append(["数据完整性", "OK" if integrity == "ok" else "异常", integrity])

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        checks.append(["外键一致性", "OK" if not violations else "异常",
                       f"{len(violations)} 条违规"])

        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("members", "filaments", "records",
                                "quota_transactions", "inventory_transactions",
                                "fund_transactions", "contributions", "users")}
        checks.append(["数据量", "OK",
                       "，".join(f"{name}={value}" for name, value in counts.items())])

        overdrafts = connection.execute(
            "SELECT m.name, COALESCE(SUM(q.amount), 0) AS balance FROM members m "
            "JOIN quota_transactions q ON q.member_id = m.id "
            "GROUP BY m.id HAVING balance < 0 ORDER BY balance").fetchall()
        if overdrafts:
            warnings.append("额度透支（规则允许，记得催缴）："
                            + "，".join(f"{name} {balance:g} 克" for name, balance in overdrafts))

        negative_stock = connection.execute(
            "SELECT f.name, COALESCE(SUM(i.amount), 0) AS stock FROM filaments f "
            "JOIN inventory_transactions i ON i.filament_id = f.id "
            "GROUP BY f.id HAVING stock < 0").fetchall()
        if negative_stock:
            warnings.append("库存为负（多半是采购没入账）："
                            + "，".join(f"{name} {stock:g} 克" for name, stock in negative_stock))

        if counts["members"] and counts["users"] == 0:
            warnings.append("有社员但没有任何登录账号，Web 界面登录不了，"
                            "请先 python main.py --operator <社长id> user add ...")

        duplicated = connection.execute(
            "SELECT m.name, COUNT(*) AS times FROM quota_transactions q "
            "JOIN members m ON m.id = q.member_id WHERE q.type = 'init' "
            "GROUP BY q.member_id HAVING times > 1").fetchall()
        if duplicated:
            warnings.append("重复发放过学期额度："
                            + "，".join(f"{name}（{times} 次）" for name, times in duplicated))
    finally:
        connection.close()

    failed = [row for row in checks if row[1] == "异常"]
    title = (f"体检完成：发现 {len(failed)} 项异常" if failed
             else "体检完成：数据库正常")
    extra = (["", "提示："] + [f"- {text}" for text in warnings]) if warnings else []
    payload = {"ok": not failed, "checks": checks, "warnings": warnings,
               "database": str(db_path)}
    return Result(title, headers, checks, payload, extra,
                  exit_code=1 if failed else 0)


def _backup(args, services) -> Result:
    """热备份数据库，或列出已有备份。"""
    db_path = Path(args.db or DB_PATH)
    out_dir = Path(args.out) if args.out else default_backup_dir(db_path)

    if args.list:
        files = list_backups(out_dir)
        rows = [[path.name, f"{path.stat().st_size / 1024:.1f} KB", str(path.parent)]
                for path in reversed(files)]
        payload = [{"path": str(path), "size": path.stat().st_size} for path in files]
        return Result(f"备份列表（{len(files)} 份）：{out_dir}",
                      ["文件", "大小", "目录"], rows, payload)

    backup = create_backup(db_path, out_dir, keep=args.keep)
    size = backup.stat().st_size
    return Result(f"已备份并校验通过：{backup}",
                  ["文件", "大小", "保留份数"],
                  [[backup.name, f"{size / 1024:.1f} KB", str(args.keep)]],
                  {"path": str(backup), "size": size, "keep": args.keep})


def _web(args, services) -> Result:
    """启动 Flask 应用（自带服务日志，Ctrl+C 停止）。"""
    from interfaces.app import create_app

    app = create_app(args.db or DB_PATH)
    print(f"Web 界面：http://{args.host}:{args.port}/   （Ctrl+C 停止）")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
    return Result("Web 服务已停止")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

# 业务错误一律变成一行提示 + 退出码 1，不给用户看 traceback
_HANDLED_ERRORS = (ValueError, PermissionError, RuntimeError, OSError, sqlite3.Error)


def _emit(args, result: Result | None) -> int:
    if result is None:
        return 0
    if args.json:
        print(json.dumps(result.payload, ensure_ascii=False, indent=2, default=_fmt))
    else:
        for line in _render(result):
            print(line)
    return result.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # web / backup / doctor 自己开连接（web 还要长期运行），不需要外层再装配一套服务
    if not getattr(args, "needs_services", True):
        try:
            return _emit(args, args.handler(args, None))
        except _HANDLED_ERRORS as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1

    db = Database(args.db or DB_PATH)
    try:
        services = build_services(db)
        try:
            result = args.handler(args, services)
        except _HANDLED_ERRORS as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
    finally:
        db.close()

    return _emit(args, result)


if __name__ == "__main__":
    raise SystemExit(main())
