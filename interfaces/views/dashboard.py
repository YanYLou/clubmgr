"""首页（自己的额度 + 社长视角的全社概览）与个人额度单。"""

from flask import Blueprint, g, render_template

from interfaces.views.common import can, handles_errors, login_required, services

bp = Blueprint("dashboard", __name__)


@bp.get("/")
@login_required
@handles_errors
def index():
    report = services().report
    statement = report.member_statement(g.member.id, g.member.id)

    club = None
    if can("view_all"):
        club = {
            "members": services().member.list_members(g.member.id, status="active"),
            "quota": report.quota_report(g.member.id),
            "stock": report.stock_report(g.member.id),
        }
        if can("view_funds"):
            club["fund_balance"] = report.fund_balance(g.member.id)
    return render_template("dashboard.html", statement=statement, club=club,
                           printers=services().printer.summary(g.member.id))


@bp.get("/me")
@login_required
@handles_errors
def statement():
    data = services().report.member_statement(g.member.id, g.member.id)
    return render_template("statement.html", statement=data)
