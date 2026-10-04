"""阶段 1.2：权限矩阵测试。"""

import pytest

from domain.models import Role
from domain.permissions import ACTIONS, MATRIX, can, can_view_member, require


def test_president_and_vice_president_can_do_everything():
    for role in (Role.PRESIDENT, Role.VICE_PRESIDENT):
        for action in ACTIONS:
            assert can(role, action) is True, (role, action)


def test_every_role_can_view_own_data():
    for role in Role:
        assert can(role, "view_own") is True


@pytest.mark.parametrize(
    "role, allowed, denied",
    [
        (Role.OP1, "schedule", "write_record"),
        (Role.OP2, "write_record", "schedule"),
        (Role.HR, "edit_members", "write_record"),
        (Role.MEMBER, "view_own", "view_all"),
        (Role.OP2, "view_inventory", "view_funds"),      # 运营2 能看库存、看不到经费
        (Role.OP2, "view_records", "view_members"),      # 运营2 看打印记录、不看名册
        (Role.HR, "view_members", "view_records"),       # 人事看名册、不看打印记录
    ],
)
def test_role_specific_permissions(role, allowed, denied):
    assert can(role, allowed) is True
    assert can(role, denied) is False


def test_overdraft_is_limited_to_full_roles():
    """拍板结论：额度不足时只有社长 / 副社长能记。"""
    assert can(Role.PRESIDENT, "allow_overdraft") is True
    assert can(Role.VICE_PRESIDENT, "allow_overdraft") is True
    assert can(Role.OP2, "allow_overdraft") is False
    assert can(Role.HR, "allow_overdraft") is False
    assert can(Role.MEMBER, "allow_overdraft") is False


def test_require_raises_permission_error_with_action_name():
    require(Role.OP2, "write_record")                      # 有权限：不抛异常

    with pytest.raises(PermissionError) as excinfo:
        require(Role.MEMBER, "write_record")

    assert "write_record" in str(excinfo.value)


def test_unknown_action_is_a_programming_error():
    with pytest.raises(ValueError):
        can(Role.PRESIDENT, "no_such_action")


def test_matrix_covers_only_known_actions():
    assert set(MATRIX) == set(ACTIONS)
    assert all(isinstance(roles, frozenset) for roles in MATRIX.values())


def test_can_view_member_allows_self_and_view_all_roles():
    assert can_view_member(Role.MEMBER, 7, 7) is True          # 看自己
    assert can_view_member(Role.MEMBER, 7, 8) is False         # 看别人
    assert can_view_member(Role.PRESIDENT, 7, 8) is True       # 社长看谁都可以
    assert can_view_member(Role.OP2, 7, 8) is False
