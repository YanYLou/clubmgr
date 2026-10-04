"""预约页面（阶段 2.3）：排班表 + 我的预约 + 审核队列。

规则：谁都能提交（pending）；社长 / 副社长 / 运维审核通过后才进排班表（approved）。
"""

from datetime import timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from domain.services import (ACTIVITY_DAYS, DAY_LABELS,
                             RESERVATION_STATUS_LABELS)
from interfaces.views.common import (can, handles_errors, login_required,
                                     parse_date, services)

bp = Blueprint("reservations", __name__, url_prefix="/reservations")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    schedule = services().reservation.schedule(
        g.member.id, week_start=parse_date(request.args.get("week")))
    week = schedule["week_start"]
    mine = services().reservation.mine(g.member.id)
    reviewer = can("review_reservation")
    pending = services().reservation.pending(g.member.id) if reviewer else []
    reschedule = services().reservation.reschedule_list(g.member.id) if reviewer else []
    approved = [item for _, items in schedule["days"] for item in items]
    names = services().member.names_for(
        [item.member_id for item in [*mine, *pending, *reschedule, *approved]])
    return render_template(
        "reservations.html",
        schedule=schedule,
        mine=mine,
        pending=pending,
        approved=approved,
        reschedule=reschedule,
        names=names,
        days=ACTIVITY_DAYS,
        day_labels=DAY_LABELS,
        status_labels=RESERVATION_STATUS_LABELS,
        urgent_allowed=can("urgent_reservation"),
        prev_week=(week - timedelta(days=7)).isoformat(),
        next_week=(week + timedelta(days=7)).isoformat(),
    )


@bp.post("/add")
@login_required
@handles_errors
def add():
    token = (request.form.get("member") or "").strip()
    member_id = None
    if token:
        target = services().member.find_by_token(token)
        if target is None:
            raise ValueError("找不到社员：请填学号 / 姓名 / id")
        member_id = target.id

    reservation = services().reservation.create(
        g.member.id,
        activity_day=request.form.get("activity_day", ""),
        week_start=parse_date(request.form.get("week")),
        member_id=member_id,
        note=request.form.get("note") or None,
    )
    flash(f"已提交预约 #{reservation.id}（{reservation.week_start} "
          f"{DAY_LABELS.get(reservation.activity_day, reservation.activity_day)}），等审核通过",
          "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))


@bp.post("/<int:reservation_id>/approve")
@login_required
@handles_errors
def approve(reservation_id: int):
    order = request.form.get("order", type=int)
    reservation = services().reservation.review(
        g.member.id, reservation_id, approve=True, order_no=order)
    flash(f"已通过预约 #{reservation.id}，排班序号 {reservation.order_no}", "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))


@bp.post("/<int:reservation_id>/reject")
@login_required
@handles_errors
def reject(reservation_id: int):
    reservation = services().reservation.reject(
        g.member.id, reservation_id, note=request.form.get("note") or None)
    flash(f"已驳回预约 #{reservation.id}", "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))


@bp.post("/<int:reservation_id>/cancel")
@login_required
@handles_errors
def cancel(reservation_id: int):
    reservation = services().reservation.cancel(
        g.member.id, reservation_id, note=request.form.get("note") or None)
    flash(f"已撤销预约 #{reservation.id}", "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))


# -- 紧急任务（阶段 3.4）-----------------------------------------------------

@bp.post("/<int:reservation_id>/urgent")
@login_required
@handles_errors
def urgent(reservation_id: int):
    """把某条预约提到本周（或指定周）并插到最前面。"""
    reservation = services().reservation.pull_to_this_week(
        g.member.id, reservation_id,
        week_start=parse_date(request.form.get("week")),
        activity_day=request.form.get("day") or None,
        note=request.form.get("note", ""),
        order_no=request.form.get("order", type=int))
    flash(f"已紧急提前 #{reservation.id} → {reservation.week_start} "
          f"{DAY_LABELS.get(reservation.activity_day, reservation.activity_day)} "
          f"序号 {reservation.order_no}（被顺延的人已收到通知）", "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))


@bp.post("/<int:reservation_id>/bump")
@login_required
@handles_errors
def bump(reservation_id: int):
    """挤掉某条已通过的排班：退回待重排并通知本人。"""
    reservation = services().reservation.bump(
        g.member.id, reservation_id, note=request.form.get("note", ""))
    flash(f"已挤掉排班 #{reservation.id}，本人已收到通知（状态＝待重排）", "ok")
    return redirect(url_for("reservations.index",
                            week=reservation.week_start.isoformat()))
