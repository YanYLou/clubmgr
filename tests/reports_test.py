"""阶段 2.5：公示报表（Markdown / CSV）与维护页测试。"""

import csv

import pytest

from domain.models import Role
from interfaces.app import create_app
from interfaces.reports import collect, export, render_markdown


# ---------------------------------------------------------------------------
# 报表本身（直接用服务层，不经过 Web）
# ---------------------------------------------------------------------------

@pytest.fixture
def club_services(services, club):
    """给 club 添一点真实数据：采购入库、经费、贡献、一次打印。"""
    services.fund.income(club.president.id, 500, note="会费收入")
    services.filament.purchase(club.president.id, club.filament.id, 1000, 150,
                               note="采购 1kg")
    services.contribution.add(club.president.id, club.member.id, 100, type="money",
                             reward_quota=50, note="捐赠耗材费")
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 42.5,
                                 printer_name="P1")
    return services


def test_render_markdown_contains_all_sections(club_services, club):
    data = collect(club_services, club.president.id)
    text = render_markdown(data)

    assert "# 造梦 3D 打印社团 · 公示报表" in text
    for section in ("## 一、社员额度", "## 二、耗材库存", "## 三、经费流水", "## 四、贡献名单"):
        assert section in text
    assert "经费余额：350 元" in text                      # 500 收入 - 150 采购
    # 200 学期额度 + 50 贡献奖励 - 42.5 打印 = 207.5
    assert club.member.name in text and "207.5" in text
    assert "捐赠耗材费" in text


def test_export_writes_markdown_and_csv(club_services, club, tmp_path):
    out_dir = tmp_path / "reports"

    markdown, csvs = export(club_services, club.president.id, out_dir, write_csv=True)

    assert markdown.exists() and markdown.name == "report.md"
    assert {path.name for path in csvs} == {"quota.csv", "stock.csv",
                                            "fund.csv", "contributions.csv"}

    with (out_dir / "quota.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["社员", "学号", "剩余额度(克)"]
    assert any(row[0] == club.member.name for row in rows[1:])


def test_export_respects_permissions(services, club, tmp_path):
    with pytest.raises(PermissionError):
        export(services, club.member.id, tmp_path / "reports")     # 普通社员不能导公示


def test_period_label_in_markdown(club_services, club):
    from datetime import date

    data = collect(club_services, club.president.id,
                   start=date(2026, 9, 1), end=date(2026, 9, 30))
    text = render_markdown(data)

    assert "2026-09-01 ~ 2026-09-30" in text


# ---------------------------------------------------------------------------
# 维护页（Web）
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(tmp_path):
    app = create_app(str(tmp_path / "club.db"), secret_key="test-secret")
    services = app.config["SERVICES"]

    president = services.member.bootstrap("社长", student_id="10001")
    member = services.member.create_member(president.id, "张三", student_id="10005")
    filament = services.filament.create_filament(president.id, "PLA 白")
    services.quota.init_semester(president.id, 200)
    services.record.record_print(president.id, member.id, filament.id, 42.5)
    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "zhangsan", "zhang123", member.id)

    client = app.test_client()
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client, app


def test_admin_page_requires_permission(admin_client):
    client, app = admin_client

    response = client.get("/admin")
    assert response.status_code == 200
    assert "数据库文件" in response.data.decode("utf-8")

    # 普通社员进不去
    member_client = app.test_client()
    member_client.post("/login", data={"username": "zhangsan", "password": "zhang123"})
    response = member_client.get("/admin", follow_redirects=True)
    assert "没有权限" in response.data.decode("utf-8")


def test_admin_backup_creates_file(admin_client):
    from pathlib import Path

    client, app = admin_client

    response = client.post("/admin/backup", data={"keep": "5"}, follow_redirects=True)
    body = response.data.decode("utf-8")

    assert "已备份并校验通过" in body
    backups = list((Path(app.config["DB_PATH"]).parent / "backups").glob("club-*.db"))
    assert len(backups) == 1


def test_admin_report_download(admin_client):
    client, _ = admin_client

    response = client.get("/admin/report.md")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/markdown")
    body = response.data.decode("utf-8")
    assert "# 造梦 3D 打印社团 · 公示报表" in body
    assert "157.5" in body
