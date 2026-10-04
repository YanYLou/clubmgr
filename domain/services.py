"""业务逻辑与事务边界（阶段 1.3 实现）。

约定（README「设计约定」的落地）：

- 仓储只执行 SQL、不提交；**只有服务层**用 ``with db.transaction():`` 开事务，
  事务可嵌套（SAVEPOINT）。
- 每个写操作先校验操作人权限（:mod:`domain.permissions`），接口层不重复判断。
- 额度 / 库存 / 经费只写流水，余额永远是 ``SUM(amount)``，绝不直接改余额。
- 一次打印要同时写 ``records``、``quota_transactions``、``inventory_transactions``，
  三张表要么全成、要么全不成。

阶段 1 开工前拍板的结论：

- 额度不足时**允许透支**（余额可为负），但只有社长 / 副社长能记；
- 打印记录不记钱（``fee`` / ``is_charged`` 已从模型删除）；
- ``records.filament_id`` 是外键，``filament_name`` 只作历史快照。

本模块只依赖 ``domain.repositories`` 的抽象接口，不 import infrastructure。
"""

from dataclasses import dataclass, replace
from datetime import date
from typing import Sequence

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
from domain.permissions import can, can_view_member, require
from domain.repositories import (
    ContributionRepository,
    FilamentRepository,
    FundTransactionRepository,
    InventoryTransactionRepository,
    MemberRepository,
    QuotaTransactionRepository,
    RecordRepository,
    TransactionManager,
)

MEMBER_STATUSES = ("active", "left")
CONTRIBUTION_TYPES = ("money", "material")
_EDITABLE_MEMBER_FIELDS = frozenset(
    {"name", "qq", "student_id", "role", "status", "join_date", "note"}
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _today() -> date:
    """取今天。单独包一层，避免函数参数名 ``date`` 遮蔽 ``date`` 类型。"""
    return date.today()


def _positive(value, label: str) -> float:
    """转成正数，否则给出人话报错。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}必须是数字，收到 {value!r}") from None
    if number <= 0:
        raise ValueError(f"{label}必须大于 0，收到 {number!r}")
    return number


def _note_or_error(note: str | None, label: str) -> str:
    text = (note or "").strip()
    if not text:
        raise ValueError(f"{label}必须写备注（说明原因）")
    return text


class _Service:
    """服务层公共部分：持有事务边界与社员仓储，提供权限与存在性校验。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository) -> None:
        self.db = db
        self.member_repo = member_repo

    def _operator_only(self, operator_id: int) -> Member:
        """取出操作人（不校验权限，用于读取自己数据的场景）。"""
        operator = self.member_repo._get(operator_id)
        if operator is None:
            raise ValueError(f"操作人不存在: {operator_id}")
        return operator

    def _operator(self, operator_id: int, action: str) -> Member:
        """取出操作人并校验权限。"""
        operator = self._operator_only(operator_id)
        require(operator.role, action)
        return operator

    def _member(self, member_id: int) -> Member:
        member = self.member_repo._get(member_id)
        if member is None:
            raise ValueError(f"社员不存在: {member_id}")
        return member


def _require_filament(filament_repo: FilamentRepository, filament_id: int) -> Filament:
    filament = filament_repo._get(filament_id)
    if filament is None:
        raise ValueError(f"耗材不存在: {filament_id}")
    return filament


# ---------------------------------------------------------------------------
# 社员
# ---------------------------------------------------------------------------

class MemberService(_Service):
    """社员管理：空库引导、增改、退社。"""

    def bootstrap(self, name: str, *, qq: str | None = None,
                  student_id: str | None = None) -> Member:
        """空库初始化：创建第一个社长（只在库里还没有任何社员时可用）。"""
        if self.member_repo._list():
            raise RuntimeError("库里已经有社员了；bootstrap 只用于空库初始化")
        name = (name or "").strip()
        if not name:
            raise ValueError("社员姓名不能为空")
        with self.db.transaction():
            return self.member_repo._create(Member(
                name=name, qq=qq, student_id=student_id,
                role=Role.PRESIDENT, status="active"))

    def create_member(self, operator_id: int, name: str, *, qq: str | None = None,
                      student_id: str | None = None, role: Role | str = Role.MEMBER,
                      status: str = "active", join_date: date | None = None,
                      note: str | None = None) -> Member:
        self._operator(operator_id, "edit_members")
        name = (name or "").strip()
        if not name:
            raise ValueError("社员姓名不能为空")
        role = Role(role)
        if status not in MEMBER_STATUSES:
            raise ValueError(f"状态只能是 {MEMBER_STATUSES}，收到 {status!r}")
        if student_id is not None:
            existing = self.member_repo.find_by_student_id(student_id)
            if existing is not None:
                raise ValueError(f"学号 {student_id} 已被 {existing.name} 占用")
        with self.db.transaction():
            return self.member_repo._create(Member(
                name=name, qq=qq, student_id=student_id, role=role,
                status=status, join_date=join_date, note=note))

    def update_member(self, operator_id: int, member_id: int, **changes) -> Member:
        self._operator(operator_id, "edit_members")
        member = self._member(member_id)

        unknown = set(changes) - _EDITABLE_MEMBER_FIELDS
        if unknown:
            raise ValueError(f"不可修改的字段: {sorted(unknown)}")
        if "role" in changes:
            changes["role"] = Role(changes["role"])
        if "status" in changes and changes["status"] not in MEMBER_STATUSES:
            raise ValueError(f"状态只能是 {MEMBER_STATUSES}，收到 {changes['status']!r}")
        if "name" in changes:
            changes["name"] = (changes["name"] or "").strip()
            if not changes["name"]:
                raise ValueError("社员姓名不能为空")
        if changes.get("student_id") is not None:
            existing = self.member_repo.find_by_student_id(changes["student_id"])
            if existing is not None and existing.id != member_id:
                raise ValueError(f"学号 {changes['student_id']} 已被 {existing.name} 占用")

        updated = replace(member, **changes)
        with self.db.transaction():
            self.member_repo._update(updated)
        return updated

    def mark_left(self, operator_id: int, member_id: int) -> Member:
        """退社：只把 ``status`` 改成 left，历史记录全部保留。"""
        return self.update_member(operator_id, member_id, status="left")

    def get_member(self, operator_id: int, member_id: int) -> Member:
        operator = self._operator_only(operator_id)
        if not can_view_member(operator.role, operator.id, member_id):
            raise PermissionError(f"角色 {operator.role.value} 不能查看其他社员的信息")
        return self._member(member_id)

    def list_members(self, operator_id: int, *, status: str | None = None,
                     role: Role | str | None = None) -> list[Member]:
        self._operator(operator_id, "view_all")
        if role is not None:
            return self.member_repo.list_by_role(Role(role))
        if status is not None:
            return self.member_repo._list(status=status)
        return self.member_repo._list()


# ---------------------------------------------------------------------------
# 额度
# ---------------------------------------------------------------------------

class QuotaService(_Service):
    """额度：学期初发放、手工调整。永远写流水，不直接改余额。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 quota_repo: QuotaTransactionRepository) -> None:
        super().__init__(db, member_repo)
        self.quota_repo = quota_repo

    def init_semester(self, operator_id: int, amount: float, *,
                      member_ids: Sequence[int] | None = None,
                      date: date | None = None, note: str | None = None,
                      allow_repeat: bool = False) -> list[QuotaTransaction]:
        """学期初发放额度：给在社社员（或指定社员）各写一条 ``init`` 流水。"""
        self._operator(operator_id, "adjust_quota")
        amount = _positive(amount, "发放额度（克）")
        day = date or _today()
        targets = ([self._member(mid) for mid in member_ids] if member_ids
                   else self.member_repo.list_active())
        if not targets:
            raise ValueError("没有可发放额度的社员（在社社员为空）")

        if not allow_repeat:
            repeated = [m.name for m in targets if self.quota_repo.has_type(m.id, "init")]
            if repeated:
                raise RuntimeError(
                    "以下社员已经发过学期额度（init 流水），确实要再发请显式 "
                    f"allow_repeat=True，或用 adjust() 单笔调整：{', '.join(repeated)}")

        with self.db.transaction():
            return [self.quota_repo._create(QuotaTransaction(
                member_id=m.id, amount=amount, type="init", operator_id=operator_id,
                date=day, note=note or f"学期初发放 {amount:g} 克")) for m in targets]

    def adjust(self, operator_id: int, member_id: int, amount: float, note: str, *,
               date: date | None = None) -> QuotaTransaction:
        """手工调整额度（正数增加、负数扣减），必须写备注。"""
        self._operator(operator_id, "adjust_quota")
        self._member(member_id)
        if not amount:
            raise ValueError("调整数量不能为 0")
        text = _note_or_error(note, "手工调整额度")
        with self.db.transaction():
            return self.quota_repo._create(QuotaTransaction(
                member_id=member_id, amount=float(amount), type="manual_adjust",
                operator_id=operator_id, date=date or _today(), note=text))


# ---------------------------------------------------------------------------
# 打印记录
# ---------------------------------------------------------------------------

class RecordService(_Service):
    """打印记录：一次打印 = 打印记录 + 额度流水 + 库存流水，同事务。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 record_repo: RecordRepository, quota_repo: QuotaTransactionRepository,
                 filament_repo: FilamentRepository,
                 inventory_repo: InventoryTransactionRepository) -> None:
        super().__init__(db, member_repo)
        self.record_repo = record_repo
        self.quota_repo = quota_repo
        self.filament_repo = filament_repo
        self.inventory_repo = inventory_repo

    def record_print(self, operator_id: int, member_id: int, filament_id: int,
                     consumption: float, *, printer_name: str = "",
                     date: date | None = None,
                     comments: str | None = None) -> Record:
        """记录一次打印。

        额度不足（余额会变成负数）时只有社长 / 副社长能记 —— 拍板结论。
        库存允许出现负数：那通常意味着采购没入账，比拒绝记录更容易发现。
        """
        operator = self._operator(operator_id, "write_record")
        consumption = _positive(consumption, "消耗（克）")
        member = self._member(member_id)
        filament = _require_filament(self.filament_repo, filament_id)
        day = date or _today()

        with self.db.transaction():
            balance = self.quota_repo.balance_of(member.id)
            if balance - consumption < 0 and not can(operator.role, "allow_overdraft"):
                raise PermissionError(
                    f"{member.name} 剩余额度 {balance:g} 克，本次消耗 {consumption:g} 克；"
                    f"额度不足时只有社长/副社长能记账（当前角色 {operator.role.value}）")

            record = self.record_repo._create(Record(
                member_id=member.id, printer_name=printer_name,
                filament_id=filament.id, filament_name=filament.name,
                consumption=consumption, date=day, operator_id=operator.id,
                comments=comments))
            self.quota_repo._create(QuotaTransaction(
                member_id=member.id, amount=-consumption, type="print",
                related_record_id=record.id, operator_id=operator.id, date=day,
                note=f"打印记录 #{record.id}：{filament.name} {consumption:g} 克"))
            self.inventory_repo._create(InventoryTransaction(
                filament_id=filament.id, amount=-consumption, type="print",
                related_record_id=record.id, operator_id=operator.id, date=day,
                note=f"打印记录 #{record.id}"))
        return record

    def list_records(self, operator_id: int, *, member_id: int | None = None,
                     start: date | None = None, end: date | None = None) -> list[Record]:
        operator = self._operator_only(operator_id)
        if member_id is not None:
            if not can_view_member(operator.role, operator.id, member_id):
                raise PermissionError("只能查看自己的打印记录")
            return self.record_repo.list_by_member(member_id)
        require(operator.role, "view_all")
        if start is not None and end is not None:
            return self.record_repo.list_by_date_range(start, end)
        return self.record_repo._list()


# ---------------------------------------------------------------------------
# 耗材与库存
# ---------------------------------------------------------------------------

class FilamentService(_Service):
    """耗材目录与采购入库。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 filament_repo: FilamentRepository,
                 inventory_repo: InventoryTransactionRepository,
                 fund_repo: FundTransactionRepository) -> None:
        super().__init__(db, member_repo)
        self.filament_repo = filament_repo
        self.inventory_repo = inventory_repo
        self.fund_repo = fund_repo

    def create_filament(self, operator_id: int, name: str, *, material: str | None = None,
                        color: str | None = None, unit_price: float | None = None,
                        note: str | None = None) -> Filament:
        self._operator(operator_id, "purchase")
        name = (name or "").strip()
        if not name:
            raise ValueError("耗材名称不能为空")
        if self.filament_repo.find_by_name(name) is not None:
            raise ValueError(f"耗材已存在: {name}")
        if unit_price is not None and unit_price < 0:
            raise ValueError("单价不能为负")
        with self.db.transaction():
            return self.filament_repo._create(Filament(
                name=name, material=material, color=color,
                unit_price=unit_price, note=note))

    def purchase(self, operator_id: int, filament_id: int, grams: float,
                 total_cost: float = 0, *, date: date | None = None,
                 note: str | None = None) -> InventoryTransaction:
        """采购入库：库存 ``+grams``；``total_cost > 0`` 时同时写一条经费支出。

        金额为 0（捐赠、免费样品）时不写经费流水，避免 0 元噪音。
        """
        self._operator(operator_id, "purchase")
        grams = _positive(grams, "入库数量（克）")
        total_cost = float(total_cost or 0)
        if total_cost < 0:
            raise ValueError("采购金额不能为负")
        filament = _require_filament(self.filament_repo, filament_id)
        day = date or _today()

        with self.db.transaction():
            if total_cost > 0:
                self.fund_repo._create(FundTransaction(
                    amount=-total_cost, type="expense", operator_id=operator_id,
                    date=day, note=note or f"采购 {filament.name} {grams:g} 克"))
            return self.inventory_repo._create(InventoryTransaction(
                filament_id=filament.id, amount=grams, type="purchase",
                operator_id=operator_id, date=day, note=note))

    def list_filaments(self, operator_id: int) -> list[Filament]:
        self._operator(operator_id, "view_inventory")
        return self.filament_repo._list()


# ---------------------------------------------------------------------------
# 经费
# ---------------------------------------------------------------------------

class FundService(_Service):
    """经费收支（采购支出由 :class:`FilamentService` 写，其余在这里手工记账）。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 fund_repo: FundTransactionRepository) -> None:
        super().__init__(db, member_repo)
        self.fund_repo = fund_repo

    def income(self, operator_id: int, amount: float, *, date: date | None = None,
               note: str | None = None) -> FundTransaction:
        return self._record(operator_id, amount, "income", date, note)

    def expense(self, operator_id: int, amount: float, *, date: date | None = None,
                note: str | None = None) -> FundTransaction:
        return self._record(operator_id, amount, "expense", date, note)

    def _record(self, operator_id: int, amount: float, txn_type: str,
                day: date | None, note: str | None) -> FundTransaction:
        self._operator(operator_id, "manage_funds")
        amount = _positive(amount, "金额")
        text = _note_or_error(note, "经费流水")
        signed = amount if txn_type == "income" else -amount
        with self.db.transaction():
            return self.fund_repo._create(FundTransaction(
                amount=signed, type=txn_type, operator_id=operator_id,
                date=day or _today(), note=text))


# ---------------------------------------------------------------------------
# 贡献 / 捐款
# ---------------------------------------------------------------------------

class ContributionService(_Service):
    """贡献登记：记一条贡献，可选地奖励额度。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 contribution_repo: ContributionRepository,
                 quota_repo: QuotaTransactionRepository) -> None:
        super().__init__(db, member_repo)
        self.contribution_repo = contribution_repo
        self.quota_repo = quota_repo

    def add(self, operator_id: int, member_id: int, amount: float, *, type: str = "money",
            material_desc: str | None = None, reward_quota: float = 0,
            date: date | None = None, note: str | None = None) -> Contribution:
        self._operator(operator_id, "manage_funds")
        member = self._member(member_id)
        if type not in CONTRIBUTION_TYPES:
            raise ValueError(f"贡献类型只能是 {CONTRIBUTION_TYPES}，收到 {type!r}")
        amount = float(amount or 0)
        if amount < 0:
            raise ValueError("贡献金额不能为负")
        if type == "material" and not (material_desc or "").strip():
            raise ValueError("实物捐赠必须填写 material_desc")
        reward = float(reward_quota or 0)
        if reward < 0:
            raise ValueError("奖励额度不能为负")
        day = date or _today()

        with self.db.transaction():
            contribution = self.contribution_repo._create(Contribution(
                member_id=member.id, amount=amount, type=type,
                material_desc=material_desc, reward_quota=reward,
                date=day, operator_id=operator_id, note=note))
            if reward > 0:
                self.quota_repo._create(QuotaTransaction(
                    member_id=member.id, amount=reward, type="contribution_reward",
                    operator_id=operator_id, date=day,
                    note=note or f"贡献奖励（贡献 #{contribution.id}）"))
        return contribution


# ---------------------------------------------------------------------------
# 只读查询与报表
# ---------------------------------------------------------------------------

class ReportService(_Service):
    """额度单、库存、经费报表（只读，但同样校验权限）。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 record_repo: RecordRepository, quota_repo: QuotaTransactionRepository,
                 filament_repo: FilamentRepository,
                 inventory_repo: InventoryTransactionRepository,
                 fund_repo: FundTransactionRepository,
                 contribution_repo: ContributionRepository) -> None:
        super().__init__(db, member_repo)
        self.record_repo = record_repo
        self.quota_repo = quota_repo
        self.filament_repo = filament_repo
        self.inventory_repo = inventory_repo
        self.fund_repo = fund_repo
        self.contribution_repo = contribution_repo

    def balance_of(self, operator_id: int, member_id: int) -> float:
        operator = self._operator_only(operator_id)
        if not can_view_member(operator.role, operator.id, member_id):
            raise PermissionError("只能查看自己的额度")
        return self.quota_repo.balance_of(member_id)

    def stock_of(self, operator_id: int, filament_id: int) -> float:
        self._operator(operator_id, "view_inventory")
        return self.inventory_repo.stock_of(filament_id)

    def fund_balance(self, operator_id: int) -> float:
        self._operator(operator_id, "view_funds")
        return self.fund_repo.balance()

    def quota_report(self, operator_id: int) -> list[tuple[Member, float]]:
        """全社额度表： (社员, 剩余额度)。"""
        self._operator(operator_id, "view_all")
        return [(m, self.quota_repo.balance_of(m.id)) for m in self.member_repo.list_active()]

    def stock_report(self, operator_id: int) -> list[tuple[Filament, float]]:
        """耗材库存表： (耗材, 剩余克数)。"""
        self._operator(operator_id, "view_inventory")
        return [(f, self.inventory_repo.stock_of(f.id)) for f in self.filament_repo._list()]

    def fund_report(self, operator_id: int, *, start: date | None = None,
                    end: date | None = None) -> dict:
        self._operator(operator_id, "view_funds")
        if start is not None and end is not None:
            transactions = self.fund_repo.list_by_date_range(start, end)
        else:
            transactions = self.fund_repo._list()
        return {"balance": self.fund_repo.balance(), "transactions": transactions}

    def member_statement(self, operator_id: int, member_id: int) -> dict:
        """个人额度单：社员 + 余额 + 打印记录 + 额度流水 + 贡献记录。"""
        operator = self._operator_only(operator_id)
        if not can_view_member(operator.role, operator.id, member_id):
            raise PermissionError("只能查看自己的额度单")
        member = self._member(member_id)
        return {
            "member": member,
            "balance": self.quota_repo.balance_of(member.id),
            "records": self.record_repo.list_by_member(member.id),
            "quota": self.quota_repo.list_by_member(member.id),
            "contributions": self.contribution_repo.list_by_member(member.id),
        }


@dataclass(frozen=True)
class Services:
    """装配好的服务集合（由 ``main.build_services`` 构造）。"""

    member: MemberService
    quota: QuotaService
    record: RecordService
    filament: FilamentService
    fund: FundService
    contribution: ContributionService
    report: ReportService
