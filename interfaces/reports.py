"""公示报表：把额度 / 库存 / 经费 / 贡献整理成 Markdown 与 CSV（阶段 2.5 新增）。

CLI（``report export``）和 Web（``/admin`` 下载）共用这一份实现。
数据全部来自服务层，所以权限校验照旧生效；本模块只负责取数、排版与写文件。
"""

import csv
from datetime import date, datetime
from pathlib import Path

MARKDOWN_NAME = "report.md"


def collect(services, operator_id: int, *, start: date | None = None,
            end: date | None = None) -> dict:
    """取一次报表所需的全部数据（每一项都会做各自的权限校验）。"""
    return {
        "generated_at": datetime.now(),
        "period": (start, end),
        "quota": services.report.quota_report(operator_id),
        "stock": services.report.stock_report(operator_id),
        "fund": services.report.fund_report(operator_id, start=start, end=end),
        "contributions": services.report.contributions_report(
            operator_id, start=start, end=end),
        "members": services.member.list_members(operator_id, status="active"),
    }


def _period_text(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return "全部时间"
    return f"{start.isoformat()} ~ {end.isoformat()}"


def _number(value) -> str:
    return f"{float(value):g}"


def render_markdown(data: dict) -> str:
    """把 :func:`collect` 的结果渲染成可直接贴到群里的 Markdown。"""
    quota = data["quota"]
    stock = data["stock"]
    fund = data["fund"]
    contributions = data["contributions"]
    members = data["members"]

    lines = [
        "# 造梦 3D 打印社团 · 公示报表",
        "",
        f"- 生成时间：{data['generated_at']:%Y-%m-%d %H:%M}",
        f"- 统计区间：{_period_text(*data['period'])}",
        f"- 在社社员：{len(members)} 人",
        f"- 经费余额：{_number(fund['balance'])} 元",
        "",
        "## 一、社员额度",
        "",
        "| 社员 | 学号 | 剩余额度(克) |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {member.name} | {member.student_id or '-'} | {_number(balance)} |"
              for member, balance in quota] or ["| （无） | - | - |"]

    lines += ["", "## 二、耗材库存", "", "| 耗材 | 材质 | 库存(克) |", "| --- | --- | --- |"]
    lines += [f"| {filament.name} | {filament.material or '-'} | {_number(amount)} |"
              for filament, amount in stock] or ["| （无） | - | - |"]

    lines += ["", "## 三、经费流水", "",
              "| 日期 | 类型 | 金额(元) | 记录人 | 备注 |", "| --- | --- | --- | --- | --- |"]
    lines += [f"| {txn.date} | {txn.type} | {_number(txn.amount)} | {txn.operator_id} | "
              f"{txn.note or '-'} |"
              for txn in fund["transactions"]] or ["| （无） | - | - | - | - |"]

    lines += ["", "## 四、贡献名单", "",
              "| 日期 | 社员 | 类型 | 金额 | 实物 | 奖励额度(克) | 备注 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {item.date} | {item.member_id} | {item.type} | {_number(item.amount)} | "
              f"{item.material_desc or '-'} | {_number(item.reward_quota)} | {item.note or '-'} |"
              for item in contributions] or ["| （无） | - | - | - | - | - | - |"]

    lines += ["", "> 额度与库存为负数分别表示透支与采购未入账；"
                  "余额都由流水实时汇总得出。", ""]
    return "\n".join(lines)


def export(services, operator_id: int, out_dir: str | Path, *,
           start: date | None = None, end: date | None = None,
           write_csv: bool = False) -> tuple[Path, list[Path]]:
    """写出公示报表，返回 ``(Markdown 路径, 其它文件列表)``。"""
    data = collect(services, operator_id, start=start, end=end)
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    markdown_path = directory / MARKDOWN_NAME
    markdown_path.write_text(render_markdown(data), encoding="utf-8")

    written: list[Path] = []
    if write_csv:
        written = _write_csv(data, directory)
    return markdown_path, written


def _write_csv(data: dict, directory: Path) -> list[Path]:
    """额度 / 库存 / 经费 / 贡献各写一个 CSV（utf-8-sig，Excel 直接打开不乱码）。"""
    tables = {
        "quota.csv": (
            ["社员", "学号", "剩余额度(克)"],
            [[member.name, member.student_id or "", balance]
             for member, balance in data["quota"]],
        ),
        "stock.csv": (
            ["耗材", "材质", "库存(克)"],
            [[filament.name, filament.material or "", amount]
             for filament, amount in data["stock"]],
        ),
        "fund.csv": (
            ["日期", "类型", "金额(元)", "记录人", "备注"],
            [[txn.date, txn.type, txn.amount, txn.operator_id, txn.note or ""]
             for txn in data["fund"]["transactions"]],
        ),
        "contributions.csv": (
            ["日期", "社员id", "类型", "金额", "实物", "奖励额度(克)", "备注"],
            [[item.date, item.member_id, item.type, item.amount,
              item.material_desc or "", item.reward_quota, item.note or ""]
             for item in data["contributions"]],
        ),
    }

    written: list[Path] = []
    for name, (header, rows) in tables.items():
        path = directory / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        written.append(path)
    return written
