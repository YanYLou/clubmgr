"""站内通知页面（阶段 3.2）：耗材快用完等提醒都落在这里。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import handles_errors, login_required, services

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    unread_only = bool(request.args.get("unread"))
    items = services().notification.list_for(g.member.id, unread_only=unread_only)
    return render_template("notifications.html", notifications=items,
                           unread_only=unread_only)


@bp.post("/<int:notification_id>/read")
@login_required
@handles_errors
def mark_read(notification_id: int):
    services().notification.mark_read(g.member.id, notification_id)
    flash("已标记为已读", "ok")
    return redirect(request.referrer or url_for("notifications.index"))


@bp.post("/read-all")
@login_required
@handles_errors
def mark_all_read():
    count = services().notification.mark_all_read(g.member.id)
    flash(f"已把 {count} 条通知标为已读", "ok")
    return redirect(url_for("notifications.index"))
