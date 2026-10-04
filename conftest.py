"""pytest 共享 fixture（阶段 0.5 起本文件不再承担 sys.path 锚点，见 pytest.ini）。

阶段 1 新增：``db``（内存库 + 事务泄漏检查）与 ``services``（装配好的服务层）两个
fixture，供仓储层、服务层、CLI 的测试复用。
"""

import pytest

from infrastructure.db import Database


@pytest.fixture
def db():
    """内存库；测试结束时检查没有忘记退出的事务。"""
    database = Database(":memory:")
    yield database
    assert not database.in_transaction, "有测试/服务忘记退出 with db.transaction()"
    database.close()
