"""登录账号管理页面（阶段 2.2）：开户、重置口令、停用（manage_users）。

阶段 3.5 起这里还负责审核自助注册（``approve_signup``：人事 + 社长 / 副社长 / 老师）。
"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import (can, handles_errors, login_required,
                                     services)

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    manage = can("manage_users")            # 账号管理（社长 / 副社长1号 / 老师）
    review = can("approve_signup")          # 注册审核（再加上人事）
    signups = services().user.pending_signups(g.member.id) if review else []
    return render_template(
        "users.html",
        manage=manage,
        users=services().user.list_users(g.member.id) if manage else [],
        members=services().member.list_members(g.member.id) if manage else [],
        signups=signups,
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


# -- 自助注册审核（阶段 3.5）-------------------------------------------------

@bp.post("/signups/<int:user_id>/approve")
@login_required
@handles_errors
def approve_signup(user_id: int):
    user, member = services().user.approve_signup(g.member.id, user_id)
    flash(f"已通过 {member.name}（{user.username}）的注册，现在可以登录了", "ok")
    return redirect(url_for("users.index"))


@bp.post("/signups/<int:user_id>/reject")
@login_required
@handles_errors
def reject_signup(user_id: int):
    user, member = services().user.reject_signup(
        g.member.id, user_id, note=request.form.get("note") or None)
    flash(f"已驳回 {member.name}（{user.username}）的注册", "ok")
    return redirect(url_for("users.index"))
