"""角色权限矩阵（阶段 1.2 新增）。

规则来自 README 的角色表与 ``docs/design-notes.md`` 的权限矩阵：

| 功能 | 社长/副社长 | 运营1 | 运营2 | 人事 | 普通社员 |
| --- | --- | --- | --- | --- | --- |
| 查看全社数据 | ✅ | | | | |
| 成员增改 / 退社 | ✅ | | | ✅ | |
| 预约安排 | ✅ | ✅ | | | |
| 打印记录 | ✅ | | ✅ | | |
| 耗材入库 / 采购 | ✅ | | | | |
| 经费管理 | ✅ | | | | |
| 额度调整 | ✅ | | | | |
| 查看自己的额度 / 记录 | ✅ | ✅ | ✅ | ✅ | ✅ |

另有两条业务拍板结论：

- 额度不足时**允许透支**，但只有社长 / 副社长能记（``allow_overdraft``）；
- ``records`` 不再记钱（``fee`` / ``is_charged`` 已删除），因此没有收费相关权限。

矩阵比设计文档多两个**读**权限：``view_inventory``（运营2 记打印时要先选耗材）与
``view_funds``（经费只给社长 / 副社长看）。

权限判断只在服务层做（``domain/services.py`` 调用 :func:`require`），接口层不重复判断。
"""

from domain.models import Role

FULL = frozenset({Role.PRESIDENT, Role.VICE_PRESIDENT})
EVERYONE = frozenset(Role)

MATRIX: dict[str, frozenset[Role]] = {
    "view_all":        FULL,                      # 查看全社数据与报表
    "edit_members":    FULL | {Role.HR},          # 成员增改 / 退社
    "schedule":        FULL | {Role.OP1},         # 预约安排（阶段 2 使用）
    "write_record":    FULL | {Role.OP2},         # 记录打印（含耗材出库）
    "allow_overdraft": FULL,                      # 额度不足时仍然记账
    "adjust_quota":    FULL,                      # 手工调整额度
    "purchase":        FULL,                      # 耗材入库 / 采购 / 新建耗材
    "manage_funds":    FULL,                      # 经费收支与贡献奖励
    "view_own":        EVERYONE,                  # 查看自己的额度与记录
    # 下面两个是阶段 1 新增的读权限：运营2 要选耗材才能记打印，所以能看耗材与库存；
    # 经费只给社长 / 副社长看。
    "view_inventory":  FULL | {Role.OP2},         # 耗材目录与库存
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
    return role in allowed


def require(role: Role, action: str) -> None:
    """没有权限就抛 ``PermissionError``；服务层统一用它做校验。"""
    if not can(role, action):
        raise PermissionError(f"角色 {Role(role).value} 没有 {action} 权限")


def can_view_member(role: Role, operator_id: int, target_member_id: int) -> bool:
    """能否查看某个社员的数据：本人，或拥有 ``view_all`` 权限。"""
    return operator_id == target_member_id or can(role, "view_all")
