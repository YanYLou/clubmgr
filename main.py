"""项目路径与数据库位置。

阶段 0.1 修正（本次改动）：
- ``ROOT_DIR`` 原来用了两层 ``dirname``，指到的是仓库的**父目录**
  （例如 ``E:\\clubmgr.worktrees``），导致 ``DB_PATH`` 落在仓库之外且目录不存在。
  现在改为 ``main.py`` 所在目录，即仓库根。
- 数据库文件统一为 ``data/club.db``：原来 ``main.py`` 写 ``data/data.db``，
  而 README 写 ``data/club.db``，两处不一致。
- 目录创建交给 ``infrastructure.db.Database``（连接前自动 mkdir），
  这里保留 :func:`ensure_data_dir` 供入口脚本显式调用。
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DOMAIN_DIR = ROOT_DIR / "domain"
DATA_DIR = ROOT_DIR / "data"

DB_FILENAME = "club.db"
DB_PATH = DATA_DIR / DB_FILENAME


def ensure_data_dir() -> Path:
    """确保 ``data/`` 目录存在并返回它（首次运行、备份脚本等入口可调用）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
