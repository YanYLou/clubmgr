"""角色权限矩阵。

角色（阶段 3.1 起，按选择题确认的答案改过）：

| 角色 | 说明 |
| --- | --- |
| ``president`` | 社长：全部权限 |
| ``vice_president_1`` | 副社长1号：全部业务权限 **+ 管理页 / 账号页** |
| ``vice_president_2`` | 副社长2号：全部业务权限，但**没有**管理页权限 |
| ``teacher`` | 社团老师：权限与社长同级（含管理页） |
| ``op1`` / ``op2`` | 两位运营：**权限完全一致**（记打印、审核预约、排班、看库存与打印记录） |
| ``hr`` | 人事：成员增改 / 退社 / 看名册 |
| ``member`` | 普通社员：只看自己的额度与记录、自己提交预约 |

| 动作 | 社长 | 副社1 | 副社2 | 老师 | 运营1/2 | 人事 | 社员 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| view_all（全社数据与报表） | ✅ | ✅ | ✅ | ✅ | | | |
| view_funds（经费） | ✅ | ✅ | ✅ | ✅ | | | |
| edit_members / view_members | ✅ | ✅ | ✅ | ✅ | | ✅ | |
| schedule（替别人排/录预约） | ✅ | ✅ | ✅ | ✅ | ✅ | | |
| review_reservation（审核预约） | ✅ | ✅ | ✅ | ✅ | ✅ | | |
| write_record / view_records | ✅ | ✅ | ✅ | ✅ | ✅ | | |
| view_inventory（耗材库存） | ✅ | ✅ | ✅ | ✅ | ✅ | | |
| allow_overdraft / adjust_quota | ✅ | ✅ | ✅ | ✅ | | | |
| purchase / manage_funds | ✅ | ✅ | ✅ | ✅ | | | |
| **manage_users（管理页 / 账号页）** | ✅ | ✅ | | ✅ | | | |
| view_own（自己的额度与记录） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

三条业务拍板结论：

- 额度不足时**允许透支**（余额可为负），但只有社长 / 副社长 / 老师能记（``allow_overdraft``）；
- 管理页 / 账号页只给**社长、副社长1号、老师**（``manage_users``）；
- **两位运营权限完全一致**（都归到 :data:`OPS`），保留两个角色名只是为了统计"谁做的"。

权限判断只在服务层做（``domain/services.py`` 调用 :func:`require`），接口层不重复判断。
"""

from domain.models import Role

# 最高权限一档：社长 + 副社长（1、2 号）+ 老师
FULL = frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT_1,
                  Role.VICE_PRESIDENT_2, Role.TEACHER})
# 管理页 / 账号页：社长 + 副社长1号 + 老师（副社长2号没有）
ADMINS = frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT_1, Role.TEACHER})
# 两位运营权限完全一致
OPS = frozenset({Role.OP1, Role.OP2})
EVERYONE = frozenset(Role)

MATRIX: dict[str, frozenset[Role]] = {
    "view_all":        FULL,                      # 查看全社数据与报表
    "edit_members":    FULL | {Role.HR},          # 成员增改 / 退社
    "schedule":        FULL | OPS,                # 预约安排（替别人提交 / 排进时间格）
    "review_reservation": FULL | OPS,             # 审核预约
    "write_record":    FULL | OPS,                # 记录打印（含耗材出库）
    "allow_overdraft": FULL,                      # 额度不足时仍然记账
    "adjust_quota":    FULL,                      # 手工调整额度
    "purchase":        FULL,                      # 耗材入库 / 采购 / 新建耗材
    "manage_funds":    FULL,                      # 经费收支与贡献奖励
    "manage_users":    ADMINS,                    # 登录账号管理 + Web 维护页
    "manage_settings": ADMINS,                    # 全局配置（低库存阈值等，阶段 3.2）
    "manage_printers": FULL | OPS,                # 标记打印机使用中 / 释放（阶段 3.3）
    "repair_printers": FULL,                      # 标记维修中 / 修好、增删机器（阶段 3.3）
    "view_own":        EVERYONE,                  # 查看自己的额度与记录
    # 读权限：不同角色要干的活不同
    "view_members":    FULL | {Role.HR},          # 社员名册
    "view_records":    FULL | OPS,                # 打印记录列表与统计
    "view_inventory":  FULL | OPS,                # 耗材目录与库存
    "view_funds":      FULL,                      # 经费余额与流水
}

ACTIONS = tuple(MATRIX)


def can(role: Role, action: str) -> bool:
    """``role`` 是否拥有 ``action`` 权限。

    动作名拼错时直接抛 ``ValueError``，避免"静默无权限"这种难查的 bug。
    """
    try:
        allowed = MATRIX[action]
    except KeyError:
        raise ValueError(
            f"未知权限动作: {action!r}（可用动作: {', '.join(ACTIONS)}）"
        ) from None
    return Role.parse(role) in allowed


def require(role: Role, action: str) -> None:
    """没有权限就抛 ``PermissionError``；服务层统一用它做校验。"""
    if not can(role, action):
        raise PermissionError(f"角色 {Role.parse(role).value} 没有 {action} 权限")


def can_view_member(role: Role, operator_id: int, target_member_id: int) -> bool:
    """能否查看某个社员的数据：本人，或拥有 ``view_all`` 权限。"""
    return operator_id == target_member_id or can(role, "view_all")
