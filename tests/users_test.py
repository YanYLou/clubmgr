"""阶段 2.2：登录账号服务测试（权限、认证、改口令、停用）。"""

import pytest


def test_add_user_and_authenticate(services, club):
    user = services.user.add_user(club.president.id, "admin", "admin123",
                                  club.president.id)

    assert user.username == "admin"
    assert user.password_hash != "admin123"          # 不存明文

    found = services.user.authenticate("admin", "admin123")
    assert found is not None and found.id == user.id
    assert services.user.authenticate("admin", "wrong") is None
    assert services.user.authenticate("nobody", "admin123") is None


def test_add_user_validates_permission_and_input(services, club):
    with pytest.raises(PermissionError):
        services.user.add_user(club.op2.id, "op2user", "admin123", club.op2.id)

    with pytest.raises(ValueError):
        services.user.add_user(club.president.id, "ab", "admin123", club.president.id)

    with pytest.raises(ValueError):
        services.user.add_user(club.president.id, "hruser", "12345", club.hr.id)

    with pytest.raises(ValueError):
        services.user.add_user(club.president.id, "ghost", "admin123", 999)

    services.user.add_user(club.president.id, "hruser", "admin123", club.hr.id)
    with pytest.raises(ValueError):
        services.user.add_user(club.president.id, "hruser", "admin123", club.hr.id)


def test_set_password_by_self_and_by_admin(services, club):
    user = services.user.add_user(club.president.id, "zhangsan", "admin123",
                                  club.member.id)

    # 本人改自己的口令
    services.user.set_password(club.member.id, user.id, "newpass123")
    assert services.user.authenticate("zhangsan", "newpass123") is not None
    assert services.user.authenticate("zhangsan", "admin123") is None

    # 改别人的需要 manage_users 权限
    with pytest.raises(PermissionError):
        services.user.set_password(club.op2.id, user.id, "otherpass")
    services.user.set_password(club.president.id, user.id, "reset12345")
    assert services.user.authenticate("zhangsan", "reset12345") is not None


def test_disabled_user_cannot_authenticate(services, club):
    user = services.user.add_user(club.president.id, "tempuser", "admin123",
                                  club.member.id)
    assert services.user.authenticate("tempuser", "admin123") is not None

    services.user.disable(club.president.id, user.id)

    assert services.user.authenticate("tempuser", "admin123") is None
    assert services.user.get_user(user.id).status == "disabled"


def test_list_users_requires_permission(services, club):
    services.user.add_user(club.president.id, "admin", "admin123", club.president.id)

    assert [u.username for u in services.user.list_users(club.president.id)] == ["admin"]
    with pytest.raises(PermissionError):
        services.user.list_users(club.member.id)


def test_member_of_resolves_role_source(services, club):
    user = services.user.add_user(club.president.id, "admin", "admin123",
                                  club.president.id)
    member = services.user.member_of(user)
    assert member.id == club.president.id
    assert member.role.value == "president"
