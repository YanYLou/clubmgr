"""额度页面（阶段 2.2）：全社额度表 + 学期初发放 + 手工调整。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import (handles_errors, login_required, parse_date,
                                     services)

bp = Blueprint("quota", __name__, url_prefix="/quota")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    return render_template("quota.html",
                           quota=services().report.quota_report(g.member.id))


@bp.post("/init")
@login_required
@handles_errors
def init():
    transactions = services().quota.init_semester(
        g.member.id,
        float(request.form.get("amount") or 0),
        date=parse_date(request.form.get("date")),
        note=request.form.get("note") or None,
        allow_repeat=bool(request.form.get("allow_repeat")),
    )
    flash(f"已给 {len(transactions)} 人发放额度", "ok")
    return redirect(url_for("quota.index"))


@bp.post("/adjust")
@login_required
@handles_errors
def adjust():
    member = services().member.find_by_token(request.form.get("member", ""))
    if member is None:
        raise ValueError("找不到社员：请填学号 / 姓名 / id")

    txn = services().quota.adjust(
        g.member.id, member.id,
        float(request.form.get("amount") or 0),
        request.form.get("note", ""),
        date=parse_date(request.form.get("date")),
    )
    flash(f"已调整 {member.name} 的额度：{txn.amount:+g} 克", "ok")
    return redirect(url_for("quota.index"))
