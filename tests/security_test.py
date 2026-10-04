"""阶段 2.2：口令哈希测试。"""

import pytest

from domain.security import hash_password, verify_password


def test_hash_is_salted_and_verifiable():
    first = hash_password("admin123")
    second = hash_password("admin123")

    assert first != second                     # 同一口令 + 不同随机盐 → 不同哈希
    assert first.startswith("pbkdf2_sha256$")
    assert verify_password("admin123", first) is True
    assert verify_password("admin124", first) is False


def test_verify_rejects_malformed_or_empty_input():
    assert verify_password("x", "") is False
    assert verify_password("x", "not-a-hash") is False
    assert verify_password("", hash_password("admin123")) is False
    assert verify_password("whatever", "md5$1$aa$bb") is False


def test_hash_password_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")
