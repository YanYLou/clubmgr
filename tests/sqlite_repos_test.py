"""阶段 1：具体仓储（7 个 SQLite 实现）的行为测试。

抽象接口在 ``domain/repositories.py``，实现在 ``infrastructure/repositories.py``。
这里只测仓储层的查询语义（余额/库存是 SUM，日期区间是闭区间等），
业务规则（权限、透支、事务联动）在 ``services_test.py`` 里测。
"""

from datetime import date
from types import SimpleNamespace

import pytest

from domain.models import (
    Contribution,
    Filament,
    FundTransaction,
    InventoryTransaction,
    Member,
    QuotaTransaction,
    Record,
    Role,
)
from infrastructure.repositories import (
    SQLiteContributionRepo,
    SQLiteFilamentRepo,
    SQLiteFundRepo,
    SQLiteInventoryRepo,
    SQLiteMemberRepo,
    SQLiteQuotaRepo,
    SQLiteRecordRepo,
)


@pytest.fixture
def repos(db):
    """7 个具体仓储共用同一个内存库。

    能构造出来本身就说明抽象接口都实现齐了（少一个抽象方法会 TypeError）。
    """
    return SimpleNamespace(
        db=db,
        member=SQLiteMemberRepo(db),
        record=SQLiteRecordRepo(db),
        quota=SQLiteQuotaRepo(db),
        filament=SQLiteFilamentRepo(db),
        inventory=SQLiteInventoryRepo(db),
        fund=SQLiteFundRepo(db),
        contribution=SQLiteContributionRepo(db),
    )


def test_member_lookup_helpers(repos):
    with repos.db.transaction():
        alice = repos.member._create(Member(name="Alice", student_id="10101", role=Role.OP2))
        repos.member._create(Member(name="Bob", status="left"))

    assert repos.member.find_by_student_id("10101").id == alice.id
    assert repos.member.find_by_student_name("Alice").id == alice.id
    assert repos.member.find_by_student_id("nope") is None
    assert [m.name for m in repos.member.list_by_role(Role.OP2)] == ["Alice"]
    assert [m.name for m in repos.member.list_active()] == ["Alice"]


def test_quota_balance_and_statement(repos):
    with repos.db.transaction():
        member = repos.member._create(Member(name="Alice"))
        repos.quota._create(QuotaTransaction(
            member_id=member.id, amount=200, type="init",
            operator_id=member.id, date=date(2026, 9, 1)))
        repos.quota._create(QuotaTransaction(
            member_id=member.id, amount=-42.5, type="print",
            operator_id=member.id, date=date(2026, 9, 2)))

    assert repos.quota.balance_of(member.id) == pytest.approx(157.5)
    assert repos.quota.balance_of(999) == 0.0            # 没有任何流水 = 0
    assert repos.quota.has_type(member.id, "init") is True
    assert repos.quota.has_type(member.id, "manual_adjust") is False
    assert [t.type for t in repos.quota.list_by_member(member.id)] == ["init", "print"]


def test_record_queries_by_member_and_date_range(repos):
    with repos.db.transaction():
        member = repos.member._create(Member(name="Alice"))
        filament = repos.filament._create(Filament(name="PLA 白", material="PLA"))
        for day, grams in ((date(2026, 9, 1), 10.0), (date(2026, 9, 3), 20.0)):
            repos.record._create(Record(
                member_id=member.id, printer_name="P1",
                filament_id=filament.id, filament_name=filament.name,
                consumption=grams, date=day, operator_id=member.id))

    assert len(repos.record.list_by_member(member.id)) == 2
    # 闭区间：9-02 ~ 9-05 只命中 9-03 那条
    assert [r.consumption for r in repos.record.list_by_date_range(date(2026, 9, 2), date(2026, 9, 5))] == [20.0]
    assert repos.record.list_by_date_range(date(2026, 9, 4), date(2026, 9, 5)) == []
    assert repos.filament.find_by_name("PLA 白").id == filament.id
    assert repos.filament.find_by_name("不存在") is None


def test_inventory_stock_and_fund_balance(repos):
    with repos.db.transaction():
        member = repos.member._create(Member(name="Alice"))
        filament = repos.filament._create(Filament(name="PLA 白"))
        repos.inventory._create(InventoryTransaction(
            filament_id=filament.id, amount=1000, type="purchase",
            operator_id=member.id, date=date(2026, 9, 1)))
        repos.inventory._create(InventoryTransaction(
            filament_id=filament.id, amount=-42.5, type="print",
            operator_id=member.id, date=date(2026, 9, 2)))
        repos.fund._create(FundTransaction(
            amount=500, type="income", operator_id=member.id, date=date(2026, 9, 1)))
        repos.fund._create(FundTransaction(
            amount=-120, type="expense", operator_id=member.id, date=date(2026, 9, 5)))
        repos.contribution._create(Contribution(
            member_id=member.id, amount=100, type="money", reward_quota=50,
            date=date(2026, 9, 1), operator_id=member.id))

    assert repos.inventory.stock_of(filament.id) == pytest.approx(957.5)
    assert repos.inventory.stock_of(999) == 0.0
    assert len(repos.inventory.list_by_filament(filament.id)) == 2

    assert repos.fund.balance() == pytest.approx(380.0)
    assert [t.amount for t in repos.fund.list_by_date_range(date(2026, 9, 2), date(2026, 9, 30))] == [-120.0]

    assert [c.amount for c in repos.contribution.list_by_member(member.id)] == [100.0]
    assert repos.contribution.list_by_member(999) == []
