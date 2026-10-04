"""登录账号管理页面（阶段 2.2）：开户、重置口令、停用（manage_users）。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import handles_errors, login_required, services

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    return render_template(
        "users.html",
        users=services().user.list_users(g.member.id),
        members=services().member.list_members(g.member.id),
    )


@bp.post("/add")
@login_required
@handles_errors
def add():
    user = services().user.add_user(
        g.member.id,
        request.form.get("username", ""),
        request.form.get("password", ""),
        int(request.form.get("member_id") or 0),
        note=request.form.get("note") or None,
    )
    flash(f"已创建账号 {user.username}（关联社员 id={user.member_id}）", "ok")
    return redirect(url_for("users.index"))


@bp.post("/<int:user_id>/password")
@login_required
@handles_errors
def set_password(user_id: int):
    user = services().user.set_password(g.member.id, user_id,
                                        request.form.get("password", ""))
    flash(f"已重置 {user.username} 的口令", "ok")
    return redirect(url_for("users.index"))


@bp.post("/<int:user_id>/disable")
@login_required
@handles_errors
def disable(user_id: int):
    user = services().user.disable(g.member.id, user_id)
    flash(f"已停用账号 {user.username}", "ok")
    return redirect(url_for("users.index"))
