"""社员管理页面（阶段 2.2）。名册与增改需要 view_members / edit_members 权限。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from domain.models import Role
from interfaces.views.common import (handles_errors, login_required, parse_date,
                                     services)

bp = Blueprint("members", __name__, url_prefix="/members")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    status = request.args.get("status") or None
    return render_template(
        "members.html",
        members=services().member.list_members(g.member.id, status=status),
        status=status or "",
        roles=[role.value for role in Role],
    )


@bp.post("/add")
@login_required
@handles_errors
def add():
    member = services().member.create_member(
        g.member.id,
        request.form.get("name", ""),
        student_id=request.form.get("student_id") or None,
        qq=request.form.get("qq") or None,
        role=request.form.get("role") or Role.MEMBER.value,
        join_date=parse_date(request.form.get("join_date")),
        note=request.form.get("note") or None,
    )
    flash(f"已新增社员 {member.name}（id={member.id}）", "ok")
    return redirect(url_for("members.index"))


@bp.post("/<int:member_id>/left")
@login_required
@handles_errors
def mark_left(member_id: int):
    member = services().member.mark_left(g.member.id, member_id)
    flash(f"{member.name} 已退社（历史记录保留）", "ok")
    return redirect(url_for("members.index"))


@bp.post("/<int:member_id>/role")
@login_required
@handles_errors
def change_role(member_id: int):
    member = services().member.update_member(
        g.member.id, member_id, role=request.form.get("role", ""))
    flash(f"{member.name} 的角色已改为 {member.role.value}", "ok")
    return redirect(url_for("members.index"))
