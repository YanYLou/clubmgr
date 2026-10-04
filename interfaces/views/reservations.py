"""预约页面（阶段 2.3）：排班表 + 我的预约 + 审核队列。

规则：谁都能提交（pending）；社长 / 副社长 / 运维审核通过后才进排班表（approved）。
"""

from datetime import timedelta

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from domain.services import ACTIVITY_DAYS, DAY_LABELS
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
    pending = (services().reservation.pending(g.member.id)
               if can("review_reservation") else [])
    names = services().member.names_for(
        [item.member_id for item in [*mine, *pending]])
    return render_template(
        "reservations.html",
        schedule=schedule,
        mine=mine,
        pending=pending,
        names=names,
        days=ACTIVITY_DAYS,
        day_labels=DAY_LABELS,
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
