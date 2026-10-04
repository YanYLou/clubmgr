"""时间格排班页面（阶段 3.6）。

默认每周一 / 三 / 五各一格 **16:55–17:40**；运营1（以及社长 / 副社长 / 老师）可以改时间、
加格子、停用某一格、手工排人、一键填充。**谁都能看**这一周的格子与里面的人。
"""

from datetime import timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from domain.services import DEFAULT_SLOT_END, DEFAULT_SLOT_START
from interfaces.views.common import (can, handles_errors, login_required,
                                     parse_date, services)

bp = Blueprint("schedule", __name__, url_prefix="/schedule")


def _back(week=None):
    if week is None:
        return redirect(url_for("schedule.index"))
    return redirect(url_for("schedule.index", week=week.isoformat()))


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    view = services().schedule.week_view(g.member.id,
                                         parse_date(request.args.get("week")))
    week = view["week_start"]
    return render_template(
        "schedule.html",
        view=view,
        week=week,
        can_manage=can("schedule"),
        default_start=DEFAULT_SLOT_START,
        default_end=DEFAULT_SLOT_END,
        prev_week=(week - timedelta(days=7)).isoformat(),
        next_week=(week + timedelta(days=7)).isoformat(),
    )


@bp.post("/ensure")
@login_required
@handles_errors
def ensure():
    week = parse_date(request.form.get("week"))
    created = services().schedule.ensure_week(g.member.id, week)
    flash(f"已按默认规则补齐 {len(created)} 个时间格"
          f"（{DEFAULT_SLOT_START}–{DEFAULT_SLOT_END}）", "ok")
    return _back(created[0].week_start if created else week)


@bp.post("/add")
@login_required
@handles_errors
def add():
    slot = services().schedule.add_slot(
        g.member.id,
        slot_date=parse_date(request.form.get("slot_date")),
        start_time=request.form.get("start_time", ""),
        end_time=request.form.get("end_time", ""),
        capacity=request.form.get("capacity", type=int) or 0,
        note=request.form.get("note") or None)
    flash(f"已新增时间格：{slot.slot_date} {slot.start_time}–{slot.end_time}", "ok")
    return _back(slot.week_start)


@bp.post("/<int:slot_id>/update")
@login_required
@handles_errors
def update(slot_id: int):
    slot = services().schedule.update_slot(
        g.member.id, slot_id,
        slot_date=parse_date(request.form.get("slot_date")),
        start_time=request.form.get("start_time") or None,
        end_time=request.form.get("end_time") or None,
        capacity=request.form.get("capacity", type=int),
        note=request.form.get("note") or None)
    flash(f"已更新时间格：{slot.slot_date} {slot.start_time}–{slot.end_time}"
          f"（改日期会让原来的人变成待重排）", "ok")
    return _back(slot.week_start)


@bp.post("/<int:slot_id>/close")
@login_required
@handles_errors
def close(slot_id: int):
    slot = services().schedule.close_slot(g.member.id, slot_id,
                                          note=request.form.get("note") or None)
    flash(f"已停用 {slot.slot_date} {slot.start_time} 这一格"
          f"（原来的人已变成待重排并收到通知）", "ok")
    return _back(slot.week_start)


@bp.post("/<int:slot_id>/open")
@login_required
@handles_errors
def reopen(slot_id: int):
    slot = services().schedule.reopen_slot(g.member.id, slot_id,
                                           note=request.form.get("note") or None)
    flash(f"已启用 {slot.slot_date} {slot.start_time} 这一格", "ok")
    return _back(slot.week_start)


@bp.post("/assign")
@login_required
@handles_errors
def assign():
    reservation_id = request.form.get("reservation_id", type=int)
    slot_id = request.form.get("slot_id", type=int)
    if not reservation_id or not slot_id:
        raise ValueError("请选择预约与时间格")
    reservation = services().schedule.assign(g.member.id, reservation_id, slot_id)
    flash(f"已把预约 #{reservation.id} 排进时间格 #{slot_id}", "ok")
    return _back(reservation.week_start)


@bp.post("/<int:reservation_id>/unassign")
@login_required
@handles_errors
def unassign(reservation_id: int):
    reservation = services().schedule.unassign(g.member.id, reservation_id)
    flash(f"已把预约 #{reservation.id} 从时间格里拿出来", "ok")
    return _back(reservation.week_start)


@bp.post("/fill")
@login_required
@handles_errors
def fill():
    week = parse_date(request.form.get("week"))
    result = services().schedule.auto_fill(
        g.member.id, week, slot_date=parse_date(request.form.get("slot_date")))
    if result.get("reason"):
        flash(result["reason"], "error")
    else:
        skipped = len(result["skipped"])
        flash(f"一键填充完成：排进 {len(result['assigned'])} 条"
              + (f"，{skipped} 条没位置（容量不够）" if skipped else ""), "ok")
    return _back(result["week_start"])
