"""登录 / 登出 / 自助注册（阶段 2.2，注册在阶段 3.5 加入）。

会话里只放 ``user_id``；口令校验在 :meth:`domain.services.UserService.authenticate`。
自助注册走"填资料 → 待人事审核"，审核通过前不能登录。
"""

import time

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   session, url_for)

from interfaces.views.common import services

bp = Blueprint("auth", __name__)

SIGNUP_LIMIT = 10           # 同一 IP 每分钟最多提交几次注册（防止刷注册）
_signup_attempts: dict[str, list[float]] = {}


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    recent = [stamp for stamp in _signup_attempts.get(ip, []) if now - stamp < 60]
    if len(recent) >= SIGNUP_LIMIT:
        _signup_attempts[ip] = recent
        return True
    recent.append(now)
    _signup_attempts[ip] = recent
    return False


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
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = services().user.authenticate(username, password)
        if user is None:
            problem = services().user.login_problem(username, password)
            flash(problem or "账号或口令不正确（账号被停用也会登录失败）", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            member = services().user.member_of(user)
            flash(f"欢迎回来，{member.name}", "ok")
            return redirect(_safe_next(request.args.get("next")))
    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    """社员自助注册：填资料 → 生成待审核的社员与账号 → 人事审核通过后才能登录。"""
    if g.get("member") is not None:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if _rate_limited(request.remote_addr or "?"):
            flash("注册提交太频繁了，请过一分钟再试", "error")
            return render_template("signup.html", form=request.form), 429
        try:
            member, user = services().user.signup(
                name=request.form.get("name", ""),
                student_id=request.form.get("student_id", ""),
                username=request.form.get("username", ""),
                password=request.form.get("password", ""),
                qq=request.form.get("qq") or None,
                note=request.form.get("note") or None,
            )
        except ValueError as error:
            flash(str(error), "error")
            return render_template("signup.html", form=request.form)

        flash(f"注册已提交：{member.name}（账号 {user.username}）；"
              f"等人事审核通过后就能登录", "ok")
        return redirect(url_for("auth.login"))

    return render_template("signup.html", form={})


@bp.post("/logout")
def logout():
    session.clear()
    flash("已退出登录", "ok")
    return redirect(url_for("auth.login"))
