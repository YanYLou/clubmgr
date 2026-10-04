"""阶段 3.5：社员自助注册（填资料 → 待人事审核 → 通过后才能登录）。"""

import pytest

from domain.models import Role


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

def test_signup_creates_pending_member_and_user(services, club):
    member, user = services.user.signup(
        name="李四", student_id="10008", username="lisi", password="lisi123456",
        qq="123456", note="高一 3 班")

    assert member.status == "pending"
    assert member.role is Role.MEMBER
    assert member.name == "李四" and member.student_id == "10008"
    assert user.status == "pending"
    assert user.member_id == member.id
    assert "等待人事审核" in user.note
    # 口令是哈希存储
    assert "lisi123456" not in user.password_hash


def test_pending_signup_cannot_login(services, club):
    services.user.signup(name="李四", student_id="10008", username="lisi",
                         password="lisi123456")

    assert services.user.authenticate("lisi", "lisi123456") is None
    assert services.user.login_problem("lisi", "lisi123456") == \
        "账号还在等待人事审核，通过后就能登录"
    assert services.user.login_problem("lisi", "wrong-password") is None


def test_signup_validations(services, club):
    with pytest.raises(ValueError):
        services.user.signup(name="  ", student_id="10008", username="lisi",
                             password="lisi123456")
    with pytest.raises(ValueError):
        services.user.signup(name="李四", student_id=" ", username="lisi",
                             password="lisi123456")
    with pytest.raises(ValueError):
        services.user.signup(name="李四", student_id="10008", username="li",
                             password="lisi123456")
    with pytest.raises(ValueError):
        services.user.signup(name="李四", student_id="10008", username="lisi",
                             password="123")

    # 学号已经在名册里
    with pytest.raises(ValueError) as excinfo:
        services.user.signup(name="李四", student_id=club.member.student_id,
                             username="lisi", password="lisi123456")
    assert "已经在名册里" in str(excinfo.value)

    # 账号名重复
    services.user.signup(name="李四", student_id="10008", username="lisi",
                         password="lisi123456")
    with pytest.raises(ValueError) as excinfo:
        services.user.signup(name="王五", student_id="10009", username="lisi",
                             password="lisi123456")
    assert "账号已存在" in str(excinfo.value)


def test_signup_does_not_hide_existing_member(services, club):
    """注册失败不应该留下半条数据。"""
    before = len(services.member.list_members(club.president.id))

    with pytest.raises(ValueError):
        services.user.signup(name="李四", student_id=club.member.student_id,
                             username="lisi", password="lisi123456")

    assert len(services.member.list_members(club.president.id)) == before


# ---------------------------------------------------------------------------
# 审核
# ---------------------------------------------------------------------------

def test_approve_signup_activates_member_and_user(services, club):
    member, user = services.user.signup(name="李四", student_id="10008",
                                        username="lisi", password="lisi123456")

    assert [u.username for u, _ in services.user.pending_signups(club.hr.id)] == ["lisi"]

    approved_user, approved_member = services.user.approve_signup(club.hr.id, user.id)

    assert approved_user.status == "active"
    assert approved_member.status == "active"
    assert services.user.pending_signups(club.hr.id) == []

    logged_in = services.user.authenticate("lisi", "lisi123456")
    assert logged_in is not None and logged_in.id == user.id

    # 通过后就是正常社员：能看自己的额度
    assert services.report.member_statement(
        user.member_id, user.member_id)["member"].id == member.id


def test_reject_signup_keeps_record_but_blocks_login(services, club):
    member, user = services.user.signup(name="李四", student_id="10008",
                                        username="lisi", password="lisi123456")

    rejected_user, rejected_member = services.user.reject_signup(
        club.hr.id, user.id, note="不是本校学生")

    assert rejected_user.status == "rejected"
    assert rejected_member.status == "rejected"
    assert "不是本校学生" in rejected_user.note
    assert services.user.authenticate("lisi", "lisi123456") is None
    assert services.user.login_problem("lisi", "lisi123456") == \
        "这次注册被驳回了，请联系人事"
    # 记录还在，方便回查
    assert services.member.get_member(club.hr.id, member.id).status == "rejected"
    assert services.user.pending_signups(club.hr.id) == []


def test_signup_review_permission(services, club):
    _, user = services.user.signup(name="李四", student_id="10008",
                                   username="lisi", password="lisi123456")

    for person in (club.op2, club.member):
        with pytest.raises(PermissionError):
            services.user.pending_signups(person.id)
        with pytest.raises(PermissionError):
            services.user.approve_signup(person.id, user.id)

    # 人事（审核人）/ 社长 / 副社长1号 都可以
    for person in (club.hr, club.president):
        assert services.user.pending_signups(person.id) is not None


def test_approve_only_pending_signups(services, club):
    _, user = services.user.signup(name="李四", student_id="10008",
                                   username="lisi", password="lisi123456")
    services.user.approve_signup(club.hr.id, user.id)

    with pytest.raises(ValueError) as excinfo:
        services.user.approve_signup(club.hr.id, user.id)
    assert "不是待审核状态" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Web 页面
# ---------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path):
    from interfaces.app import create_app

    app = create_app(str(tmp_path / "club.db"), secret_key="test-secret")
    services = app.config["SERVICES"]

    president = services.member.bootstrap("社长", student_id="10001")
    services.member.create_member(president.id, "人事", role=Role.HR, student_id="10010")
    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "hruser", "hrpass123",
                           services.member.find_by_token("10010").id)
    return app


def _text(response) -> str:
    return response.data.decode("utf-8")


def test_web_signup_then_hr_approves(web):
    services = web.config["SERVICES"]
    client = web.test_client()

    body = _text(client.post("/signup", data={
        "name": "李四", "student_id": "10008", "username": "lisi",
        "password": "lisi123456", "qq": "123456",
    }, follow_redirects=True))
    assert "注册已提交" in body and "等人事审核通过后就能登录" in body

    # 审核前登录：提示等待审核
    body = _text(client.post("/login", data={"username": "lisi",
                                             "password": "lisi123456"},
                             follow_redirects=True))
    assert "还在等待人事审核" in body

    user_id = services.user.find_user("lisi").id

    # 人事在「账号」页看到并审核
    hr_client = web.test_client()
    hr_client.post("/login", data={"username": "hruser", "password": "hrpass123"})
    body = _text(hr_client.get("/users"))
    assert "待审核的注册（1 条）" in body and "李四" in body

    body = _text(hr_client.post(f"/users/signups/{user_id}/approve", data={},
                                follow_redirects=True))
    assert "已通过 李四" in body

    body = _text(client.post("/login", data={"username": "lisi",
                                             "password": "lisi123456"},
                             follow_redirects=True))
    assert "欢迎回来，李四" in body


def test_web_signup_validation_and_reject(web):
    services = web.config["SERVICES"]
    client = web.test_client()

    body = _text(client.post("/signup", data={
        "name": "李四", "student_id": "10001", "username": "lisi",
        "password": "lisi123456",
    }, follow_redirects=True))
    assert "已经在名册里" in body

    client.post("/signup", data={
        "name": "李四", "student_id": "10008", "username": "lisi",
        "password": "lisi123456",
    }, follow_redirects=True)
    user_id = services.user.find_user("lisi").id

    hr_client = web.test_client()
    hr_client.post("/login", data={"username": "hruser", "password": "hrpass123"})
    body = _text(hr_client.post(f"/users/signups/{user_id}/reject",
                                data={"note": "不是本校学生"},
                                follow_redirects=True))
    assert "已驳回 李四" in body

    body = _text(client.post("/login", data={"username": "lisi",
                                             "password": "lisi123456"},
                             follow_redirects=True))
    assert "注册被驳回" in body

    # 普通社员看不到待审核区
    services = web.config["SERVICES"]
    member = services.member.create_member(
        services.member.find_by_token("10001").id, "张三", student_id="10005")
    services.user.add_user(services.member.find_by_token("10001").id,
                           "zhangsan", "zhang123", member.id)
    member_client = web.test_client()
    member_client.post("/login", data={"username": "zhangsan", "password": "zhang123"})
    assert "待审核的注册" not in _text(member_client.get("/users"))
