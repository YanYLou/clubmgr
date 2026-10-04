"""阶段 1.3 / 1.5：服务层测试 —— 权限、事务联动、拍板结论落地。

fixture 见 ``conftest.py``：``db``（内存库）、``services``（装配好的服务层）、
``club``（社长 / 运营2 / 人事 / 普通社员 + PLA 耗材 + 每人 200 克额度）。
"""

from datetime import date

import pytest

from domain.models import Role


# ---------------------------------------------------------------------------
# 社员
# ---------------------------------------------------------------------------

def test_bootstrap_only_works_on_empty_database(services, club):
    with pytest.raises(RuntimeError):
        services.member.bootstrap("第二个社长")


def test_member_creation_requires_edit_permission(services, club):
    with pytest.raises(PermissionError):
        services.member.create_member(club.op2.id, "新社员")        # 运营2：无 edit_members
    with pytest.raises(PermissionError):
        services.member.create_member(club.member.id, "新社员")     # 普通社员：无权限

    created = services.member.create_member(club.hr.id, "人事招的人", student_id="10005")
    assert created.role is Role.MEMBER
    assert created.status == "active"


def test_duplicate_student_id_is_rejected(services, club):
    with pytest.raises(ValueError) as excinfo:
        services.member.create_member(club.president.id, "重号",
                                      student_id=club.op2.student_id)
    assert "学号" in str(excinfo.value)


def test_update_member_validates_fields(services, club):
    with pytest.raises(ValueError):
        services.member.update_member(club.president.id, club.member.id, id=99)
    with pytest.raises(ValueError):
        services.member.update_member(club.president.id, club.member.id, status="unknown")

    updated = services.member.update_member(club.president.id, club.member.id, role="op2")
    assert updated.role is Role.OP2


def test_mark_left_keeps_history_and_excludes_from_new_quota(services, club):
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 10)
    services.member.mark_left(club.hr.id, club.member.id)

    assert services.member.get_member(club.president.id, club.member.id).status == "left"
    assert len(services.record.list_records(club.president.id,
                                            member_id=club.member.id)) == 1

    # 退社的人不再参与学期初发放（其他人补发 100）
    services.quota.init_semester(club.president.id, 100, allow_repeat=True)
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(190)
    assert services.report.balance_of(club.president.id, club.op2.id) == pytest.approx(300)


# ---------------------------------------------------------------------------
# 额度
# ---------------------------------------------------------------------------

def test_init_semester_covers_active_members_once(services, club):
    for person in (club.president, club.op2, club.hr, club.member):
        assert services.report.balance_of(club.president.id, person.id) == pytest.approx(200)

    with pytest.raises(RuntimeError) as excinfo:
        services.quota.init_semester(club.president.id, 200)
    assert "已经发过" in str(excinfo.value)


def test_init_semester_permission_and_specific_members(services, club):
    with pytest.raises(PermissionError):
        services.quota.init_semester(club.hr.id, 200, allow_repeat=True)   # 人事无权调整额度

    newcomer = services.member.create_member(club.hr.id, "新生", student_id="10006")
    txns = services.quota.init_semester(club.president.id, 50, member_ids=[newcomer.id])

    assert len(txns) == 1
    assert txns[0].amount == 50
    assert services.report.balance_of(club.president.id, newcomer.id) == pytest.approx(50)


def test_adjust_quota_requires_note_and_permission(services, club):
    with pytest.raises(PermissionError):
        services.quota.adjust(club.op2.id, club.member.id, 10, "无权限")
    with pytest.raises(ValueError):
        services.quota.adjust(club.president.id, club.member.id, 10, "   ")
    with pytest.raises(ValueError):
        services.quota.adjust(club.president.id, club.member.id, 0, "零调整")

    txn = services.quota.adjust(club.president.id, club.member.id, -30, "上学期欠额度")
    assert txn.type == "manual_adjust"
    assert txn.amount == -30
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(170)


# ---------------------------------------------------------------------------
# 打印记录（核心闭环）
# ---------------------------------------------------------------------------

def test_record_print_writes_three_tables(services, club):
    record = services.record.record_print(
        club.op2.id, club.member.id, club.filament.id, 42.5,
        printer_name="P1", date=date(2026, 9, 1), comments="测试件")

    assert record.id is not None
    assert record.filament_id == club.filament.id
    assert record.filament_name == "PLA 白"          # 历史快照
    assert record.operator_id == club.op2.id

    # 额度 -42.5
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(157.5)
    # 库存 -42.5
    assert services.report.stock_of(club.op2.id, club.filament.id) == pytest.approx(-42.5)
    # 额度流水能追回打印记录
    statement = services.report.member_statement(club.member.id, club.member.id)
    assert any(t.related_record_id == record.id for t in statement["quota"])


def test_record_print_validates_inputs_and_permission(services, club):
    with pytest.raises(PermissionError):
        services.record.record_print(club.member.id, club.member.id, club.filament.id, 5)
    with pytest.raises(PermissionError):
        services.record.record_print(club.hr.id, club.member.id, club.filament.id, 5)
    with pytest.raises(ValueError):
        services.record.record_print(club.op2.id, club.member.id, club.filament.id, 0)
    with pytest.raises(ValueError):
        services.record.record_print(club.op2.id, club.member.id, 999, 5)       # 耗材不存在
    with pytest.raises(ValueError):
        services.record.record_print(club.op2.id, 999, club.filament.id, 5)     # 社员不存在


def test_overdraft_limited_to_full_roles(services, club):
    """拍板结论：额度不足时允许透支，但只有社长/副社长能记。"""
    with pytest.raises(PermissionError) as excinfo:
        services.record.record_print(club.op2.id, club.member.id, club.filament.id, 250)
    assert "额度不足" in str(excinfo.value)
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(200)

    services.record.record_print(club.president.id, club.member.id, club.filament.id, 250)
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(-50)


def test_record_print_rolls_back_all_three_tables_on_failure(services, club, monkeypatch):
    def boom(entity):
        raise RuntimeError("库存写入失败")

    monkeypatch.setattr(services.record.inventory_repo, "_create", boom)

    with pytest.raises(RuntimeError):
        services.record.record_print(club.op2.id, club.member.id, club.filament.id, 30)

    assert services.record.list_records(club.president.id) == []                 # records 不留痕
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(200)
    assert services.report.stock_of(club.president.id, club.filament.id) == pytest.approx(0)


# ---------------------------------------------------------------------------
# 耗材 / 经费
# ---------------------------------------------------------------------------

def test_purchase_writes_stock_and_fund_expense(services, club):
    services.fund.income(club.president.id, 500, note="会费收入")

    services.filament.purchase(club.president.id, club.filament.id, 1000, 150, note="采购 1kg")
    assert services.report.stock_of(club.president.id, club.filament.id) == pytest.approx(1000)
    assert services.report.fund_balance(club.president.id) == pytest.approx(350)

    # 捐赠 / 免费样品：total_cost = 0 时不写 0 元经费流水
    services.filament.purchase(club.president.id, club.filament.id, 200, 0, note="捐赠")
    assert services.report.fund_balance(club.president.id) == pytest.approx(350)
    assert len(services.report.fund_report(club.president.id)["transactions"]) == 2


def test_filament_management_requires_purchase_permission(services, club):
    with pytest.raises(PermissionError):
        services.filament.purchase(club.op2.id, club.filament.id, 100, 10)
    with pytest.raises(PermissionError):
        services.filament.create_filament(club.op2.id, "PETG 红")
    with pytest.raises(ValueError):
        services.filament.create_filament(club.president.id, "PLA 白")     # 重名


def test_fund_entries_require_note_and_permission(services, club):
    with pytest.raises(PermissionError):
        services.fund.income(club.hr.id, 100, note="没权限")
    with pytest.raises(ValueError):
        services.fund.income(club.president.id, 100, note="   ")
    with pytest.raises(ValueError):
        services.fund.expense(club.president.id, -5, note="负数")

    services.fund.expense(club.president.id, 30, note="买胶水")
    assert services.report.fund_balance(club.president.id) == pytest.approx(-30)


# ---------------------------------------------------------------------------
# 贡献
# ---------------------------------------------------------------------------

def test_contribution_rewards_quota(services, club):
    contribution = services.contribution.add(
        club.president.id, club.member.id, 100, type="money",
        reward_quota=50, note="捐赠耗材费")

    assert contribution.reward_quota == 50
    assert services.report.balance_of(club.president.id, club.member.id) == pytest.approx(250)

    with pytest.raises(ValueError):
        services.contribution.add(club.president.id, club.member.id, 0, type="material")
    with pytest.raises(ValueError):
        services.contribution.add(club.president.id, club.member.id, 0, type="banana")
    with pytest.raises(PermissionError):
        services.contribution.add(club.op2.id, club.member.id, 10)

    # 实物捐赠要写 material_desc，金额可以为 0
    material = services.contribution.add(
        club.president.id, club.member.id, 0, type="material",
        material_desc="PLA 1 卷", reward_quota=20)
    assert material.material_desc == "PLA 1 卷"


# ---------------------------------------------------------------------------
# 报表可见性
# ---------------------------------------------------------------------------

def test_reports_respect_permissions(services, club):
    # 普通社员只能看自己
    assert services.report.balance_of(club.member.id, club.member.id) == pytest.approx(200)
    with pytest.raises(PermissionError):
        services.report.balance_of(club.member.id, club.op2.id)

    # 全社额度报表只有社长 / 副社长
    assert len(services.report.quota_report(club.president.id)) == 4
    with pytest.raises(PermissionError):
        services.report.quota_report(club.op2.id)

    # 库存：运营2 能看（要选耗材记打印），人事不能
    assert services.report.stock_report(club.op2.id) == [(club.filament, 0.0)]
    with pytest.raises(PermissionError):
        services.report.stock_report(club.hr.id)

    # 经费只有社长 / 副社长
    with pytest.raises(PermissionError):
        services.report.fund_report(club.op2.id)


def test_staff_read_permissions(services, club):
    """人事要维护名册、运营2 要做打印统计，普通社员只能看自己。"""
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 5)

    assert [m.name for m in services.member.list_members(club.hr.id)]           # 人事：名册
    assert services.record.list_records(club.op2.id)                            # 运营2：打印记录
    assert services.report.stock_report(club.op2.id) is not None                # 运营2：库存

    # 普通社员不给 member_id 时只看到自己的记录
    own = services.record.list_records(club.member.id)
    assert [r.member_id for r in own] == [club.member.id]
    with pytest.raises(PermissionError):
        services.record.list_records(club.member.id, member_id=club.op2.id)

    # 谁都别想越过权限看经费 / 名册
    with pytest.raises(PermissionError):
        services.report.fund_report(club.hr.id)
    with pytest.raises(PermissionError):
        services.member.list_members(club.op2.id)


def test_member_statement_contains_records_and_quota(services, club):
    services.record.record_print(club.op2.id, club.member.id, club.filament.id, 20,
                                 date=date(2026, 9, 1))

    statement = services.report.member_statement(club.member.id, club.member.id)
    assert statement["member"].id == club.member.id
    assert statement["balance"] == pytest.approx(180)
    assert len(statement["records"]) == 1
    assert sorted(t.type for t in statement["quota"]) == ["init", "print"]

    with pytest.raises(PermissionError):
        services.report.member_statement(club.op2.id, club.member.id)   # 非本人且无 view_all
