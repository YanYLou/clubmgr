"""阶段 3.6：时间格排班（默认 16:55–17:40，容量按当时可用打印机台数）。"""

from datetime import date, datetime

import pytest

from domain.models import Role
from domain.services import DEFAULT_SLOT_END, DEFAULT_SLOT_START

MONDAY = date(2026, 10, 5)          # 周一
WEDNESDAY = date(2026, 10, 7)       # 周三
THURSDAY = date(2026, 10, 8)        # 周四


@pytest.fixture
def club_ops(services, club):
    """运营1 + 3 台打印机（容量 = 可用台数）。"""
    op1 = services.member.create_member(club.president.id, "运营1",
                                        role=Role.OP1, student_id="10007")
    for index in (1, 2, 3):
        services.printer.add_printer(club.president.id, f"打印机 {index}")
    return op1


def _approve(services, operator_id, member_id, day, week=MONDAY, order=None):
    reservation = services.reservation.create(operator_id, activity_day=day,
                                              week_start=week, member_id=member_id)
    return services.reservation.review(operator_id, reservation.id, approve=True,
                                       order_no=order)


# ---------------------------------------------------------------------------
# 生成与查看
# ---------------------------------------------------------------------------

def test_ensure_week_creates_default_slots_once(services, club, club_ops):
    created = services.schedule.ensure_week(club_ops.id, MONDAY)

    assert [slot.slot_date for slot in created] == [MONDAY, WEDNESDAY, date(2026, 10, 9)]
    assert all(slot.start_time == DEFAULT_SLOT_START for slot in created)
    assert all(slot.end_time == DEFAULT_SLOT_END for slot in created)
    assert all(slot.status == "open" for slot in created)

    # 幂等：再跑一次不会重复建
    assert services.schedule.ensure_week(club_ops.id, MONDAY) == []
    assert len(services.schedule.week_view(club_ops.id, MONDAY)["slots"]) == 3


def test_week_view_shows_capacity_and_people(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)
    reservation = _approve(services, club_ops.id, club.member.id, "wed")
    services.schedule.assign(club_ops.id, reservation.id,
                             services.schedule.week_view(club_ops.id, MONDAY)["slots"][1]["slot"].id)

    view = services.schedule.week_view(club_ops.id, MONDAY)
    wednesday = view["slots"][1]

    assert wednesday["weekday_label"] == "周三"
    assert wednesday["capacity"] == 3                       # 3 台空闲打印机
    assert wednesday["free"] == 2
    assert [r.id for r in wednesday["assigned"]] == [reservation.id]
    assert view["names"][club.member.id] == club.member.name
    assert view["available_printers"] == 3
    assert view["unassigned"] == []


def test_capacity_follows_printer_availability(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)
    view = services.schedule.week_view(club_ops.id, MONDAY)
    slot_id = view["slots"][0]["slot"].id

    services.printer.mark_maintenance(club.president.id, 1, note="喷头堵了")
    services.printer.mark_in_use(club.president.id, 2)

    assert services.schedule.week_view(club_ops.id, MONDAY)["slots"][0]["capacity"] == 1

    first = _approve(services, club_ops.id, club.member.id, "mon")
    second = _approve(services, club_ops.id, club.op2.id, "mon")
    services.schedule.assign(club_ops.id, first.id, slot_id)

    with pytest.raises(ValueError) as excinfo:
        services.schedule.assign(club_ops.id, second.id, slot_id)
    assert "已排满" in str(excinfo.value)

    # 修好一台就能排了
    services.printer.release(club.president.id, 2)
    services.printer.finish_maintenance(club.president.id, 1)
    services.schedule.assign(club_ops.id, second.id, slot_id)
    assert services.schedule.week_view(club_ops.id, MONDAY)["slots"][0]["free"] == 1


def test_slot_can_have_explicit_capacity(services, club, club_ops):
    slot = services.schedule.add_slot(club_ops.id, slot_date=MONDAY,
                                      start_time="13:00", end_time="14:00",
                                      capacity=1, note="只有一台机器")

    first = _approve(services, club_ops.id, club.member.id, "mon")
    second = _approve(services, club_ops.id, club.op2.id, "mon")
    services.schedule.assign(club_ops.id, first.id, slot.id)

    with pytest.raises(ValueError):
        services.schedule.assign(club_ops.id, second.id, slot.id)


# ---------------------------------------------------------------------------
# 改时间 / 改日期 / 停用
# ---------------------------------------------------------------------------

def test_change_date_marks_people_reschedule_and_notifies(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)
    slot = services.schedule.week_view(club_ops.id, MONDAY)["slots"][1]["slot"]
    reservation = _approve(services, club_ops.id, club.member.id, "wed")
    services.schedule.assign(club_ops.id, reservation.id, slot.id)
    services.notification.mark_all_read(club.member.id)

    # 周三改周四
    services.schedule.update_slot(club_ops.id, slot.id, slot_date=THURSDAY)

    moved = services.reservation._reservation(reservation.id)
    assert moved.status == "reschedule"
    assert moved.slot_id is None
    assert "改到" in moved.urgent_reason

    inbox = services.notification.list_for(club.member.id, unread_only=True)
    assert len(inbox) == 1 and "重新安排" in inbox[0].title

    view = services.schedule.week_view(club_ops.id, MONDAY)
    assert view["unassigned"] == []
    assert [item["slot"].slot_date for item in view["slots"]] == [
        MONDAY, THURSDAY, date(2026, 10, 9)]


def test_close_slot_releases_people(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)
    slot = services.schedule.week_view(club_ops.id, MONDAY)["slots"][2]["slot"]
    reservation = _approve(services, club_ops.id, club.member.id, "fri")
    services.schedule.assign(club_ops.id, reservation.id, slot.id)

    closed = services.schedule.close_slot(club_ops.id, slot.id, note="学校占用场地")

    assert closed.status == "closed"
    assert services.reservation._reservation(reservation.id).status == "reschedule"
    assert services.notification.list_for(club.member.id, unread_only=True)

    # 停用的格子不能再排人
    again = _approve(services, club_ops.id, club.op2.id, "fri")
    with pytest.raises(ValueError) as excinfo:
        services.schedule.assign(club_ops.id, again.id, slot.id)
    assert "已停用" in str(excinfo.value)

    services.schedule.reopen_slot(club_ops.id, slot.id)
    services.schedule.assign(club_ops.id, again.id, slot.id)
    assert len(services.schedule.week_view(club_ops.id, MONDAY)["slots"][2]["assigned"]) == 1


def test_update_slot_validates_time(services, club, club_ops):
    slot = services.schedule.add_slot(club_ops.id, slot_date=MONDAY,
                                      start_time="16:55", end_time="17:40")

    with pytest.raises(ValueError):
        services.schedule.update_slot(club_ops.id, slot.id, end_time="16:00")
    with pytest.raises(ValueError):
        services.schedule.add_slot(club_ops.id, slot_date=MONDAY,
                                   start_time="4点半", end_time="17:40")
    with pytest.raises(ValueError):
        services.schedule.add_slot(club_ops.id, slot_date=MONDAY,
                                   start_time="16:00", end_time="17:00", capacity=-1)


# ---------------------------------------------------------------------------
# 排人 / 一键填充
# ---------------------------------------------------------------------------

def test_assign_rules(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)
    slots = services.schedule.week_view(club_ops.id, MONDAY)["slots"]
    wednesday, friday = slots[1]["slot"], slots[2]["slot"]

    pending = services.reservation.create(club.member.id, activity_day="wed",
                                          week_start=MONDAY)
    with pytest.raises(ValueError) as excinfo:
        services.schedule.assign(club_ops.id, pending.id, wednesday.id)
    assert "只有已通过" in str(excinfo.value)
    services.reservation.cancel(club.member.id, pending.id)      # 腾出"同一天一条"的名额

    # 同一周的周一预约不能排进下周的格子
    other_week = services.schedule.add_slot(club_ops.id, slot_date=date(2026, 10, 12),
                                            start_time="16:55", end_time="17:40")
    approved = _approve(services, club_ops.id, club.member.id, "wed")
    with pytest.raises(ValueError) as excinfo:
        services.schedule.assign(club_ops.id, approved.id, other_week.id)
    assert "不在同一周" in str(excinfo.value)

    # 同一天只能排一条
    services.schedule.assign(club_ops.id, approved.id, wednesday.id)
    same_day = _approve(services, club_ops.id, club.member.id, "mon")
    with pytest.raises(ValueError):
        services.schedule.assign(club_ops.id, same_day.id, wednesday.id)

    # 幂等 + 可以拿出来
    assert services.schedule.assign(club_ops.id, approved.id, wednesday.id).slot_id == \
        wednesday.id
    assert services.schedule.unassign(club_ops.id, approved.id).slot_id is None
    assert approved.id in {r.id for r in
                           services.schedule.week_view(club_ops.id, MONDAY)["unassigned"]}

    with pytest.raises(ValueError):
        services.schedule.assign(club_ops.id, approved.id, 999)


def test_auto_fill_puts_approved_reservations_into_slots(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)

    zhang = _approve(services, club_ops.id, club.member.id, "wed")
    ops2 = _approve(services, club_ops.id, club.op2.id, "fri")
    hr = _approve(services, club_ops.id, club.hr.id, "mon")

    result = services.schedule.auto_fill(club_ops.id, MONDAY)

    assert sorted(r.id for r in result["assigned"]) == sorted([zhang.id, ops2.id, hr.id])
    assert result["skipped"] == []

    view = services.schedule.week_view(club_ops.id, MONDAY)
    monday, wednesday, friday = view["slots"]
    assert [r.id for r in monday["assigned"]] == [hr.id]
    assert [r.id for r in wednesday["assigned"]] == [zhang.id]
    assert [r.id for r in friday["assigned"]] == [ops2.id]
    assert view["unassigned"] == []


def test_auto_fill_respects_capacity_and_reports_skipped(services, club, club_ops):
    # 只留一台机器：一格最多 1 人
    services.printer.mark_maintenance(club.president.id, 1, note="坏")
    services.printer.mark_maintenance(club.president.id, 2, note="坏")
    services.schedule.ensure_week(club_ops.id, MONDAY)

    first = _approve(services, club_ops.id, club.member.id, "wed")
    second = _approve(services, club_ops.id, club.op2.id, "wed")
    third = _approve(services, club_ops.id, club.hr.id, "wed")

    result = services.schedule.auto_fill(club_ops.id, MONDAY, slot_date=WEDNESDAY)

    assert len(result["assigned"]) == 1
    assert len(result["skipped"]) == 2
    assert result["assigned"][0].id == first.id             # 序号在前面的先排
    assert {r.id for r in result["skipped"]} == {second.id, third.id}


def test_auto_fill_without_slots(services, club, club_ops):
    """周三那格停用后，不限定某一天填充时，这条会被安排到别的空格子。"""
    services.schedule.ensure_week(club_ops.id, MONDAY)
    slots = services.schedule.week_view(club_ops.id, MONDAY)["slots"]
    services.schedule.close_slot(club_ops.id, slots[1]["slot"].id, note="场地被占")

    reservation = _approve(services, club_ops.id, club.member.id, "wed")
    result = services.schedule.auto_fill(club_ops.id, MONDAY)

    assert [r.id for r in result["assigned"]] == [reservation.id]
    assert services.reservation._reservation(reservation.id).slot_id != slots[1]["slot"].id


def test_auto_fill_with_day_filter_reports_when_no_slot(services, club, club_ops):
    """限定某一天但那天没有可用格子 → 不硬塞，返回原因。"""
    services.schedule.ensure_week(club_ops.id, MONDAY)
    _approve(services, club_ops.id, club.member.id, "wed")

    result = services.schedule.auto_fill(club_ops.id, MONDAY, slot_date=THURSDAY)

    assert result["assigned"] == [] and result["skipped"] == []
    assert "没有可用的时间格" in result["reason"]


def test_schedule_permissions(services, club, club_ops):
    with pytest.raises(PermissionError):
        services.schedule.ensure_week(club.member.id, MONDAY)

    services.schedule.ensure_week(club_ops.id, MONDAY)
    slot = services.schedule.week_view(club_ops.id, MONDAY)["slots"][0]["slot"]
    reservation = _approve(services, club_ops.id, club.member.id, "mon")

    for action in (lambda: services.schedule.add_slot(
                        club.member.id, slot_date=THURSDAY, start_time="13:00",
                        end_time="14:00"),
                   lambda: services.schedule.close_slot(club.hr.id, slot.id),
                   lambda: services.schedule.assign(club.member.id, reservation.id, slot.id),
                   lambda: services.schedule.auto_fill(club.member.id, MONDAY)):
        with pytest.raises(PermissionError):
            action()

    # 但谁都能看这一周的时间格
    assert services.schedule.week_view(club.member.id, MONDAY)["slots"]


def test_week_view_available_to_everyone_including_pending_free_slots(services, club, club_ops):
    services.schedule.ensure_week(club_ops.id, MONDAY)

    view = services.schedule.week_view(club.hr.id, MONDAY)

    assert len(view["slots"]) == 3
    assert all(item["free"] == 3 for item in view["slots"])
    assert view["unassigned"] == []


def test_slot_created_at_and_staff_fields(services, club, club_ops):
    slot = services.schedule.add_slot(club_ops.id, slot_date=MONDAY,
                                      start_time="13:00", end_time="14:00",
                                      note="临时加场")

    assert isinstance(slot.created_at, datetime)
    assert slot.created_by == club_ops.id
    assert slot.week_start == MONDAY
    assert services.schedule.week_view(club_ops.id, MONDAY)["slots"][0]["slot"].note == "临时加场"


# ---------------------------------------------------------------------------
# Web 页面
# ---------------------------------------------------------------------------

def _text(response) -> str:
    return response.data.decode("utf-8")


@pytest.fixture
def web(tmp_path):
    from interfaces.app import create_app

    app = create_app(str(tmp_path / "club.db"), secret_key="test-secret")
    services = app.config["SERVICES"]

    president = services.member.bootstrap("社长", student_id="10001")
    op1 = services.member.create_member(president.id, "运营1",
                                       role=Role.OP1, student_id="10006")
    member = services.member.create_member(president.id, "张三", student_id="10005")
    for index in (1, 2):
        services.printer.add_printer(president.id, f"打印机 {index}")

    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "op1user", "op1pass123", op1.id)
    services.user.add_user(president.id, "zhangsan", "zhang123", member.id)
    return app


def _login(app, username, password):
    client = app.test_client()
    client.post("/login", data={"username": username, "password": password})
    return client


def test_web_schedule_page_and_actions(web):
    services = web.config["SERVICES"]
    op_client = _login(web, "op1user", "op1pass123")

    body = _text(op_client.post("/schedule/ensure", data={"week": "2026-10-05"},
                                follow_redirects=True))
    assert "已按默认规则补齐 3 个时间格" in body
    assert "周一" in body and "周三" in body and "周五" in body
    assert "16:55–17:40" in body
    assert "按机器数" in body                      # 容量 0 时按打印机台数

    # 社员提交 → 运营审核通过 → 一键填充
    member_client = _login(web, "zhangsan", "zhang123")
    member_client.post("/reservations/add", data={
        "activity_day": "wed", "week": "2026-10-05", "note": "打手办",
    }, follow_redirects=True)
    op_client.post("/reservations/1/approve", data={"order": "1"}, follow_redirects=True)

    body = _text(op_client.post("/schedule/fill", data={"week": "2026-10-05"},
                                follow_redirects=True))
    assert "一键填充完成：排进 1 条" in body
    assert "1. 张三" in body

    # 社员也能看这一周的时间格
    body = _text(member_client.get("/schedule?week=2026-10-05"))
    assert "1. 张三" in body and "16:55–17:40" in body


def test_web_schedule_requires_permission(web):
    member_client = _login(web, "zhangsan", "zhang123")
    op_client = _login(web, "op1user", "op1pass123")
    op_client.post("/schedule/ensure", data={"week": "2026-10-05"}, follow_redirects=True)

    body = _text(member_client.post("/schedule/ensure", data={"week": "2026-10-05"},
                                    follow_redirects=True))
    assert "没有权限" in body

    # 页面里也看不到排班操作表单
    page = _text(member_client.get("/schedule?week=2026-10-05"))
    assert "按默认规则补齐本周时间格" not in page and "一键填充本周" not in page


def test_web_change_slot_date_releases_people(web):
    services = web.config["SERVICES"]
    op_client = _login(web, "op1user", "op1pass123")
    op_client.post("/schedule/ensure", data={"week": "2026-10-05"}, follow_redirects=True)

    member_client = _login(web, "zhangsan", "zhang123")
    member_client.post("/reservations/add", data={
        "activity_day": "wed", "week": "2026-10-05",
    }, follow_redirects=True)
    op_client.post("/reservations/1/approve", data={"order": "1"}, follow_redirects=True)
    op_client.post("/schedule/fill", data={"week": "2026-10-05"}, follow_redirects=True)

    sunday_slot = services.schedule.week_view(1, date(2026, 10, 5))["slots"][1]["slot"]
    body = _text(op_client.post(f"/schedule/{sunday_slot.id}/close",
                                data={"note": "场地被学校占用"},
                                follow_redirects=True))

    assert "已停用 2026-10-07" in body
    assert services.reservation._reservation(1).status == "reschedule"
    # 本人收到通知
    zhang = services.member.find_by_token("10005")
    assert services.notification.list_for(zhang.id, unread_only=True)
