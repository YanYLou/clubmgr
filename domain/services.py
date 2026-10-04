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
from datetime import date, datetime, timedelta
from typing import Sequence

from domain.models import (
    Contribution,
    Filament,
    FundTransaction,
    InventoryTransaction,
    Member,
    Notification,
    Printer,
    QuotaTransaction,
    Record,
    Reservation,
    Role,
    ScheduleSlot,
    Setting,
    User,
)
from domain.permissions import can, can_view_member, require
from domain.repositories import (
    ContributionRepository,
    FilamentRepository,
    FundTransactionRepository,
    InventoryTransactionRepository,
    MemberRepository,
    NotificationRepository,
    PrinterRepository,
    QuotaTransactionRepository,
    RecordRepository,
    ReservationRepository,
    ScheduleSlotRepository,
    SettingRepository,
    TransactionManager,
    UserRepository,
)
from domain.security import MIN_PASSWORD_LENGTH, hash_password, verify_password

MEMBER_STATUSES = ("active", "left", "pending", "rejected")
CONTRIBUTION_TYPES = ("money", "material")
ACTIVITY_DAYS = ("mon", "wed", "fri")
DAY_LABELS = {"mon": "周一", "wed": "周三", "fri": "周五"}
RESERVATION_STATUSES = ("pending", "approved", "rejected", "cancelled", "reschedule")
RESERVATION_STATUS_LABELS = {"pending": "待审核", "approved": "已通过",
                             "rejected": "已驳回", "cancelled": "已撤销",
                             "reschedule": "待重排"}
SETTING_LOW_STOCK = "low_stock_threshold"          # 全局配置键（阶段 3.2）
DEFAULT_LOW_STOCK_THRESHOLD = 100.0                # 默认低库存阈值（克）
PRINTER_STATUSES = ("idle", "in_use", "maintenance")          # 阶段 3.3
PRINTER_STATUS_LABELS = {"idle": "空闲", "in_use": "使用中", "maintenance": "维修中"}
DEFAULT_SLOT_START = "16:55"                                  # 阶段 3.6：默认时段
DEFAULT_SLOT_END = "17:40"
DEFAULT_ACTIVITY_WEEKDAYS = (0, 2, 4)                         # 周一 / 周三 / 周五
ACTIVITY_DAY_WEEKDAYS = {"mon": 0, "wed": 2, "fri": 4}        # 活动日 → 距周一的偏移
SLOT_STATUSES = ("open", "closed")
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_EDITABLE_MEMBER_FIELDS = frozenset(
    {"name", "qq", "student_id", "role", "status", "join_date", "note"}
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _today() -> date:
    """取今天。单独包一层，避免函数参数名 ``date`` 遮蔽 ``date`` 类型。"""
    return date.today()


def _week_start(value: date | None) -> date:
    """把任意日期归一到它所在周的周一；不传就用本周。"""
    day = value or date.today()
    return day - timedelta(days=day.weekday())


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


def _time_or_error(text: str | None, label: str) -> str:
    value = (text or "").strip()
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError:
        raise ValueError(
            f"{label}要写成 HH:MM，例如 16:55（收到 {text!r}）") from None
    return value


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
        role = Role.parse(role)
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
            changes["role"] = Role.parse(changes["role"])
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
        if not (can_view_member(operator.role, operator.id, member_id)
                or can(operator.role, "view_members")):
            raise PermissionError(f"角色 {operator.role.value} 不能查看其他社员的信息")
        return self._member(member_id)

    def find_by_token(self, token: str) -> Member | None:
        """按 id / 学号 / 姓名解析社员（CLI 定位操作人用，见 interfaces/cli.py）。"""
        token = (token or "").strip()
        if not token:
            return None
        if token.isdigit():
            found = self.member_repo._get(int(token))
            if found is not None:
                return found
        return (self.member_repo.find_by_student_id(token)
                or self.member_repo.find_by_student_name(token))

    def names_for(self, member_ids: Sequence[int]) -> dict[int, str]:
        """按 id 批量取姓名（排班表、预约列表、报表渲染用）。"""
        return self.member_repo.names_for(list(member_ids))

    def list_members(self, operator_id: int, *, status: str | None = None,
                     role: Role | str | None = None) -> list[Member]:
        self._operator(operator_id, "view_members")
        if role is not None:
            return self.member_repo.list_by_role(Role.parse(role))
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
                 inventory_repo: InventoryTransactionRepository,
                 alerts: "StockAlertService | None" = None) -> None:
        super().__init__(db, member_repo)
        self.record_repo = record_repo
        self.quota_repo = quota_repo
        self.filament_repo = filament_repo
        self.inventory_repo = inventory_repo
        self.alerts = alerts          # 阶段 3.2：出库后检查是否跨过低库存阈值

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
            stock_before = self.inventory_repo.stock_of(filament.id)
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
            if self.alerts is not None:
                # 跨过低库存阈值就给两位运营发通知（与打印同事务，失败一起回滚）
                self.alerts.after_outbound(filament.id, stock_before)
        return record

    def list_records(self, operator_id: int, *, member_id: int | None = None,
                     start: date | None = None, end: date | None = None) -> list[Record]:
        """打印记录：staff（运营2 / 社长 / 副社长）看全部，其他人默认看自己。"""
        operator = self._operator_only(operator_id)
        staff = can(operator.role, "view_records")
        if member_id is not None:
            if operator.id != member_id and not staff:
                raise PermissionError("只能查看自己的打印记录")
            return self.record_repo.list_by_member(member_id)
        if not staff:
            return self.record_repo.list_by_member(operator.id)
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

    def find_by_name(self, operator_id: int, name: str) -> Filament | None:
        """按名字精确查找耗材（阶段 3.2 新增；需要 view_inventory）。"""
        self._operator(operator_id, "view_inventory")
        return self.filament_repo.find_by_name(name)


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

# ---------------------------------------------------------------------------
# 全局配置、站内通知与余量告警（阶段 3.2）
# ---------------------------------------------------------------------------

class SettingsService(_Service):
    """全局配置（键值对）。目前只有低库存阈值一个键。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 setting_repo: SettingRepository) -> None:
        super().__init__(db, member_repo)
        self.setting_repo = setting_repo

    def get(self, key: str, default: str | None = None) -> str | None:
        """读配置（服务内部与只读展示用，不做权限校验）。"""
        setting = self.setting_repo.find_by_key(key)
        return setting.value if setting is not None else default

    def get_number(self, key: str, default: float) -> float:
        raw = self.get(key)
        try:
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    def set(self, operator_id: int, key: str, value, *,
            note: str | None = None) -> Setting:
        """写配置（需要 ``manage_settings``）。"""
        self._operator(operator_id, "manage_settings")
        key = (key or "").strip()
        if not key:
            raise ValueError("配置名不能为空")
        with self.db.transaction():
            return self.setting_repo.set_value(key, str(value), note=note)

    def all(self, operator_id: int) -> list[Setting]:
        self._operator(operator_id, "manage_settings")
        return self.setting_repo._list()

    def low_stock_threshold(self) -> float:
        """低库存阈值（克）；0 或负数表示关闭告警。"""
        return self.get_number(SETTING_LOW_STOCK, DEFAULT_LOW_STOCK_THRESHOLD)


class NotificationService(_Service):
    """站内通知：谁收到、读了没有。"""

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 notification_repo: NotificationRepository) -> None:
        super().__init__(db, member_repo)
        self.notification_repo = notification_repo

    def send(self, member_ids, *, type: str, title: str, body: str | None = None,
             ref: str | None = None) -> list[Notification]:
        """给指定社员发通知（服务内部调用，不做权限校验）。"""
        targets = sorted({int(member_id) for member_id in member_ids})
        if not targets:
            return []
        now = datetime.now()
        with self.db.transaction():
            return [self.notification_repo._create(Notification(
                member_id=member_id, type=type, title=title, body=body,
                ref=ref, created_at=now)) for member_id in targets]

    def send_to_roles(self, roles, *, type: str, title: str,
                      body: str | None = None, ref: str | None = None) -> list[Notification]:
        """按角色发给所有在社社员（例如"耗材快用完"发给两位运营）。"""
        wanted = {Role.parse(role) for role in roles}
        targets = [m.id for m in self.member_repo.list_active() if m.role in wanted]
        return self.send(targets, type=type, title=title, body=body, ref=ref)

    def list_for(self, operator_id: int, *,
                 unread_only: bool = False) -> list[Notification]:
        self._operator_only(operator_id)
        return self.notification_repo.list_by_member(operator_id, unread_only=unread_only)

    def unread_count(self, operator_id: int) -> int:
        self._operator_only(operator_id)
        return self.notification_repo.count_unread(operator_id)

    def has_unread_ref(self, ref: str) -> bool:
        return self.notification_repo.find_unread_by_ref(ref) is not None

    def mark_read(self, operator_id: int, notification_id: int) -> Notification:
        """标记已读：只能读自己的通知。"""
        self._operator_only(operator_id)
        notification = self.notification_repo._get(notification_id)
        if notification is None:
            raise ValueError(f"通知不存在: {notification_id}")
        if notification.member_id != operator_id:
            raise PermissionError("只能读自己的通知")
        if notification.read_at is not None:
            return notification

        updated = replace(notification, read_at=datetime.now())
        with self.db.transaction():
            self.notification_repo._update(updated)
        return updated

    def mark_all_read(self, operator_id: int) -> int:
        self._operator_only(operator_id)
        unread = self.notification_repo.list_by_member(operator_id, unread_only=True)
        now = datetime.now()
        with self.db.transaction():
            for notification in unread:
                self.notification_repo._update(replace(notification, read_at=now))
        return len(unread)


class StockAlertService(_Service):
    """耗材余量告警：出库跨过阈值时通知两位运营（op1 / op2，权限共享所以都发）。"""

    NOTIFY_ROLES = (Role.OP1, Role.OP2)

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 settings: SettingsService, inventory_repo: InventoryTransactionRepository,
                 filament_repo: FilamentRepository,
                 notifications: NotificationService) -> None:
        super().__init__(db, member_repo)
        self.settings = settings
        self.inventory_repo = inventory_repo
        self.filament_repo = filament_repo
        self.notifications = notifications

    def threshold(self) -> float:
        return self.settings.low_stock_threshold()

    def low_stock(self) -> list[tuple[Filament, float]]:
        """当前低于阈值的耗材（含剩余量）；阈值 <= 0 表示关闭告警。"""
        threshold = self.threshold()
        if threshold <= 0:
            return []
        return [(filament, self.inventory_repo.stock_of(filament.id))
                for filament in self.filament_repo._list()
                if self.inventory_repo.stock_of(filament.id) < threshold]

    def after_outbound(self, filament_id: int, stock_before: float) -> list[Notification]:
        """出库后调用：只有"从阈值之上掉到阈值之下"才发通知，避免重复刷屏。"""
        threshold = self.threshold()
        if threshold <= 0 or stock_before < threshold:
            return []

        stock_after = self.inventory_repo.stock_of(filament_id)
        if stock_after >= threshold:
            return []

        filament = self.filament_repo._get(filament_id)
        name = filament.name if filament is not None else f"#{filament_id}"
        ref = f"filament:{filament_id}"
        if self.notifications.has_unread_ref(ref):
            return []

        return self.notifications.send_to_roles(
            self.NOTIFY_ROLES, type="low_stock",
            title=f"耗材快用完了：{name} 只剩 {stock_after:g} 克",
            body=(f"低库存阈值 {threshold:g} 克；本次出库让库存从 {stock_before:g} 克降到 "
                  f"{stock_after:g} 克，记得安排采购。"),
            ref=ref,
        )


class PrinterService(_Service):
    """打印机状态（阶段 3.3）：谁在用、还有几台可用、哪台在维修。

    规则（按选择题确认的答案）：

    - 所有登录用户都能看（社员也要知道还有没有机器可用）；
    - **使用中 / 释放**：老师自己用、运营代记、社长副社长都可以（``manage_printers``）；
    - **维修中 / 修好**：社长、副社长、老师可以标（``repair_printers``），维修必须写原因；
    - 增删 / 改名机器也算管理操作（``repair_printers``）；
    - ``available_count()`` 给排班用：时间格容量 = 当时空闲的机器台数。
    """

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 printer_repo: PrinterRepository) -> None:
        super().__init__(db, member_repo)
        self.printer_repo = printer_repo

    # -- 查询 ---------------------------------------------------------------

    def list_printers(self, operator_id: int) -> list[Printer]:
        self._operator_only(operator_id)
        return self.printer_repo._list()

    def available_count(self, operator_id: int | None = None) -> int:
        """空闲机器台数；不传 operator_id 时不做权限校验（排班容量内部用）。"""
        if operator_id is not None:
            self._operator_only(operator_id)
        return self.printer_repo.count_by_status("idle")

    def summary(self, operator_id: int) -> dict:
        """给页面用：机器列表 + 谁在用 + 各状态台数。"""
        printers = self.list_printers(operator_id)
        return {
            "printers": printers,
            "names": self.member_repo.names_for(
                [p.used_by for p in printers if p.used_by is not None]),
            "available": sum(1 for p in printers if p.status == "idle"),
            "in_use": sum(1 for p in printers if p.status == "in_use"),
            "maintenance": sum(1 for p in printers if p.status == "maintenance"),
        }

    # -- 管理 ---------------------------------------------------------------

    def add_printer(self, operator_id: int, name: str, *, model: str | None = None,
                    note: str | None = None) -> Printer:
        operator = self._operator(operator_id, "repair_printers")
        name = (name or "").strip()
        if not name:
            raise ValueError("打印机名字不能为空")
        if self.printer_repo.find_by_name(name) is not None:
            raise ValueError(f"打印机已存在: {name}")
        with self.db.transaction():
            return self.printer_repo._create(Printer(
                name=name, model=model, status="idle", note=note,
                updated_at=datetime.now(), updated_by=operator.id))

    def update_printer(self, operator_id: int, printer_id: int, *,
                       name: str | None = None, model: str | None = None,
                       note: str | None = None) -> Printer:
        operator = self._operator(operator_id, "repair_printers")
        printer = self._printer(printer_id)
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("打印机名字不能为空")
            existing = self.printer_repo.find_by_name(name)
            if existing is not None and existing.id != printer_id:
                raise ValueError(f"打印机名字已被占用: {name}")

        updated = replace(
            printer,
            name=name if name is not None else printer.name,
            model=model if model is not None else printer.model,
            note=note if note is not None else printer.note,
            updated_at=datetime.now(), updated_by=operator.id)
        with self.db.transaction():
            self.printer_repo._update(updated)
        return updated

    def mark_in_use(self, operator_id: int, printer_id: int, *,
                    member_id: int | None = None,
                    expected_end: datetime | None = None,
                    note: str | None = None) -> Printer:
        """标记某台机器"使用中"（默认记在操作人自己名下，可代记）。"""
        operator = self._operator(operator_id, "manage_printers")
        printer = self._printer(printer_id)
        if printer.status == "maintenance":
            raise ValueError(f"{printer.name} 正在维修，先修好再用")

        user = self._member(member_id) if member_id is not None else operator
        updated = replace(printer, status="in_use", used_by=user.id,
                          expected_end=expected_end,
                          note=note if note is not None else printer.note,
                          updated_at=datetime.now(), updated_by=operator.id)
        with self.db.transaction():
            self.printer_repo._update(updated)
        return updated

    def release(self, operator_id: int, printer_id: int, *,
                note: str | None = None) -> Printer:
        """用完释放：回到空闲。"""
        operator = self._operator(operator_id, "manage_printers")
        printer = self._printer(printer_id)
        if printer.status != "in_use":
            raise ValueError(
                f"{printer.name} 当前是「{PRINTER_STATUS_LABELS[printer.status]}」，"
                f"只有使用中的机器能释放")

        updated = replace(printer, status="idle", used_by=None, expected_end=None,
                          note=note if note is not None else printer.note,
                          updated_at=datetime.now(), updated_by=operator.id)
        with self.db.transaction():
            self.printer_repo._update(updated)
        return updated

    def mark_maintenance(self, operator_id: int, printer_id: int, *,
                         note: str) -> Printer:
        """标记"维修中"（必须写原因）。"""
        operator = self._operator(operator_id, "repair_printers")
        text = _note_or_error(note, "标记维修")
        printer = self._printer(printer_id)

        updated = replace(printer, status="maintenance", used_by=None,
                          expected_end=None, note=text,
                          updated_at=datetime.now(), updated_by=operator.id)
        with self.db.transaction():
            self.printer_repo._update(updated)
        return updated

    def finish_maintenance(self, operator_id: int, printer_id: int, *,
                           note: str | None = None) -> Printer:
        """修好了：回到空闲。"""
        operator = self._operator(operator_id, "repair_printers")
        printer = self._printer(printer_id)
        if printer.status != "maintenance":
            raise ValueError(
                f"{printer.name} 当前是「{PRINTER_STATUS_LABELS[printer.status]}」，"
                f"只有维修中的机器能标记修好")

        updated = replace(printer, status="idle", note=note or printer.note,
                          updated_at=datetime.now(), updated_by=operator.id)
        with self.db.transaction():
            self.printer_repo._update(updated)
        return updated

    def _printer(self, printer_id: int) -> Printer:
        printer = self.printer_repo._get(printer_id)
        if printer is None:
            raise ValueError(f"打印机不存在: {printer_id}")
        return printer


class ScheduleService(_Service):
    """时间格排班（阶段 3.6）。

    规则（按选择题确认的答案）：

    - 默认每周一 / 三 / 五各一格 **16:55–17:40**，运营1 可以改时间、加格子、停用；
    - ``slot_date`` 是真实日期，"周三改周四"就是改日期；**改动日期或停用**会让那一格上的人
      变成"待重排"并收到通知（不自动平移，由人工重新安排）；
    - **容量**：格子上没写死容量（``capacity = 0``）时，按**当时可用打印机台数**算
      （3 台；在维修或被老师占用就少几台）；
    - 手工排人（``assign``）与一键填充（``auto_fill``）需要 ``schedule`` 权限
      （社长 / 副社长 / 老师 / 两位运营）；
    - 任何登录用户都能看这一周的时间格与里面的人（社员要知道自己排在哪一格）。
    """

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 slot_repo: ScheduleSlotRepository,
                 reservation_repo: ReservationRepository,
                 printers: PrinterService | None = None,
                 notifications: NotificationService | None = None) -> None:
        super().__init__(db, member_repo)
        self.slot_repo = slot_repo
        self.reservation_repo = reservation_repo
        self.printers = printers
        self.notifications = notifications

    # -- 容量 ---------------------------------------------------------------

    def available_printers(self) -> int:
        """当前空闲打印机台数（没接打印机服务时按 0 算）。"""
        return self.printers.available_count() if self.printers is not None else 0

    def capacity_of(self, slot: ScheduleSlot) -> int:
        """这一格能排几个人：写了容量就用它，否则按当时可用打印机台数。"""
        return slot.capacity if slot.capacity else self.available_printers()

    # -- 生成与查看 ---------------------------------------------------------

    def ensure_week(self, operator_id: int,
                    week_start: date | None = None) -> list[ScheduleSlot]:
        """按默认规则补齐这一周的时间格（幂等：已有的不重复建）。"""
        operator = self._operator(operator_id, "schedule")
        week = _week_start(week_start)
        existing = {slot.slot_date for slot in self.slot_repo.list_by_week(week)}

        created: list[ScheduleSlot] = []
        with self.db.transaction():
            for weekday in DEFAULT_ACTIVITY_WEEKDAYS:
                slot_date = week + timedelta(days=weekday)
                if slot_date in existing:
                    continue
                created.append(self.slot_repo._create(ScheduleSlot(
                    week_start=week, slot_date=slot_date,
                    start_time=DEFAULT_SLOT_START, end_time=DEFAULT_SLOT_END,
                    capacity=0, status="open", note="默认时段",
                    created_at=datetime.now(), created_by=operator.id)))
        return created

    def week_view(self, operator_id: int, week_start: date | None = None) -> dict:
        """这一周的时间格：每格排了谁、还剩几个位置、当时有几台打印机可用。"""
        self._operator_only(operator_id)
        week = _week_start(week_start)
        slots = self.slot_repo.list_by_week(week)
        reservations = self.reservation_repo.list_by_week(week)

        by_slot: dict[int, list[Reservation]] = {}
        for reservation in reservations:
            if reservation.slot_id is not None:
                by_slot.setdefault(reservation.slot_id, []).append(reservation)

        available = self.available_printers()
        items = []
        for slot in slots:
            assigned = sorted(by_slot.get(slot.id, []), key=lambda r: (r.order_no, r.id))
            capacity = slot.capacity or available
            items.append({
                "slot": slot,
                "weekday_label": WEEKDAY_LABELS[slot.slot_date.weekday()],
                "assigned": assigned,
                "capacity": capacity,
                "free": max(capacity - len(assigned), 0),
            })

        return {
            "week_start": week,
            "slots": items,
            "unassigned": [r for r in reservations
                           if r.status == "approved" and r.slot_id is None],
            "names": self.member_repo.names_for([r.member_id for r in reservations]),
            "available_printers": available,
        }

    # -- 时间格管理 ---------------------------------------------------------

    def add_slot(self, operator_id: int, *, slot_date: date, start_time: str,
                 end_time: str, capacity: int = 0,
                 note: str | None = None) -> ScheduleSlot:
        """临时加一格（例如补一个周四的时段）。"""
        operator = self._operator(operator_id, "schedule")
        start = _time_or_error(start_time, "开始时间")
        end = _time_or_error(end_time, "结束时间")
        if end <= start:
            raise ValueError(f"结束时间要晚于开始时间（{start} → {end}）")
        if capacity < 0:
            raise ValueError("容量不能为负（0 = 按当时可用打印机台数）")

        with self.db.transaction():
            return self.slot_repo._create(ScheduleSlot(
                week_start=_week_start(slot_date), slot_date=slot_date,
                start_time=start, end_time=end, capacity=capacity,
                status="open", note=note, created_at=datetime.now(),
                created_by=operator.id))

    def update_slot(self, operator_id: int, slot_id: int, *,
                    slot_date: date | None = None, start_time: str | None = None,
                    end_time: str | None = None, capacity: int | None = None,
                    note: str | None = None) -> ScheduleSlot:
        """改时间 / 改日期 / 改容量。**改日期**会把这一格上的人标成"待重排"并通知他们。"""
        operator = self._operator(operator_id, "schedule")
        slot = self._slot(slot_id)

        new_date = slot_date or slot.slot_date
        new_start = _time_or_error(start_time, "开始时间") if start_time else slot.start_time
        new_end = _time_or_error(end_time, "结束时间") if end_time else slot.end_time
        if new_end <= new_start:
            raise ValueError(f"结束时间要晚于开始时间（{new_start} → {new_end}）")
        if capacity is not None and capacity < 0:
            raise ValueError("容量不能为负（0 = 按当时可用打印机台数）")

        date_changed = new_date != slot.slot_date
        assigned = self.reservation_repo.list_by_slot(slot.id)
        now = datetime.now()

        updated = replace(slot, slot_date=new_date, week_start=_week_start(new_date),
                          start_time=new_start, end_time=new_end,
                          capacity=capacity if capacity is not None else slot.capacity,
                          note=note if note is not None else slot.note)
        with self.db.transaction():
            self.slot_repo._update(updated)
            if date_changed:
                self._release_assignments(
                    assigned, reason=(f"活动日从 {slot.slot_date}（{WEEKDAY_LABELS[slot.slot_date.weekday()]}）"
                                      f"改到 {new_date}（{WEEKDAY_LABELS[new_date.weekday()]}）"))
        return updated

    def close_slot(self, operator_id: int, slot_id: int, *,
                   note: str | None = None) -> ScheduleSlot:
        """停用一格（当天不开放）：格子上的人变成"待重排"并收到通知。"""
        operator = self._operator(operator_id, "schedule")
        slot = self._slot(slot_id)
        assigned = self.reservation_repo.list_by_slot(slot.id)
        reason = (note or "").strip() or "这一格被停用"

        updated = replace(slot, status="closed", note=reason)
        with self.db.transaction():
            self.slot_repo._update(updated)
            self._release_assignments(assigned, reason=reason)
        return updated

    def reopen_slot(self, operator_id: int, slot_id: int, *,
                    note: str | None = None) -> ScheduleSlot:
        operator = self._operator(operator_id, "schedule")
        slot = self._slot(slot_id)
        updated = replace(slot, status="open", note=note or slot.note)
        with self.db.transaction():
            self.slot_repo._update(updated)
        return updated

    # -- 排人 ---------------------------------------------------------------

    def assign(self, operator_id: int, reservation_id: int,
               slot_id: int) -> Reservation:
        """把一条**已通过**的预约排进某个时间格（校验容量与"同一天同一人一条"）。"""
        self._operator(operator_id, "schedule")
        reservation = self._reservation(reservation_id)
        slot = self._slot(slot_id)

        if reservation.status != "approved":
            raise ValueError(
                f"只有已通过的预约能排进时间格（这条是 {reservation.status}）；"
                f"待重排的请先重新审核通过")
        if slot.status != "open":
            raise ValueError(f"{slot.slot_date} {slot.start_time} 这一格已停用")
        if reservation.week_start != slot.week_start:
            raise ValueError("预约与时间格不在同一周")

        assigned = self.reservation_repo.list_by_slot(slot.id)
        if any(item.id == reservation.id for item in assigned):
            return reservation                       # 已经在这一格，幂等
        capacity = self.capacity_of(slot)
        if len(assigned) >= capacity:
            raise ValueError(
                f"{slot.slot_date} {slot.start_time}-{slot.end_time} 已排满"
                f"（{len(assigned)}/{capacity}）")
        self._check_same_day(reservation, slot)

        updated = replace(reservation, slot_id=slot.id)
        with self.db.transaction():
            self.reservation_repo._update(updated)
        return updated

    def unassign(self, operator_id: int, reservation_id: int) -> Reservation:
        """把某人从时间格里拿出来（还在排班表里，只是没指定格子）。"""
        self._operator(operator_id, "schedule")
        reservation = self._reservation(reservation_id)
        if reservation.slot_id is None:
            return reservation
        updated = replace(reservation, slot_id=None)
        with self.db.transaction():
            self.reservation_repo._update(updated)
        return updated

    def auto_fill(self, operator_id: int, week_start: date | None = None, *,
                  slot_date: date | None = None) -> dict:
        """一键填充：把这一周"已通过但没排格子"的预约按顺序填进空格子。

        优先填到与它活动日相同的那一天；那天没格子或排满了，再按时间顺序找别的格子。
        """
        self._operator(operator_id, "schedule")
        week = _week_start(week_start)
        self.ensure_week(operator_id, week)

        slots = [slot for slot in self.slot_repo.list_by_week(week)
                 if slot.status == "open" and (slot_date is None or slot.slot_date == slot_date)]
        if not slots:
            return {"week_start": week, "assigned": [], "skipped": [], "reason": "本周没有可用的时间格"}

        counts = {slot.id: len(self.reservation_repo.list_by_slot(slot.id)) for slot in slots}
        capacities = {slot.id: self.capacity_of(slot) for slot in slots}

        order = {day: index for index, day in enumerate(ACTIVITY_DAYS)}
        waiting = sorted(
            (r for r in self.reservation_repo.list_by_week(week)
             if r.status == "approved" and r.slot_id is None),
            key=lambda r: (order.get(r.activity_day, 99), r.order_no or 0, r.id))

        assigned, skipped = [], []
        for reservation in waiting:
            target = self._pick_slot(slots, counts, capacities, reservation, week)
            if target is None:
                skipped.append(reservation)
                continue
            self.assign(operator_id, reservation.id, target.id)
            counts[target.id] += 1
            assigned.append(reservation)

        return {"week_start": week, "assigned": assigned, "skipped": skipped}

    # -- 内部 ---------------------------------------------------------------

    def _pick_slot(self, slots, counts, capacities, reservation,
                   week: date) -> ScheduleSlot | None:
        offset = ACTIVITY_DAY_WEEKDAYS.get(reservation.activity_day)
        wanted_date = week + timedelta(days=offset) if offset is not None else None

        candidates = [slot for slot in slots if slot.slot_date == wanted_date] + \
                     [slot for slot in slots if slot.slot_date != wanted_date]
        for slot in candidates:
            if counts[slot.id] >= capacities[slot.id]:
                continue
            if self._same_day_taken(reservation, slot):
                continue
            return slot
        return None

    def _check_same_day(self, reservation: Reservation, slot: ScheduleSlot) -> None:
        if self._same_day_taken(reservation, slot):
            raise ValueError(
                f"该社员 {slot.slot_date} 已经在别的时间格里排过了（同一天只能一条）")

    def _same_day_taken(self, reservation: Reservation, slot: ScheduleSlot) -> bool:
        for other in self.reservation_repo.list_by_week(slot.week_start):
            if other.id == reservation.id or other.slot_id is None:
                continue
            if other.member_id != reservation.member_id:
                continue
            other_slot = self.slot_repo._get(other.slot_id)
            if other_slot is not None and other_slot.slot_date == slot.slot_date:
                return True
        return False

    def _release_assignments(self, reservations, *, reason: str) -> None:
        """把受影响的人退回"待重排"并通知（活动日变动 / 停用格子）。"""
        now = datetime.now()
        for reservation in reservations:
            self.reservation_repo._update(replace(
                reservation, status="reschedule", slot_id=None,
                urgent_reason=reason, urgent_at=now))
            if self.notifications is not None:
                self.notifications.send(
                    [reservation.member_id], type="slot_changed",
                    title=f"你的排班要重新安排（{reservation.week_start}）",
                    body=f"{reason}；请重新选时间，运营会帮你重排。",
                    ref=f"reservation:{reservation.id}")

    def _slot(self, slot_id: int) -> ScheduleSlot:
        slot = self.slot_repo._get(slot_id)
        if slot is None:
            raise ValueError(f"时间格不存在: {slot_id}")
        return slot

    def _reservation(self, reservation_id: int) -> Reservation:
        reservation = self.reservation_repo._get(reservation_id)
        if reservation is None:
            raise ValueError(f"预约不存在: {reservation_id}")
        return reservation


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

    def contributions_report(self, operator_id: int, *, start: date | None = None,
                             end: date | None = None) -> list[Contribution]:
        """贡献名单（阶段 2.5 新增，公示用）。"""
        self._operator(operator_id, "view_all")
        if start is not None and end is not None:
            return self.contribution_repo.list_by_date_range(start, end)
        return self.contribution_repo._list()

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


# ---------------------------------------------------------------------------
# 登录账号（阶段 2.2）
# ---------------------------------------------------------------------------

class UserService(_Service):
    """登录账号：认证、开户、改口令、停用。

    账号只负责"证明你是哪个社员"，权限仍然取自该社员的 ``role``，
    因此所有业务权限判断都复用同一套权限矩阵。
    """

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 user_repo: UserRepository) -> None:
        super().__init__(db, member_repo)
        self.user_repo = user_repo

    def authenticate(self, username: str, password: str) -> User | None:
        """校验账号口令，成功返回 User，失败返回 None（登录入口，不做权限校验）。"""
        user = self.user_repo.find_by_username((username or "").strip())
        if user is None or user.status != "active":
            return None
        if not verify_password(password or "", user.password_hash):
            return None
        return user

    def get_user(self, user_id: int) -> User | None:
        """按 id 取账号（Web 会话恢复用）。"""
        return self.user_repo._get(user_id)

    def login_problem(self, username: str, password: str) -> str | None:
        """口令对但登不进去时，给出具体原因（阶段 3.5：待审核 / 被驳回 / 被停用）。"""
        user = self.user_repo.find_by_username((username or "").strip())
        if user is None or not verify_password(password or "", user.password_hash):
            return None
        if user.status == "pending":
            return "账号还在等待人事审核，通过后就能登录"
        if user.status == "rejected":
            return "这次注册被驳回了，请联系人事"
        if user.status == "disabled":
            return "账号已被停用，请联系社长"
        return None

    def find_user(self, token: str) -> User | None:
        """按账号名 / id 解析账号（CLI 用）。"""
        token = (token or "").strip()
        if not token:
            return None
        if token.isdigit():
            found = self.user_repo._get(int(token))
            if found is not None:
                return found
        return self.user_repo.find_by_username(token)

    def member_of(self, user: User) -> Member | None:
        """账号对应的社员，角色从这里取。"""
        return self.member_repo._get(user.member_id)

    def add_user(self, operator_id: int, username: str, password: str,
                 member_id: int, *, note: str | None = None) -> User:
        self._operator(operator_id, "manage_users")
        member = self._member(member_id)
        username = (username or "").strip()
        if len(username) < 3:
            raise ValueError("账号名至少 3 个字符")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"口令至少 {MIN_PASSWORD_LENGTH} 位")
        if self.user_repo.find_by_username(username) is not None:
            raise ValueError(f"账号已存在: {username}")
        with self.db.transaction():
            return self.user_repo._create(User(
                username=username, password_hash=hash_password(password),
                member_id=member.id, status="active", note=note))

    def set_password(self, operator_id: int, user_id: int, new_password: str) -> User:
        """改口令：本人可改自己的，改别人的需要 manage_users 权限。"""
        operator = self._operator_only(operator_id)
        user = self.user_repo._get(user_id)
        if user is None:
            raise ValueError(f"账号不存在: {user_id}")
        if user.member_id != operator.id:
            require(operator.role, "manage_users")
        if len(new_password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"口令至少 {MIN_PASSWORD_LENGTH} 位")
        updated = replace(user, password_hash=hash_password(new_password))
        with self.db.transaction():
            self.user_repo._update(updated)
        return updated

    def disable(self, operator_id: int, user_id: int) -> User:
        """停用账号（不删除，保留审计线索）。"""
        self._operator(operator_id, "manage_users")
        user = self.user_repo._get(user_id)
        if user is None:
            raise ValueError(f"账号不存在: {user_id}")
        updated = replace(user, status="disabled")
        with self.db.transaction():
            self.user_repo._update(updated)
        return updated

    def list_users(self, operator_id: int) -> list[User]:
        self._operator(operator_id, "manage_users")
        return self.user_repo._list()

    # -- 自助注册（阶段 3.5）-------------------------------------------------

    def signup(self, *, name: str, student_id: str, username: str, password: str,
               qq: str | None = None, note: str | None = None) -> tuple[Member, User]:
        """社员自助注册：同时建"待审核"的社员与账号，等人事审核通过。

        这个入口对所有人开放（不需要 operator），所以校验从严：姓名 / 学号 / 账号 / 口令都必填，
        学号与账号名都不能和已有的重复；审核前**不能登录**。
        """
        name = (name or "").strip()
        student_id = (student_id or "").strip()
        username = (username or "").strip()
        if not name:
            raise ValueError("姓名不能为空")
        if not student_id:
            raise ValueError("学号不能为空")
        if len(username) < 3:
            raise ValueError("账号名至少 3 个字符")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"口令至少 {MIN_PASSWORD_LENGTH} 位")

        existing = self.member_repo.find_by_student_id(student_id)
        if existing is not None:
            raise ValueError(
                f"学号 {student_id} 已经在名册里（{existing.name}）；如果是你本人，"
                f"请联系人事帮你开通账号")
        if self.user_repo.find_by_username(username) is not None:
            raise ValueError(f"账号已存在: {username}")

        with self.db.transaction():
            member = self.member_repo._create(Member(
                name=name, qq=qq, student_id=student_id, role=Role.MEMBER,
                status="pending", join_date=_today(),
                note=note or "自助注册"))
            user = self.user_repo._create(User(
                username=username, password_hash=hash_password(password),
                member_id=member.id, status="pending", note="等待人事审核"))
        return member, user

    def pending_signups(self, operator_id: int) -> list[tuple[User, Member]]:
        """待审核的注册列表（需要 ``approve_signup``）。"""
        self._operator(operator_id, "approve_signup")
        result: list[tuple[User, Member]] = []
        for user in self.user_repo.list_by_status("pending"):
            member = self.member_repo._get(user.member_id)
            if member is not None:
                result.append((user, member))
        return result

    def approve_signup(self, operator_id: int, user_id: int) -> tuple[User, Member]:
        """通过注册：社员与账号一起转成 active，之后就能登录了。"""
        operator = self._operator(operator_id, "approve_signup")
        user, member = self._signup(user_id)
        with self.db.transaction():
            updated_member = replace(member, status="active")
            self.member_repo._update(updated_member)
            updated_user = replace(user, status="active",
                                   note=f"注册已通过（审核人：{operator.name}）")
            self.user_repo._update(updated_user)
        return updated_user, updated_member

    def reject_signup(self, operator_id: int, user_id: int, *,
                      note: str | None = None) -> tuple[User, Member]:
        """驳回注册：社员与账号都标成 rejected（保留记录，方便回查）。"""
        operator = self._operator(operator_id, "approve_signup")
        user, member = self._signup(user_id)
        text = (note or "").strip() or "注册被驳回"
        with self.db.transaction():
            updated_member = replace(member, status="rejected",
                                     note=f"{text}（审核人：{operator.name}）")
            self.member_repo._update(updated_member)
            updated_user = replace(user, status="rejected", note=text)
            self.user_repo._update(updated_user)
        return updated_user, updated_member

    def _signup(self, user_id: int) -> tuple[User, Member]:
        user = self.user_repo._get(user_id)
        if user is None:
            raise ValueError(f"账号不存在: {user_id}")
        if user.status != "pending":
            raise ValueError(f"账号 {user.username} 不是待审核状态（当前 {user.status}）")
        member = self.member_repo._get(user.member_id)
        if member is None:
            raise ValueError(f"账号 {user.username} 没有关联社员")
        return user, member


# ---------------------------------------------------------------------------
# 预约（阶段 2.3）
# ---------------------------------------------------------------------------

class ReservationService(_Service):
    """预约：谁都能提交（``pending``），审核通过后才进排班表（``approved``）。

    与用户确认过的规则：

    - **提交不设限**：任何社员都能为自己提交任意多条预约（同一天重复提交只拦"已有一条
      待审核"的情况，避免误点两次）；
    - **只有社长 / 副社长 / 运维（op1、op2）能审核**（权限 ``review_reservation``）；
      通过时分配排班序号，同日同人只能有一条已通过（数据库部分唯一索引兜底）；
    - 提交人可以撤销自己的待审核 / 已通过预约，撤销后名额释放；
    - 排班表（已通过的预约）所有登录用户都能看；
    - **紧急任务**（阶段 3.4）：社长 / 副社长 / 运维可以把预约**提到本周并插到最前面**
      （当天其他人自动后移并收到通知），也可以**挤掉**某条已通过的排班
      （那条变成"待重排"并通知本人）；两种操作都留痕（谁、为什么、什么时候）。
    """

    def __init__(self, db: TransactionManager, member_repo: MemberRepository,
                 reservation_repo: ReservationRepository,
                 notifications: NotificationService | None = None) -> None:
        super().__init__(db, member_repo)
        self.reservation_repo = reservation_repo
        self.notifications = notifications

    # -- 提交 ---------------------------------------------------------------

    def create(self, operator_id: int, *, activity_day: str,
               week_start: date | None = None, member_id: int | None = None,
               note: str | None = None) -> Reservation:
        """提交一条预约（默认给自己；替别人提交需要 ``schedule`` 权限）。"""
        operator = self._operator_only(operator_id)
        target = self._member(member_id) if member_id is not None else operator
        if target.id != operator.id:
            require(operator.role, "schedule")

        day = (activity_day or "").strip().lower()
        if day not in ACTIVITY_DAYS:
            raise ValueError(f"活动日只能是 {ACTIVITY_DAYS}，收到 {activity_day!r}")
        week = _week_start(week_start)

        if self.reservation_repo.find_pending(week, day, target.id) is not None:
            raise ValueError(
                f"{target.name} 对 {week}（{DAY_LABELS[day]}）已有一条待审核的预约，"
                f"等审核结果或先撤销它")

        with self.db.transaction():
            return self.reservation_repo._create(Reservation(
                member_id=target.id, week_start=week, activity_day=day,
                order_no=0, status="pending", operator_id=operator.id, note=note))

    # -- 审核 ---------------------------------------------------------------

    def review(self, operator_id: int, reservation_id: int, *, approve: bool = True,
               note: str | None = None, order_no: int | None = None) -> Reservation:
        """审核：通过与驳回。通过会分配排班序号并进入排班表。"""
        operator = self._operator(operator_id, "review_reservation")
        reservation = self._reservation(reservation_id)
        if reservation.status not in ("pending", "reschedule"):
            raise ValueError(
                f"只有待审核 / 待重排的预约能审核，这条当前是 {reservation.status}")

        if approve:
            existing = self.reservation_repo.find_approved(
                reservation.week_start, reservation.activity_day, reservation.member_id)
            if existing is not None:
                raise ValueError(
                    f"该社员在这一天已经有排班（预约 #{existing.id}，序号 "
                    f"{existing.order_no}），不能重复通过")
            sequence = order_no or self.reservation_repo.next_order_no(
                reservation.week_start, reservation.activity_day)
            if sequence <= 0:
                raise ValueError("排班序号必须大于 0")
            updated = replace(reservation, status="approved", order_no=sequence,
                              reviewer_id=operator.id, reviewed_at=datetime.now(),
                              note=note or reservation.note)
        else:
            updated = replace(reservation, status="rejected", order_no=0,
                              reviewer_id=operator.id, reviewed_at=datetime.now(),
                              note=note or reservation.note)

        with self.db.transaction():
            self.reservation_repo._update(updated)
        return updated

    def reject(self, operator_id: int, reservation_id: int, *,
               note: str | None = None) -> Reservation:
        """驳回（``review(approve=False)`` 的语义化写法）。"""
        return self.review(operator_id, reservation_id, approve=False, note=note)

    # -- 撤销 ---------------------------------------------------------------

    def cancel(self, operator_id: int, reservation_id: int, *,
               note: str | None = None) -> Reservation:
        """撤销预约：本人随时可以撤；撤别人的需要审核权限。"""
        operator = self._operator_only(operator_id)
        reservation = self._reservation(reservation_id)
        if reservation.status not in ("pending", "approved", "reschedule"):
            raise ValueError(
                f"只有待审核 / 已通过 / 待重排的预约能撤销，这条是 {reservation.status}")
        if reservation.member_id != operator.id:
            require(operator.role, "review_reservation")

        updated = replace(reservation, status="cancelled", order_no=0,
                          reviewer_id=operator.id, reviewed_at=datetime.now(),
                          note=note or reservation.note)
        with self.db.transaction():
            self.reservation_repo._update(updated)
        return updated

    # -- 紧急任务（阶段 3.4）-------------------------------------------------

    def pull_to_this_week(self, operator_id: int, reservation_id: int, *,
                          week_start: date | None = None,
                          activity_day: str | None = None,
                          note: str, order_no: int | None = None) -> Reservation:
        """紧急任务：把某条预约提到本周（或指定周）并插到最前面。

        - 允许 pending / approved / 待重排 的预约；
        - 目标活动日默认沿用原来的活动日；
        - 该社员在目标日若已有**另一条**已通过的排班 → 拒绝；
        - 插队 = 序号 1，当天其他已通过的预约整体后移一位并逐个收到通知；
        - 留痕：urgent_by / urgent_reason / urgent_at。
        """
        operator = self._operator(operator_id, "urgent_reservation")
        text = _note_or_error(note, "紧急提前")
        reservation = self._reservation(reservation_id)
        if reservation.status not in ("pending", "approved", "reschedule"):
            raise ValueError(f"当前状态不能提前：{reservation.status}")

        week = _week_start(week_start)
        day = (activity_day or reservation.activity_day or "").strip().lower()
        if day not in ACTIVITY_DAYS:
            raise ValueError(f"活动日只能是 {ACTIVITY_DAYS}，收到 {activity_day!r}")

        conflict = self.reservation_repo.find_approved(week, day, reservation.member_id)
        if conflict is not None and conflict.id != reservation.id:
            raise ValueError(
                f"该社员在 {week}（{DAY_LABELS[day]}）已经有排班 #{conflict.id}")

        sequence = order_no or 1
        if sequence <= 0:
            raise ValueError("排班序号必须大于 0")

        others = [r for r in self.reservation_repo.list_by_week(week)
                  if r.activity_day == day and r.status == "approved"
                  and r.id != reservation.id]
        shifted = [r for r in others if r.order_no >= sequence]

        now = datetime.now()
        with self.db.transaction():
            for other in shifted:
                self.reservation_repo._update(
                    replace(other, order_no=other.order_no + 1))

            updated = replace(reservation, week_start=week, activity_day=day,
                              status="approved", order_no=sequence,
                              reviewer_id=operator.id, reviewed_at=now,
                              urgent_by=operator.id, urgent_reason=text,
                              urgent_at=now)
            self.reservation_repo._update(updated)

            if self.notifications is not None:
                for other in shifted:
                    self.notifications.send(
                        [other.member_id], type="reservation_shifted",
                        title=f"你的排班顺序被顺延了（{week} {DAY_LABELS[day]}）",
                        body=f"因为紧急任务：{text}；新的序号见排班表。",
                        ref=f"reservation:{other.id}")
                self.notifications.send(
                    [reservation.member_id], type="reservation_urgent",
                    title=f"你的预约被紧急提前（{week} {DAY_LABELS[day]} 序号 {sequence}）",
                    body=f"原因：{text}",
                    ref=f"reservation:{reservation.id}")
        return updated

    def bump(self, operator_id: int, reservation_id: int, *, note: str) -> Reservation:
        """挤掉别人：把一条已通过的排班退回"待重排"并通知本人（留痕）。"""
        operator = self._operator(operator_id, "urgent_reservation")
        text = _note_or_error(note, "挤掉排班")
        reservation = self._reservation(reservation_id)
        if reservation.status != "approved":
            raise ValueError(f"只有已通过的排班能挤掉，当前是 {reservation.status}")

        now = datetime.now()
        updated = replace(reservation, status="reschedule", order_no=0,
                          reviewer_id=operator.id, reviewed_at=now,
                          urgent_by=operator.id, urgent_reason=text, urgent_at=now)
        with self.db.transaction():
            self.reservation_repo._update(updated)
            if self.notifications is not None:
                self.notifications.send(
                    [reservation.member_id], type="reservation_bumped",
                    title=(f"你的排班被紧急任务占用了（{reservation.week_start} "
                           f"{DAY_LABELS.get(reservation.activity_day, reservation.activity_day)}）"),
                    body=f"原因：{text}。可以重新选时间，运营会帮你重排。",
                    ref=f"reservation:{reservation.id}")
        return updated

    def reschedule_list(self, operator_id: int) -> list[Reservation]:
        """待重排列表（需要审核权限）。"""
        self._operator(operator_id, "review_reservation")
        return self.reservation_repo.list_by_status("reschedule")

    # -- 查询 ---------------------------------------------------------------

    def schedule(self, operator_id: int, *, week_start: date | None = None) -> dict:
        """排班表：只含已通过的预约，按活动日分组、按序号排列。所有登录用户可看。"""
        self._operator_only(operator_id)
        week = _week_start(week_start)
        approved = self.reservation_repo.list_by_status("approved", week_start=week)
        return {
            "week_start": week,
            "days": [(day, [r for r in approved if r.activity_day == day])
                     for day in ACTIVITY_DAYS],
            "names": self.member_repo.names_for([r.member_id for r in approved]),
        }

    def pending(self, operator_id: int) -> list[Reservation]:
        """待审核队列（需要审核权限）。"""
        self._operator(operator_id, "review_reservation")
        return self.reservation_repo.list_by_status("pending")

    def mine(self, operator_id: int, *, member_id: int | None = None) -> list[Reservation]:
        """我的预约（看别人的需要审核权限）。"""
        operator = self._operator_only(operator_id)
        target = self._member(member_id) if member_id is not None else operator
        if target.id != operator.id:
            require(operator.role, "review_reservation")
        return self.reservation_repo.list_by_member(target.id)

    def _reservation(self, reservation_id: int) -> Reservation:
        reservation = self.reservation_repo._get(reservation_id)
        if reservation is None:
            raise ValueError(f"预约不存在: {reservation_id}")
        return reservation


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
    user: UserService
    reservation: ReservationService
    settings: SettingsService
    notification: NotificationService
    stock_alert: StockAlertService
    printer: PrinterService
    schedule: ScheduleService
