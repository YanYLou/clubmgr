"""打印机页面（阶段 3.3）：空闲 / 使用中 / 维修中，以及还有几台可用。

谁都能看；标记使用中/释放需要 ``manage_printers``（老师、运营、社长副社长），
标记维修/修好与增删机器需要 ``repair_printers``（社长 / 副社长 / 老师）。
"""

from datetime import datetime

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import handles_errors, login_required, services

bp = Blueprint("printers", __name__, url_prefix="/printers")


def _datetime(text: str | None) -> datetime | None:
    """``2026-10-04 17:40`` 或 ``2026-10-04T17:40`` → datetime；空串按 None。"""
    text = (text or "").strip()
    return datetime.fromisoformat(text) if text else None


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    return render_template("printers.html", summary=services().printer.summary(g.member.id))


@bp.post("/add")
@login_required
@handles_errors
def add():
    printer = services().printer.add_printer(
        g.member.id,
        request.form.get("name", ""),
        model=request.form.get("model") or None,
        note=request.form.get("note") or None,
    )
    flash(f"已新增打印机 {printer.name}（id={printer.id}）", "ok")
    return redirect(url_for("printers.index"))


@bp.post("/<int:printer_id>/use")
@login_required
@handles_errors
def use(printer_id: int):
    token = (request.form.get("member") or "").strip()
    member_id = None
    if token:
        target = services().member.find_by_token(token)
        if target is None:
            raise ValueError("找不到使用人：请填学号 / 姓名 / id")
        member_id = target.id

    printer = services().printer.mark_in_use(
        g.member.id, printer_id, member_id=member_id,
        expected_end=_datetime(request.form.get("expected_end")),
        note=request.form.get("note") or None)
    flash(f"{printer.name} 已标记为使用中", "ok")
    return redirect(url_for("printers.index"))


@bp.post("/<int:printer_id>/release")
@login_required
@handles_errors
def release(printer_id: int):
    printer = services().printer.release(g.member.id, printer_id,
                                         note=request.form.get("note") or None)
    flash(f"{printer.name} 已释放（空闲）", "ok")
    return redirect(url_for("printers.index"))


@bp.post("/<int:printer_id>/maintenance")
@login_required
@handles_errors
def maintenance(printer_id: int):
    printer = services().printer.mark_maintenance(
        g.member.id, printer_id, note=request.form.get("note", ""))
    flash(f"{printer.name} 已标记为维修中：{printer.note}", "ok")
    return redirect(url_for("printers.index"))


@bp.post("/<int:printer_id>/fixed")
@login_required
@handles_errors
def fixed(printer_id: int):
    printer = services().printer.finish_maintenance(
        g.member.id, printer_id, note=request.form.get("note") or None)
    flash(f"{printer.name} 已修好，恢复空闲", "ok")
    return redirect(url_for("printers.index"))
