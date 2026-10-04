"""阶段 3.2：全局配置、站内通知与低库存告警。"""

import pytest

from domain.models import Role
from domain.services import DEFAULT_LOW_STOCK_THRESHOLD, SETTING_LOW_STOCK


# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------

def test_settings_default_and_set(services, club):
    assert services.settings.low_stock_threshold() == DEFAULT_LOW_STOCK_THRESHOLD
    assert services.settings.get(SETTING_LOW_STOCK) is None

    services.settings.set(club.president.id, SETTING_LOW_STOCK, 50, note="低于 50 克就提醒")

    assert services.settings.low_stock_threshold() == 50
    assert services.settings.get(SETTING_LOW_STOCK) == "50"
    # 再写一次是覆盖而不是新增
    services.settings.set(club.president.id, SETTING_LOW_STOCK, "80")
    assert services.settings.low_stock_threshold() == 80
    assert len(services.settings.all(club.president.id)) == 1


def test_settings_write_requires_admin(services, club):
    vp2 = services.member.create_member(club.president.id, "副社长2号",
                                        role="vice_president_2", student_id="10011")
    with pytest.raises(PermissionError):
        services.settings.set(vp2.id, SETTING_LOW_STOCK, 50)
    with pytest.raises(PermissionError):
        services.settings.set(club.op2.id, SETTING_LOW_STOCK, 50)
    with pytest.raises(PermissionError):
        services.settings.all(club.member.id)

    # 社长 / 副社长1号 / 老师可以写
    vp1 = services.member.create_member(club.president.id, "副社长1号",
                                        role="vice_president_1", student_id="10010")
    services.settings.set(vp1.id, SETTING_LOW_STOCK, 50)
    assert services.settings.low_stock_threshold() == 50


# ---------------------------------------------------------------------------
# 站内通知
# ---------------------------------------------------------------------------

def test_send_and_read_notifications(services, club):
    sent = services.notification.send(
        [club.member.id, club.op2.id], type="test", title="测试通知", body="内容",
        ref="thing:1")

    assert len(sent) == 2
    assert services.notification.unread_count(club.member.id) == 1

    inbox = services.notification.list_for(club.member.id)
    assert [n.title for n in inbox] == ["测试通知"]
    assert inbox[0].created_at is not None

    read = services.notification.mark_read(club.member.id, inbox[0].id)
    assert read.read_at is not None
    assert services.notification.unread_count(club.member.id) == 0

    # 只能读自己的
    others = [n for n in sent if n.member_id != club.member.id]
    with pytest.raises(PermissionError):
        services.notification.mark_read(club.member.id, others[0].id)


def test_mark_all_read(services, club):
    services.notification.send([club.member.id], type="t", title="一")
    services.notification.send([club.member.id], type="t", title="二")

    assert services.notification.mark_all_read(club.member.id) == 2
    assert services.notification.unread_count(club.member.id) == 0
    assert services.notification.mark_all_read(club.member.id) == 0


def test_send_to_roles_targets_active_members(services, club):
    services.member.mark_left(club.hr.id, club.op2.id)      # 运营2 退社

    sent = services.notification.send_to_roles(
        (Role.OP1, Role.OP2), type="t", title="给运维")

    assert sent == []                                       # 只有一个运营且已退社


# ---------------------------------------------------------------------------
# 低库存告警
# ---------------------------------------------------------------------------

def test_low_stock_triggers_once_when_crossing_threshold(services, club):
    services.settings.set(club.president.id, SETTING_LOW_STOCK, 100)
    services.filament.purchase(club.president.id, club.filament.id, 150, note="入库")

    # 150 → 60：跨过 100
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 90)

    for person in (club.op2,):                              # 两位运营都收到（club 里只有 op2）
        inbox = services.notification.list_for(person.id)
        assert [n.type for n in inbox] == ["low_stock"]
        assert "只剩 60 克" in inbox[0].title
        assert inbox[0].ref == f"filament:{club.filament.id}"

    # 已经在阈值之下再出库：不再重复通知
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 10)
    assert len(services.notification.list_for(club.op2.id)) == 1


def test_low_stock_not_triggered_when_staying_above(services, club):
    services.settings.set(club.president.id, SETTING_LOW_STOCK, 10)
    services.filament.purchase(club.president.id, club.filament.id, 100, note="入库")

    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 5)

    assert services.notification.list_for(club.op2.id) == []


def test_low_stock_can_be_disabled_with_zero_threshold(services, club):
    services.settings.set(club.president.id, SETTING_LOW_STOCK, 0)
    services.filament.purchase(club.president.id, club.filament.id, 10, note="入库")

    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 9)

    assert services.notification.list_for(club.op2.id) == []
    assert services.stock_alert.low_stock() == []


def test_low_stock_report_lists_filaments_below_threshold(services, club):
    services.settings.set(club.president.id, SETTING_LOW_STOCK, 100)
    services.filament.purchase(club.president.id, club.filament.id, 40, note="入库")

    low = services.stock_alert.low_stock()

    assert [f.name for f, _ in low] == [club.filament.name]
    assert low[0][1] == pytest.approx(40)


def test_low_stock_alert_rolls_back_with_the_print(services, club, monkeypatch):
    """通知与打印同事务：打印失败时通知也不该留下。"""
    services.settings.set(club.president.id, SETTING_LOW_STOCK, 100)
    services.filament.purchase(club.president.id, club.filament.id, 150, note="入库")

    def boom(*args, **kwargs):
        raise RuntimeError("写通知失败")

    monkeypatch.setattr(services.stock_alert, "after_outbound", boom)

    with pytest.raises(RuntimeError):
        services.record.record_print(club.op2.id, club.member.id, club.filament.id, 90)

    assert services.record.list_records(club.president.id) == []
    assert services.notification.list_for(club.op2.id) == []
