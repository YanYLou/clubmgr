"""阶段 3.3：打印机状态（空闲 / 使用中 / 维修中）与可用台数。"""

import pytest

from domain.models import Role
from domain.services import PRINTER_STATUS_LABELS


@pytest.fixture
def printers(services, club):
    """3 台机器，外加一个老师账号。"""
    teacher = services.member.create_member(club.president.id, "王老师",
                                            role=Role.TEACHER, student_id="T001")
    machines = [services.printer.add_printer(club.president.id, f"打印机 {index}")
                for index in (1, 2, 3)]
    return {"teacher": teacher, "machines": machines}


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def test_everyone_can_see_printers(services, club, printers):
    for person in (club.president, club.member, club.op2):
        summary = services.printer.summary(person.id)
        assert len(summary["printers"]) == 3
        assert summary["available"] == 3


def test_available_count_used_by_scheduler(services, club, printers):
    machine = printers["machines"][0]
    services.printer.mark_in_use(club.president.id, machine.id)
    services.printer.mark_maintenance(club.president.id, printers["machines"][1].id,
                                      note="喷头堵了")

    assert services.printer.available_count() == 1          # 不传 operator：内部用
    assert services.printer.available_count(club.member.id) == 1


# ---------------------------------------------------------------------------
# 使用中 / 释放
# ---------------------------------------------------------------------------

def test_teacher_can_mark_own_use_and_release(services, club, printers):
    teacher = printers["teacher"]
    machine = printers["machines"][0]

    used = services.printer.mark_in_use(teacher.id, machine.id, note="打教具")
    assert used.status == "in_use"
    assert used.used_by == teacher.id
    assert used.updated_by == teacher.id

    assert services.printer.available_count() == 2

    released = services.printer.release(teacher.id, machine.id)
    assert released.status == "idle"
    assert released.used_by is None
    assert services.printer.available_count() == 3


def test_operator_can_record_use_for_someone_else(services, club, printers):
    machine = printers["machines"][0]

    used = services.printer.mark_in_use(club.op2.id, machine.id,
                                        member_id=club.member.id)
    assert used.used_by == club.member.id
    assert used.updated_by == club.op2.id


def test_use_permission_and_state_rules(services, club, printers):
    machine = printers["machines"][0]

    with pytest.raises(PermissionError):
        services.printer.mark_in_use(club.member.id, machine.id)   # 普通社员不能标

    with pytest.raises(ValueError):
        services.printer.release(club.president.id, machine.id)    # 空闲的不能释放

    services.printer.mark_in_use(club.president.id, machine.id,
                                 expected_end=None, note="打展品")
    with pytest.raises(ValueError):
        services.printer.release(club.op2.id, 999)                 # 不存在


# ---------------------------------------------------------------------------
# 维修
# ---------------------------------------------------------------------------

def test_maintenance_flow(services, club, printers):
    machine = printers["machines"][1]

    broken = services.printer.mark_maintenance(printers["teacher"].id, machine.id,
                                               note="热床不加热")
    assert broken.status == "maintenance"
    assert broken.note == "热床不加热"
    assert services.printer.available_count() == 2

    # 维修中不能直接当使用中
    with pytest.raises(ValueError) as excinfo:
        services.printer.mark_in_use(club.president.id, machine.id)
    assert "正在维修" in str(excinfo.value)

    fixed = services.printer.finish_maintenance(club.president.id, machine.id)
    assert fixed.status == "idle"
    assert services.printer.available_count() == 3


def test_maintenance_requires_reason_and_permission(services, club, printers):
    machine = printers["machines"][0]

    with pytest.raises(ValueError):
        services.printer.mark_maintenance(club.president.id, machine.id, note="  ")

    with pytest.raises(PermissionError):
        services.printer.mark_maintenance(club.op2.id, machine.id, note="坏了")   # 运营不能标维修

    # 副社长也可以标（现场处理方便）
    vp2 = services.member.create_member(club.president.id, "副社长2号",
                                        role="vice_president_2", student_id="10011")
    assert services.printer.mark_maintenance(
        vp2.id, machine.id, note="皮带松了").status == "maintenance"

    with pytest.raises(ValueError):
        services.printer.finish_maintenance(club.president.id,
                                            printers["machines"][1].id)     # 没在修


# ---------------------------------------------------------------------------
# 增删改
# ---------------------------------------------------------------------------

def test_add_and_update_printer(services, club, printers):
    with pytest.raises(ValueError):
        services.printer.add_printer(club.president.id, "打印机 1")     # 重名

    with pytest.raises(PermissionError):
        services.printer.add_printer(club.op2.id, "打印机 4")           # 运营不能加机器

    fourth = services.printer.add_printer(printers["teacher"].id, "打印机 4",
                                          model="Bambu A1")
    assert fourth.status == "idle"
    assert fourth.model == "Bambu A1"

    renamed = services.printer.update_printer(club.president.id, fourth.id,
                                              name="打印机 4 号", note="备用机")
    assert renamed.name == "打印机 4 号"
    assert renamed.note == "备用机"
    assert renamed.status == "idle"                     # 改名不影响状态


def test_status_labels_cover_all_statuses(services, club, printers):
    from domain.services import PRINTER_STATUSES
    assert set(PRINTER_STATUS_LABELS) == set(PRINTER_STATUSES)


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
    teacher = services.member.create_member(president.id, "王老师",
                                            role=Role.TEACHER, student_id="T001")
    op2 = services.member.create_member(president.id, "运营2",
                                        role=Role.OP2, student_id="10002")
    machine = services.printer.add_printer(president.id, "打印机 1")

    services.user.add_user(president.id, "admin", "admin123", president.id)
    services.user.add_user(president.id, "teacher", "teacher123", teacher.id)
    services.user.add_user(president.id, "op2user", "op2pass123", op2.id)
    app.config["PRINTER_ID"] = machine.id
    return app


def test_web_printer_page_and_actions(web):
    printer_id = web.config["PRINTER_ID"]
    client = web.test_client()
    client.post("/login", data={"username": "teacher", "password": "teacher123"})

    assert "空闲 1 台" in _text(client.get("/printers"))

    body = _text(client.post(f"/printers/{printer_id}/use", data={"note": "打教具"},
                             follow_redirects=True))
    assert "已标记为使用中" in body and "使用中 1 台" in body

    body = _text(client.post(f"/printers/{printer_id}/release", data={},
                             follow_redirects=True))
    assert "已释放" in body

    body = _text(client.post(f"/printers/{printer_id}/maintenance",
                             data={"note": "喷头堵了"}, follow_redirects=True))
    assert "已标记为维修中" in body and "维修中 1 台" in body

    body = _text(client.post(f"/printers/{printer_id}/fixed", data={},
                             follow_redirects=True))
    assert "已修好" in body and "空闲 1 台" in body


def test_web_operator_cannot_mark_maintenance(web):
    printer_id = web.config["PRINTER_ID"]
    client = web.test_client()
    client.post("/login", data={"username": "op2user", "password": "op2pass123"})

    body = _text(client.post(f"/printers/{printer_id}/maintenance",
                             data={"note": "坏了"}, follow_redirects=True))

    assert "没有权限" in body


def test_web_home_shows_printer_summary(web):
    client = web.test_client()
    client.post("/login", data={"username": "op2user", "password": "op2pass123"})

    body = _text(client.get("/"))

    assert "打印机" in body and "空闲" in body
