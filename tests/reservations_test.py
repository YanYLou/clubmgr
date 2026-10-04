"""阶段 2.3：预约 —— 谁都能提交，社长 / 副社长 / 运维审核通过后才进排班表。"""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from domain.models import Role

MONDAY = date(2026, 10, 5)          # 周一
WEDNESDAY = date(2026, 10, 7)       # 同一周的周三


@pytest.fixture
def op1(services, club):
    """club fixture 里没有运营1，这里补一个（预约安排是运营1 的活）。"""
    return services.member.create_member(club.president.id, "运营1",
                                        role=Role.OP1, student_id="10007")


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------

def test_anyone_can_submit_and_week_snaps_to_monday(services, club):
    reservation = services.reservation.create(
        club.member.id, activity_day="wed", week_start=WEDNESDAY)

    assert reservation.status == "pending"
    assert reservation.week_start == MONDAY          # 自动归一到所在周的周一
    assert reservation.order_no == 0                 # 还没排班
    assert reservation.operator_id == club.member.id
    assert reservation.reviewer_id is None


def test_creation_is_not_limited(services, club):
    """提交不设限：三个活动日都能提交。"""
    for day in ("mon", "wed", "fri"):
        services.reservation.create(club.member.id, activity_day=day, week_start=MONDAY)

    assert len(services.reservation.mine(club.member.id)) == 3


def test_invalid_activity_day_is_rejected(services, club):
    with pytest.raises(ValueError):
        services.reservation.create(club.member.id, activity_day="tue")


def test_duplicate_pending_is_rejected(services, club):
    services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)

    with pytest.raises(ValueError) as excinfo:
        services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)

    assert "待审核" in str(excinfo.value)


def test_submitting_for_others_needs_schedule_permission(services, club, op1):
    with pytest.raises(PermissionError):
        services.reservation.create(club.op2.id, activity_day="mon",
                                    week_start=MONDAY, member_id=club.member.id)

    reservation = services.reservation.create(op1.id, activity_day="mon",
                                              week_start=MONDAY, member_id=club.member.id)
    assert reservation.member_id == club.member.id      # 代录：受益人是社员
    assert reservation.operator_id == op1.id            # 提交人记运营1


# ---------------------------------------------------------------------------
# 审核
# ---------------------------------------------------------------------------

def test_review_approves_and_assigns_order(services, club, op1):
    first = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    second = services.reservation.create(club.op2.id, activity_day="mon", week_start=MONDAY)

    approved = services.reservation.review(club.president.id, first.id)
    assert approved.status == "approved"
    assert approved.order_no == 1
    assert approved.reviewer_id == club.president.id
    assert approved.reviewed_at is not None

    # 运维（运营1 / 运营2）也能审，序号接着排
    assert services.reservation.review(op1.id, second.id).order_no == 2


def test_review_requires_permission(services, club):
    reservation = services.reservation.create(club.member.id, activity_day="mon",
                                              week_start=MONDAY)

    with pytest.raises(PermissionError):
        services.reservation.review(club.member.id, reservation.id)     # 普通社员
    with pytest.raises(PermissionError):
        services.reservation.review(club.hr.id, reservation.id)         # 人事


def test_only_pending_can_be_reviewed(services, club):
    reservation = services.reservation.create(club.member.id, activity_day="mon",
                                              week_start=MONDAY)
    services.reservation.review(club.president.id, reservation.id)

    with pytest.raises(ValueError):
        services.reservation.review(club.president.id, reservation.id)


def test_same_person_same_day_cannot_be_approved_twice(services, club):
    first = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    services.reservation.review(club.president.id, first.id)

    second = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    with pytest.raises(ValueError) as excinfo:
        services.reservation.review(club.president.id, second.id)

    assert "已经有排班" in str(excinfo.value)


def test_database_blocks_duplicate_approved_slots(services, club):
    """兜底：绕过服务层直接插第二条「已通过」也会被部分唯一索引拦下。"""
    first = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    services.reservation.review(club.president.id, first.id)
    second = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)

    with pytest.raises(sqlite3.IntegrityError):
        services.reservation.reservation_repo._create(
            replace(second, status="approved", order_no=2))


def test_reject_keeps_out_of_schedule(services, club):
    reservation = services.reservation.create(club.member.id, activity_day="mon",
                                              week_start=MONDAY)
    rejected = services.reservation.reject(club.president.id, reservation.id,
                                           note="当天名额满了")

    assert rejected.status == "rejected"
    assert rejected.note == "当天名额满了"
    assert rejected.reviewer_id == club.president.id

    schedule = services.reservation.schedule(club.member.id, week_start=MONDAY)
    assert all(not items for _, items in schedule["days"])


# ---------------------------------------------------------------------------
# 排班表 / 撤销
# ---------------------------------------------------------------------------

def test_schedule_groups_by_day_and_orders(services, club, op1):
    monday = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    monday2 = services.reservation.create(club.op2.id, activity_day="mon", week_start=MONDAY)
    wednesday = services.reservation.create(op1.id, activity_day="wed", week_start=MONDAY)
    for reservation in (monday, wednesday, monday2):
        services.reservation.review(club.president.id, reservation.id)

    schedule = services.reservation.schedule(club.member.id, week_start=MONDAY)
    days = dict(schedule["days"])

    assert schedule["week_start"] == MONDAY
    assert [r.order_no for r in days["mon"]] == [1, 2]
    assert [r.order_no for r in days["wed"]] == [1]
    assert days["fri"] == []
    assert schedule["names"][club.member.id] == club.member.name


def test_schedule_visible_to_everyone_but_pending_queue_is_not(services, club):
    services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)

    services.reservation.schedule(club.member.id)            # 普通社员可看排班表

    with pytest.raises(PermissionError):
        services.reservation.pending(club.member.id)
    with pytest.raises(PermissionError):
        services.reservation.pending(club.hr.id)

    assert len(services.reservation.pending(club.op2.id)) == 1   # 运维可看审核队列


def test_cancel_frees_the_slot(services, club):
    reservation = services.reservation.create(club.member.id, activity_day="mon",
                                              week_start=MONDAY)
    cancelled = services.reservation.cancel(club.member.id, reservation.id)

    assert cancelled.status == "cancelled"

    again = services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)
    assert services.reservation.review(club.president.id, again.id).order_no == 1


def test_cancel_others_requires_review_permission(services, club):
    reservation = services.reservation.create(club.member.id, activity_day="mon",
                                              week_start=MONDAY)

    with pytest.raises(PermissionError):
        services.reservation.cancel(club.hr.id, reservation.id)

    assert services.reservation.cancel(club.op2.id, reservation.id).status == "cancelled"


def test_mine_can_be_read_by_reviewer_only(services, club):
    services.reservation.create(club.member.id, activity_day="mon", week_start=MONDAY)

    assert len(services.reservation.mine(club.president.id,
                                         member_id=club.member.id)) == 1
    with pytest.raises(PermissionError):
        services.reservation.mine(club.hr.id, member_id=club.member.id)


# ---------------------------------------------------------------------------
# Web 页面
# ---------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path):
    from interfaces.app import create_app

    app = create_app(str(tmp_path / "club.db"), secret_key="test-secret")
    services = app.config["SERVICES"]

    president = services.member.bootstrap("社长", student_id="10001")
    op2 = services.member.create_member(president.id, "运营2",
                                        role=Role.OP2, student_id="10002")
    member = services.member.create_member(president.id, "张三", student_id="10005")
    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "op2user", "op2pass123", op2.id)
    services.user.add_user(president.id, "zhangsan", "zhang123", member.id)
    return app


def _login(app, username: str, password: str):
    client = app.test_client()
    client.post("/login", data={"username": username, "password": password})
    return client


def _text(response) -> str:
    return response.data.decode("utf-8")


def test_web_submit_then_review(web):
    member_client = _login(web, "zhangsan", "zhang123")

    body = _text(member_client.post("/reservations/add", data={
        "activity_day": "wed", "week": "2026-10-07", "note": "打手办",
    }, follow_redirects=True))
    assert "已提交预约" in body
    assert "还没有排班" in body                     # 未审核 → 不进排班表
    assert "待审核（" not in body                   # 普通社员看不到审核队列

    reviewer_client = _login(web, "op2user", "op2pass123")
    body = _text(reviewer_client.get("/reservations"))
    assert "张三" in body and "待审核（1 条）" in body

    body = _text(reviewer_client.post("/reservations/1/approve", data={},
                                      follow_redirects=True))
    assert "已通过预约 #1，排班序号 1" in body

    # 排班表里现在有张三（周一 / 周五仍是空的，周三排上了）
    body = _text(member_client.get("/reservations?week=2026-10-05"))
    assert "张三" in body
    assert body.count("还没有排班") == 2


def test_web_review_requires_permission(web):
    _login(web, "zhangsan", "zhang123").post("/reservations/add", data={
        "activity_day": "mon", "week": "2026-10-05",
    }, follow_redirects=True)

    member_client = _login(web, "zhangsan", "zhang123")
    body = _text(member_client.post("/reservations/1/approve", data={},
                                    follow_redirects=True))
    assert "没有权限" in body


def test_web_reject_and_cancel(web):
    member_client = _login(web, "zhangsan", "zhang123")
    member_client.post("/reservations/add", data={
        "activity_day": "mon", "week": "2026-10-05", "note": "打模型",
    }, follow_redirects=True)

    reviewer_client = _login(web, "op2user", "op2pass123")
    body = _text(reviewer_client.post("/reservations/1/reject",
                                      data={"note": "当天名额满了"},
                                      follow_redirects=True))
    assert "已驳回预约 #1" in body

    body = _text(member_client.get("/reservations"))
    assert "rejected" in body and "当天名额满了" in body

    # 被驳回之后可以重新提交，并且本人可以撤销
    member_client.post("/reservations/add", data={
        "activity_day": "mon", "week": "2026-10-05",
    }, follow_redirects=True)
    body = _text(member_client.post("/reservations/2/cancel", data={},
                                    follow_redirects=True))
    assert "已撤销预约 #2" in body and "cancelled" in body


def test_web_staff_can_submit_for_others(web):
    services = web.config["SERVICES"]
    op1 = services.member.create_member(
        services.member.find_by_token("10001").id, "运营1",
        role=Role.OP1, student_id="10007")
    services.user.add_user(services.member.find_by_token("10001").id,
                           "op1user", "op1pass123", op1.id)

    client = _login(web, "op1user", "op1pass123")
    body = _text(client.post("/reservations/add", data={
        "activity_day": "fri", "week": "2026-10-05",
        "member": "10005", "note": "代录（群里报的名）",
    }, follow_redirects=True))

    assert "已提交预约" in body
    reservation = services.reservation.mine(op1.id)      # 提交人是运营1
    assert reservation == []
    assert services.reservation.mine(op1.id, member_id=services.member.find_by_token("10005").id)

