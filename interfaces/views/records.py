"""打印记录页面（阶段 2.2）。

记录打印时，"谁打印的"用 **学号 / 姓名 / id** 文本输入（运营2 没有看名册的权限，
用查找即可）；耗材用下拉框（运营2 有 view_inventory 权限）。
"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import (handles_errors, login_required, parse_date,
                                     services)

bp = Blueprint("records", __name__, url_prefix="/records")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    member_id = request.args.get("member_id", type=int)
    return render_template(
        "records.html",
        records=services().record.list_records(
            g.member.id, member_id=member_id,
            start=parse_date(request.args.get("start")),
            end=parse_date(request.args.get("end"))),
        member_id=member_id or "",
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
@handles_errors
def new():
    if request.method == "POST":
        member = services().member.find_by_token(request.form.get("member", ""))
        if member is None:
            raise ValueError("找不到社员：请填学号 / 姓名 / id")

        record = services().record.record_print(
            g.member.id,
            member.id,
            int(request.form.get("filament_id") or 0),
            float(request.form.get("grams") or 0),
            printer_name=request.form.get("printer", ""),
            date=parse_date(request.form.get("date")),
            comments=request.form.get("comments") or None,
        )
        flash(f"已记录打印 #{record.id}：{member.name} "
              f"{record.filament_name} {record.consumption:g} 克", "ok")
        return redirect(url_for("records.index"))

    return render_template(
        "record_new.html",
        filaments=services().filament.list_filaments(g.member.id),
    )
