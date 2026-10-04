"""阶段 1.2 / 3.1：权限矩阵测试。

阶段 3.1 起的新规则：副社长分 1/2 号（只有 1 号有管理页）、新增 teacher（与社长同级）、
两位运营权限完全一致。
"""

import pytest

from domain.models import Role
from domain.permissions import (ACTIONS, ADMINS, FULL, MATRIX, OPS, can,
                                can_view_member, require)

FULL_ROLES = (Role.PRESIDENT, Role.VICE_PRESIDENT_1,
              Role.VICE_PRESIDENT_2, Role.TEACHER)
# 只给"管理页"那一档的动作：副社长2号没有
ADMIN_ACTIONS = ("manage_users", "manage_settings")
BUSINESS_ACTIONS = tuple(action for action in ACTIONS if action not in ADMIN_ACTIONS)


def test_full_roles_can_do_every_business_action():
    for role in FULL_ROLES:
        for action in BUSINESS_ACTIONS:
            assert can(role, action) is True, (role, action)


def test_admin_page_only_for_president_vp1_and_teacher():
    """拍板结论：管理页 / 账号页 / 全局配置只给社长、副社长1号、老师。"""
    assert set(ADMINS) == {Role.PRESIDENT, Role.VICE_PRESIDENT_1, Role.TEACHER}

    for action in ADMIN_ACTIONS:
        assert can(Role.PRESIDENT, action) is True, action
        assert can(Role.VICE_PRESIDENT_1, action) is True, action
        assert can(Role.TEACHER, action) is True, action
        assert can(Role.VICE_PRESIDENT_2, action) is False, action
        assert can(Role.OP1, action) is False, action
        assert can(Role.OP2, action) is False, action
        assert can(Role.HR, action) is False, action
        assert can(Role.MEMBER, action) is False, action


def test_teacher_has_president_level_permissions():
    for action in ACTIONS:
        assert can(Role.TEACHER, action) == can(Role.PRESIDENT, action), action


def test_both_operators_share_the_same_permissions():
    """两位运营权限完全一致（拍板结论）。"""
    assert set(OPS) == {Role.OP1, Role.OP2}
    for action in ACTIONS:
        assert can(Role.OP1, action) == can(Role.OP2, action), action

    for action in ("write_record", "review_reservation", "schedule",
                   "view_records", "view_inventory"):
        assert can(Role.OP1, action) is True, action
        assert can(Role.OP2, action) is True, action


def test_every_role_can_view_own_data():
    for role in Role:
        assert can(role, "view_own") is True


@pytest.mark.parametrize(
    "role, allowed, denied",
    [
        (Role.OP1, "write_record", "view_funds"),
        (Role.OP2, "review_reservation", "allow_overdraft"),
        (Role.HR, "edit_members", "write_record"),
        (Role.HR, "view_members", "view_funds"),
        (Role.MEMBER, "view_own", "view_all"),
        (Role.VICE_PRESIDENT_2, "view_funds", "manage_users"),
    ],
)
def test_role_specific_permissions(role, allowed, denied):
    assert can(role, allowed) is True
    assert can(role, denied) is False


def test_overdraft_is_limited_to_full_roles():
    """拍板结论：额度不足时只有社长 / 副社长 / 老师能记。"""
    for role in FULL_ROLES:
        assert can(role, "allow_overdraft") is True

    for role in (Role.OP1, Role.OP2, Role.HR, Role.MEMBER):
        assert can(role, "allow_overdraft") is False


def test_legacy_vice_president_maps_to_vp1():
    """旧数据里的 vice_president 当作副社长1号（兼容阶段 2.3 之前的库）。"""
    assert Role.parse("vice_president") is Role.VICE_PRESIDENT_1
    assert Role.parse("Vice_President") is Role.VICE_PRESIDENT_1
    assert Role.parse("president") is Role.PRESIDENT
    assert Role.parse(Role.TEACHER) is Role.TEACHER
    assert can("vice_president", "manage_users") is True


def test_require_raises_permission_error_with_action_name():
    require(Role.OP2, "write_record")                      # 有权限：不抛异常

    with pytest.raises(PermissionError) as excinfo:
        require(Role.MEMBER, "write_record")

    assert "write_record" in str(excinfo.value)


def test_unknown_action_is_a_programming_error():
    with pytest.raises(ValueError):
        can(Role.PRESIDENT, "no_such_action")


def test_matrix_structure():
    assert set(MATRIX) == set(ACTIONS)
    assert all(isinstance(roles, frozenset) for roles in MATRIX.values())
    assert FULL <= frozenset(Role)
    assert ADMINS <= FULL
    assert OPS <= frozenset(Role)


def test_can_view_member_allows_self_and_view_all_roles():
    assert can_view_member(Role.MEMBER, 7, 7) is True          # 看自己
    assert can_view_member(Role.MEMBER, 7, 8) is False         # 看别人
    assert can_view_member(Role.PRESIDENT, 7, 8) is True       # 社长看谁都可以
    assert can_view_member(Role.OP2, 7, 8) is False
