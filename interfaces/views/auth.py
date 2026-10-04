"""登录 / 登出（阶段 2.2）。

会话里只放 ``user_id``；口令校验在 :meth:`domain.services.UserService.authenticate`。
"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)

from interfaces.views.common import services

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str:
    """只允许站内跳转，避免被 open redirect 利用。"""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("member") is not None:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        user = services().user.authenticate(
            request.form.get("username", ""), request.form.get("password", ""))
        if user is None:
            flash("账号或口令不正确（账号被停用也会登录失败）", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            member = services().user.member_of(user)
            flash(f"欢迎回来，{member.name}", "ok")
            return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    flash("已退出登录", "ok")
    return redirect(url_for("auth.login"))
