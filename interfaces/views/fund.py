"""经费页面（阶段 2.2）：余额与流水、收支记账、贡献登记（manage_funds）。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import (handles_errors, login_required, parse_date,
                                     services)

bp = Blueprint("fund", __name__, url_prefix="/fund")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    return render_template(
        "fund.html",
        report=services().report.fund_report(
            g.member.id,
            start=parse_date(request.args.get("start")),
            end=parse_date(request.args.get("end"))),
    )


@bp.post("/income")
@login_required
@handles_errors
def income():
    txn = services().fund.income(
        g.member.id,
        float(request.form.get("amount") or 0),
        date=parse_date(request.form.get("date")),
        note=request.form.get("note", ""),
    )
    flash(f"已记收入 {txn.amount:g} 元", "ok")
    return redirect(url_for("fund.index"))


@bp.post("/expense")
@login_required
@handles_errors
def expense():
    txn = services().fund.expense(
        g.member.id,
        float(request.form.get("amount") or 0),
        date=parse_date(request.form.get("date")),
        note=request.form.get("note", ""),
    )
    flash(f"已记支出 {-txn.amount:g} 元", "ok")
    return redirect(url_for("fund.index"))


@bp.post("/contribution")
@login_required
@handles_errors
def contribution():
    member = services().member.find_by_token(request.form.get("member", ""))
    if member is None:
        raise ValueError("找不到社员：请填学号 / 姓名 / id")

    reward = request.form.get("reward_quota") or 0
    record = services().contribution.add(
        g.member.id, member.id,
        float(request.form.get("amount") or 0),
        type=request.form.get("type") or "money",
        material_desc=request.form.get("material_desc") or None,
        reward_quota=float(reward),
        date=parse_date(request.form.get("date")),
        note=request.form.get("note") or None,
    )
    flash(f"已登记 {member.name} 的贡献，奖励额度 {record.reward_quota:g} 克", "ok")
    return redirect(url_for("fund.index"))
