"""阶段 2.2：Web 界面测试（登录、权限、记打印闭环）。

用 Flask 测试客户端 + 内存库；``app.config["SERVICES"]`` 与测试共享同一套服务层。
"""

import pytest

from domain.models import Role
from interfaces.app import create_app


def _text(response) -> str:
    return response.data.decode("utf-8")


@pytest.fixture
def app():
    application = create_app(":memory:", secret_key="test-secret")
    services = application.config["SERVICES"]

    president = services.member.bootstrap("社长", student_id="10001")
    op2 = services.member.create_member(president.id, "运营2",
                                        role=Role.OP2, student_id="10002")
    member = services.member.create_member(president.id, "张三", student_id="10005")
    filament = services.filament.create_filament(president.id, "PLA 白",
                                                 material="PLA", unit_price=0.1)
    services.quota.init_semester(president.id, 200)

    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "op2user", "op2pass123", op2.id)
    services.user.add_user(president.id, "zhangsan", "zhang123", member.id)

    application.config["IDS"] = {
        "president": president.id, "op2": op2.id,
        "member": member.id, "filament": filament.id,
    }
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username="admin", password="admin123"):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=True)


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def test_login_is_required(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_rejects_wrong_password(client):
    response = login(client, "admin", "wrong-password")
    assert "账号或口令不正确" in _text(response)


def test_login_and_dashboard(client):
    response = login(client, "zhangsan", "zhang123")
    body = _text(response)

    assert "张三 的额度" in body
    assert "200" in body
    assert "退出" in body


def test_logout_clears_session(client):
    login(client, "admin")
    client.post("/logout", follow_redirects=True)

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


# ---------------------------------------------------------------------------
# 记打印闭环
# ---------------------------------------------------------------------------

def test_record_print_through_web_form(client, app):
    ids = app.config["IDS"]
    login(client, "op2user", "op2pass123")

    response = client.post("/records/new", data={
        "member": "10005",
        "filament_id": str(ids["filament"]),
        "grams": "42.5",
        "printer": "P1",
    }, follow_redirects=True)
    body = _text(response)

    assert "已记录打印" in body
    assert "42.5" in body

    # 张三的额度变成 157.5，库存变成 -42.5
    services = app.config["SERVICES"]
    assert services.report.balance_of(ids["president"], ids["member"]) == pytest.approx(157.5)
    assert services.report.stock_of(ids["president"], ids["filament"]) == pytest.approx(-42.5)


def test_ordinary_member_cannot_record_print(client, app):
    ids = app.config["IDS"]
    login(client, "zhangsan", "zhang123")

    response = client.post("/records/new", data={
        "member": "10005",
        "filament_id": str(ids["filament"]),
        "grams": "5",
    }, follow_redirects=True)

    assert "没有权限" in _text(response)
    assert app.config["SERVICES"].record.list_records(ids["president"]) == []


def test_overdraft_needs_full_role(client, app):
    ids = app.config["IDS"]

    # 运营2 记 250 克（额度只有 200）→ 被拦
    login(client, "op2user", "op2pass123")
    response = client.post("/records/new", data={
        "member": "10005",
        "filament_id": str(ids["filament"]),
        "grams": "250",
    }, follow_redirects=True)
    assert "额度不足" in _text(response)
    client.post("/logout")

    # 社长可以记透支
    login(client, "admin")
    response = client.post("/records/new", data={
        "member": "10005",
        "filament_id": str(ids["filament"]),
        "grams": "250",
    }, follow_redirects=True)
    assert "已记录打印" in _text(response)
    assert app.config["SERVICES"].report.balance_of(
        ids["president"], ids["member"]) == pytest.approx(-50)


# ---------------------------------------------------------------------------
# 权限与页面
# ---------------------------------------------------------------------------

def test_member_list_page_respects_permissions(client, app):
    ids = app.config["IDS"]

    login(client, "admin")
    assert "张三" in _text(client.get("/members"))
    client.post("/logout")

    login(client, "op2user", "op2pass123")
    response = client.get("/members", follow_redirects=True)
    assert "没有权限" in _text(response)
    client.post("/logout")

    login(client, "zhangsan", "zhang123")
    response = client.get("/quota", follow_redirects=True)
    assert "没有权限" in _text(response)


def test_member_can_see_own_statement_only(client, app):
    ids = app.config["IDS"]
    login(client, "zhangsan", "zhang123")

    body = _text(client.get("/me"))
    assert "张三 的额度单" in body

    # 别人的额度单：URL 上没有入口，服务层也不允许
    with pytest.raises(PermissionError):
        app.config["SERVICES"].report.member_statement(ids["member"], ids["op2"])


def test_users_page_creates_and_disables_account(client, app):
    login(client, "admin")

    response = client.post("/users/add", data={
        "username": "newbie", "password": "newbie123",
        "member_id": str(app.config["IDS"]["member"]),
    }, follow_redirects=True)
    assert "已创建账号 newbie" in _text(response)

    services = app.config["SERVICES"]
    user = services.user.find_user("newbie")
    assert services.user.authenticate("newbie", "newbie123") is not None

    response = client.post(f"/users/{user.id}/disable", follow_redirects=True)
    assert "已停用账号 newbie" in _text(response)
    assert services.user.authenticate("newbie", "newbie123") is None


def test_filament_purchase_page(client, app):
    ids = app.config["IDS"]
    login(client, "admin")

    response = client.post("/filaments/purchase", data={
        "filament_id": str(ids["filament"]),
        "grams": "1000",
        "cost": "150",
        "note": "采购 1kg",
    }, follow_redirects=True)
    assert "已入库" in _text(response)

    services = app.config["SERVICES"]
    assert services.report.stock_of(ids["president"], ids["filament"]) == pytest.approx(1000)
    assert services.report.fund_balance(ids["president"]) == pytest.approx(-150)
