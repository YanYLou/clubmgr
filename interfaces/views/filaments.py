"""耗材与库存页面（阶段 2.2）。查看需 view_inventory，增改采购需 purchase。"""

from flask import (Blueprint, flash, g, redirect, render_template, request,
                   url_for)

from interfaces.views.common import (handles_errors, login_required, parse_date,
                                     services)

bp = Blueprint("filaments", __name__, url_prefix="/filaments")


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    return render_template(
        "filaments.html",
        filaments=services().filament.list_filaments(g.member.id),
        stock=services().report.stock_report(g.member.id),
    )


@bp.post("/add")
@login_required
@handles_errors
def add():
    price = request.form.get("unit_price") or None
    filament = services().filament.create_filament(
        g.member.id,
        request.form.get("name", ""),
        material=request.form.get("material") or None,
        color=request.form.get("color") or None,
        unit_price=float(price) if price else None,
        note=request.form.get("note") or None,
    )
    flash(f"已新增耗材 {filament.name}（id={filament.id}）", "ok")
    return redirect(url_for("filaments.index"))


@bp.post("/purchase")
@login_required
@handles_errors
def purchase():
    cost = request.form.get("cost") or 0
    txn = services().filament.purchase(
        g.member.id,
        int(request.form.get("filament_id") or 0),
        float(request.form.get("grams") or 0),
        float(cost),
        date=parse_date(request.form.get("date")),
        note=request.form.get("note") or None,
    )
    flash(f"已入库 {txn.amount:g} 克（filament_id={txn.filament_id}）", "ok")
    return redirect(url_for("filaments.index"))
