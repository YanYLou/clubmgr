"""角色权限矩阵。

设计约定：
- 权限在哪里校验？在服务层（domain/services.py）每个写操作入口调用 require()。
- 本模块只负责"角色 -> 动作"的纯函数判断，不含业务逻辑；
- interfaces 层不感知权限，main.py 不感知权限。
"""

from enum import Enum

from domain.models import Role


class Action(str, Enum):
    VIEW_ALL = "view_all"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_RESERVATIONS = "manage_reservations"
    MANAGE_RECORDS = "manage_records"


# 权限矩阵：动作 -> 允许执行的角色集合
PERMISSION_MATRIX: dict[Action, frozenset[Role]] = {
    Action.VIEW_ALL: frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT}),
    Action.MANAGE_MEMBERS: frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT, Role.HR}),
    Action.MANAGE_RESERVATIONS: frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT, Role.OP1}),
    Action.MANAGE_RECORDS: frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT, Role.OP2}),
}


class PermissionDenied(Exception):
    """操作者角色无权执行该操作。"""


def as_role(role: Role | str) -> Role:
    """把字符串角色归一化成 Role 枚举（从数据库读出的 role 是 str）。"""
    return role if isinstance(role, Role) else Role(role)


def can(role: Role | str, action: Action) -> bool:
    """判断某角色是否拥有某动作的权限。"""
    return as_role(role) in PERMISSION_MATRIX.get(action, frozenset())


def require(role: Role | str, action: Action) -> None:
    """无权限时抛 PermissionDenied。"""
    if not can(role, action):
        raise PermissionDenied(f"角色 {as_role(role).value} 无权执行 {action.value}")
