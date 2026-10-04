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


def _approved(services, operator_id, member_id, day, week=MONDAY):
    reservation = services.reservation.create(operator_id, activity_day=day,
                                              week_start=week, member_id=member_id)
    return services.reservation.review(operator_id, reservation.id, approve=True)


# ---------------------------------------------------------------------------
# 紧急任务（阶段 3.4）：提到本周 + 插队
# ---------------------------------------------------------------------------

def test_urgent_pull_moves_to_this_week_and_shifts_others(services, club, op1):
    # 周三已排两个人：张三（序号 1）、运营2（序号 2）
    first = _approved(services, op1.id, club.member.id, "wed")
    second = _approved(services, op1.id, club.op2.id, "wed")
    assert (first.order_no, second.order_no) == (1, 2)

    # 下周一有一条待审核的预约，学校任务要把它提到本周周三最前面
    later = services.reservation.create(club.hr.id, activity_day="mon",
                                        week_start=date(2026, 10, 12))

    urgent = services.reservation.pull_to_this_week(
        op1.id, later.id, week_start=WEDNESDAY, activity_day="wed",
        note="学校下派的展示模型")

    assert urgent.status == "approved"
    assert urgent.order_no == 1
    assert urgent.week_start == MONDAY                     # 归一到周一
    assert urgent.activity_day == "wed"
    assert urgent.urgent_by == op1.id
    assert urgent.urgent_reason == "学校下派的展示模型"
    assert urgent.urgent_at is not None

    # 原来的人整体后移
    assert services.reservation._reservation(first.id).order_no == 2
    assert services.reservation._reservation(second.id).order_no == 3

    # 被顺延的两位都收到通知，本人也收到"已提前"
    assert services.notification.unread_count(club.member.id) == 1
    assert services.notification.unread_count(club.op2.id) == 1
    assert services.notification.unread_count(club.hr.id) == 1
    titles = [n.title for n in services.notification.list_for(club.op2.id)]
    assert "顺延" in titles[0]


def test_urgent_pull_requires_reason_and_permission(services, club, op1):
    approved = _approved(services, op1.id, club.member.id, "wed")

    with pytest.raises(ValueError):
        services.reservation.pull_to_this_week(op1.id, approved.id, note="   ")

    with pytest.raises(PermissionError):
        services.reservation.pull_to_this_week(club.hr.id, approved.id, note="学校任务")

    with pytest.raises(PermissionError):
        services.reservation.pull_to_this_week(club.member.id, approved.id, note="学校任务")


def test_urgent_pull_rejects_same_member_same_day(services, club, op1):
    approved = _approved(services, op1.id, club.member.id, "wed")
    other = _approved(services, op1.id, club.member.id, "fri")

    with pytest.raises(ValueError) as excinfo:
        services.reservation.pull_to_this_week(op1.id, other.id, week_start=MONDAY,
                                               activity_day="wed", note="学校任务")
    assert "已经有排班" in str(excinfo.value)


def test_urgent_pull_rejects_bad_day_and_status(services, club, op1):
    approved = _approved(services, op1.id, club.member.id, "wed")

    with pytest.raises(ValueError):
        services.reservation.pull_to_this_week(op1.id, approved.id,
                                               activity_day="tue", note="学校任务")

    cancelled = services.reservation.cancel(club.member.id, approved.id)
    assert cancelled.status == "cancelled"
    with pytest.raises(ValueError) as excinfo:
        services.reservation.pull_to_this_week(op1.id, approved.id, note="学校任务")
    assert "不能提前" in str(excinfo.value)


def test_bump_sets_reschedule_and_notifies_owner(services, club, op1):
    approved = _approved(services, op1.id, club.member.id, "wed")
    services.notification.mark_all_read(club.member.id)

    bumped = services.reservation.bump(op1.id, approved.id, note="学校任务要占用")

    assert bumped.status == "reschedule"
    assert bumped.order_no == 0
    assert bumped.urgent_reason == "学校任务要占用"

    assert services.reservation.schedule(op1.id)["days"][1][1] == []      # 周三空了
    assert [r.id for r in services.reservation.reschedule_list(op1.id)] == [approved.id]

    inbox = services.notification.list_for(club.member.id, unread_only=True)
    assert len(inbox) == 1 and "紧急任务" in inbox[0].title

    # 待重排的还能重新排上
    again = services.reservation.review(op1.id, approved.id, approve=True)
    assert again.status == "approved" and again.order_no == 1


def test_bump_rules(services, club, op1):
    pending = services.reservation.create(club.member.id, activity_day="wed",
                                          week_start=MONDAY)

    with pytest.raises(ValueError) as excinfo:
        services.reservation.bump(op1.id, pending.id, note="学校任务")
    assert "只有已通过" in str(excinfo.value)

    with pytest.raises(ValueError):
        services.reservation.bump(op1.id, pending.id, note="  ")

    with pytest.raises(PermissionError):
        services.reservation.bump(club.hr.id, pending.id, note="学校任务")


def test_reschedule_list_requires_review_permission(services, club, op1):
    _approved(services, op1.id, club.member.id, "wed")

    with pytest.raises(PermissionError):
        services.reservation.reschedule_list(club.member.id)

    assert services.reservation.reschedule_list(club.op2.id) == []


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
        services.reservation.create(club.hr.id, activity_day="mon",
                                    week_start=MONDAY, member_id=club.member.id)

    reservation = services.reservation.create(op1.id, activity_day="mon",
                                              week_start=MONDAY, member_id=club.member.id)
    assert reservation.member_id == club.member.id      # 代录：受益人是社员
    assert reservation.operator_id == op1.id            # 提交人记运营1

    # 阶段 3.1 起两位运营权限一致：运营2 也能代录
    services.reservation.cancel(op1.id, reservation.id)
    reserved_by_op2 = services.reservation.create(
        club.op2.id, activity_day="mon", week_start=MONDAY, member_id=club.member.id)
    assert reserved_by_op2.operator_id == club.op2.id


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
    assert "已驳回" in body and "当天名额满了" in body

    # 被驳回之后可以重新提交，并且本人可以撤销
    member_client.post("/reservations/add", data={
        "activity_day": "mon", "week": "2026-10-05",
    }, follow_redirects=True)
    body = _text(member_client.post("/reservations/2/cancel", data={},
                                    follow_redirects=True))
    assert "已撤销预约 #2" in body and "已撤销" in body


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


def test_web_urgent_and_bump(web):
    """阶段 3.4：页面上的紧急提前与挤掉。"""
    services = web.config["SERVICES"]
    member_client = _login(web, "zhangsan", "zhang123")
    member_client.post("/reservations/add", data={
        "activity_day": "wed", "week": "2026-10-05", "note": "打模型",
    }, follow_redirects=True)

    reviewer = _login(web, "op2user", "op2pass123")
    reviewer.post("/reservations/1/approve", data={"order": "1"}, follow_redirects=True)

    body = _text(reviewer.get("/reservations?week=2026-10-05"))
    assert "紧急任务（本周已通过的排班）" in body and "挤掉" in body

    # 原因必填
    body = _text(reviewer.post("/reservations/1/urgent", data={
        "week": "2026-10-05", "note": "  "}, follow_redirects=True))
    assert "必须写备注" in body

    body = _text(reviewer.post("/reservations/1/urgent", data={
        "week": "2026-10-05", "day": "wed", "note": "学校下派任务",
    }, follow_redirects=True))
    assert "已紧急提前 #1" in body
    assert "［紧急］" in body and "学校下派任务" in body

    saved = services.reservation._reservation(1)
    assert saved.urgent_reason == "学校下派任务" and saved.urgent_by is not None

    # 挤掉：退回待重排并通知本人
    body = _text(reviewer.post("/reservations/1/bump", data={
        "note": "学校任务占用"}, follow_redirects=True))
    assert "已挤掉排班 #1" in body

    saved = services.reservation._reservation(1)
    assert saved.status == "reschedule"
    assert services.notification.list_for(
        services.member.find_by_token("10005").id, unread_only=True)

    # 待重排区可以看到并重新排上
    body = _text(reviewer.get("/reservations?week=2026-10-05"))
    assert "待重排" in body and "重新排上" in body

    body = _text(reviewer.post("/reservations/1/approve", data={"order": "1"},
                               follow_redirects=True))
    assert "已通过预约 #1" in body
    assert services.reservation._reservation(1).status == "approved"


def test_web_urgent_requires_permission(web):
    member_client = _login(web, "zhangsan", "zhang123")
    member_client.post("/reservations/add", data={
        "activity_day": "wed", "week": "2026-10-05",
    }, follow_redirects=True)

    body = _text(member_client.post("/reservations/1/urgent", data={
        "week": "2026-10-05", "note": "我想插队"}, follow_redirects=True))
    assert "没有权限" in body

    # 普通社员的页面也看不到紧急操作区
    assert "紧急任务（本周已通过的排班）" not in _text(
        member_client.get("/reservations?week=2026-10-05"))

