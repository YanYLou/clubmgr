"""口令哈希与校验（阶段 2.2 新增，只用标准库）。

存储格式：``pbkdf2_sha256$<迭代次数>$<盐 hex>$<哈希 hex>``，
每人独立随机盐，校验用 :func:`hmac.compare_digest` 做定时安全比较。

不用 werkzeug 的 ``generate_password_hash`` 是为了把"口令怎么存"这件事留在
domain 里（且不引入额外依赖）；将来换算法只需改本文件并把版本段换掉。
"""

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 6


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """把明文口令变成可入库的字符串。"""
    if not password:
        raise ValueError("口令不能为空")
    salt = secrets.token_hex(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
    )
    return f"{ALGORITHM}${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令；``stored`` 格式不对时返回 False（不抛异常）。"""
    if not password or not stored:
        return False
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)
