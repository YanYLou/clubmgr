"""维护页面（阶段 2.5）：数据库备份与公示报表下载。

只有 ``manage_users``（社长 / 副社长）能进；备份文件落在 ``data/backups/``，
公示报表在内存里生成后直接下载，不落盘。
"""

import io
from datetime import date

from flask import (Blueprint, current_app, flash, g, redirect,
                   render_template, request, send_file, url_for)

from infrastructure.backup import (create_backup, default_backup_dir,
                                   list_backups)
from domain.services import SETTING_LOW_STOCK
from interfaces.reports import collect, render_markdown
from interfaces.views.common import handles_errors, login_required, services

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _db_path() -> str:
    return current_app.config["DB_PATH"]


@bp.get("")
@bp.get("/")
@login_required
@handles_errors
def index():
    services().user.list_users(g.member.id)          # 权限门槛：manage_users

    out_dir = default_backup_dir(_db_path())
    backups = [{"name": path.name, "size": f"{path.stat().st_size / 1024:.1f} KB",
                "path": str(path)} for path in reversed(list_backups(out_dir))]
    return render_template("admin.html", db_path=_db_path(),
                           backup_dir=str(out_dir), backups=backups,
                           threshold=services().settings.low_stock_threshold(),
                           low_stock=services().stock_alert.low_stock())


@bp.post("/low-stock")
@login_required
@handles_errors
def low_stock():
    """设置低库存阈值（阶段 3.2）：0 表示关闭告警。"""
    value = float(request.form.get("threshold") or 0)
    if value < 0:
        raise ValueError("阈值不能为负（0 表示关闭告警）")
    services().settings.set(g.member.id, SETTING_LOW_STOCK, value,
                            note="低库存阈值（克），0 = 关闭告警")
    flash(f"低库存阈值已设为 {value:g} 克", "ok")
    return redirect(url_for("admin.index"))


@bp.post("/backup")
@login_required
@handles_errors
def backup():
    keep = request.form.get("keep", type=int) or 10
    path = create_backup(_db_path(), keep=keep)
    flash(f"已备份并校验通过：{path}", "ok")
    return redirect(url_for("admin.index"))


@bp.get("/report.md")
@login_required
@handles_errors
def report_markdown():
    """下载公示报表（Markdown）。"""
    content = render_markdown(collect(services(), g.member.id)).encode("utf-8")
    return send_file(
        io.BytesIO(content),
        mimetype="text/markdown",
        as_attachment=True,
        download_name=f"club-report-{date.today().isoformat()}.md",
    )
