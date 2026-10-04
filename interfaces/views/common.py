"""视图公共部分（阶段 2.2）：当前登录人、权限、错误处理、参数解析。"""

from datetime import date
from functools import wraps

from flask import current_app, flash, g, redirect, request, session, url_for

from domain.permissions import can as _can


def services():
    """装配好的服务层（由 create_app 放进 config）。"""
    return current_app.config["SERVICES"]


def can(action: str) -> bool:
    """模板里用它隐藏没权限的入口；真正的校验始终在服务层。"""
    member = g.get("member")
    return member is not None and _can(member.role, action)


def parse_date(text: str | None) -> date | None:
    """``YYYY-MM-DD`` → date；空串按 None 处理（交给服务层用今天）。"""
    text = (text or "").strip()
    return date.fromisoformat(text) if text else None


def load_session_identity() -> None:
    """每个请求开头恢复当前账号与社员；角色 / 状态改了立刻生效。"""
    g.user = None
    g.member = None
    user_id = session.get("user_id")
    if user_id is None:
        return

    user = services().user.get_user(user_id)
    member = None
    if user is not None and user.status == "active":
        member = services().user.member_of(user)
    if user is None or member is None:
        session.clear()
        return
    g.user, g.member = user, member


def login_required(view):
    """没登录就跳登录页，登录后回到原地址。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("member") is None:
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def handles_errors(view):
    """把服务层的业务错误变成 flash 提示，避免 500 页面。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except PermissionError as exc:
            flash(f"没有权限：{exc}", "error")
            return redirect(url_for("dashboard.index"))
        except (ValueError, RuntimeError) as exc:
            flash(f"操作失败：{exc}", "error")
            return redirect(request.referrer or url_for("dashboard.index"))

    return wrapped
