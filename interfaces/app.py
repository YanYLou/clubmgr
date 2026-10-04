"""Flask 应用工厂（阶段 2.2）。

两种等价启动方式：

    flask --app interfaces.app:create_app run --debug
    python main.py web --port 5000

设计要点：

- 页面只调用服务层；权限判断仍然全部在服务层，模板里只用 ``can()`` 隐藏入口。
- 会话里只放 ``user_id``；每个请求都按 id 重新取社员与角色，改了角色立刻生效。
- SQLite 连接只有一个、跨线程使用（``check_same_thread=False``），
  因此用一把锁把请求串行化 —— 社团这个规模，简单且不会踩并发的坑。
- 会话密钥优先取环境变量 ``CLUBMGR_SECRET_KEY``，否则在 ``data/secret_key``
  生成一个并复用（该文件已被 .gitignore 忽略）。
"""

import os
import secrets
import threading
from pathlib import Path

from flask import Flask

from infrastructure.db import Database
from main import DATA_DIR, DB_PATH, build_services


def _fmt_number(value) -> str:
    """模板里统一数字格式（200.0 → 200，42.5 → 42.5）。"""
    if value is None:
        return "-"
    return f"{float(value):g}"


def _secret_key() -> str:
    key = os.environ.get("CLUBMGR_SECRET_KEY")
    if key:
        return key

    path = Path(DATA_DIR) / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    key = secrets.token_hex(32)
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    return key


def create_app(db_path: str | Path | None = None,
               *, secret_key: str | None = None) -> Flask:
    """建应用：装配服务层、注册蓝图、挂上会话恢复与请求锁。"""
    app = Flask(__name__)
    app.secret_key = secret_key or _secret_key()
    app.config["DB_PATH"] = str(db_path or DB_PATH)
    app.config["SERVICES"] = build_services(
        Database(app.config["DB_PATH"], check_same_thread=False))

    from interfaces.views import register_blueprints
    from interfaces.views.common import can, load_session_identity

    register_blueprints(app)

    lock = threading.RLock()

    @app.before_request
    def _acquire_db_lock():
        lock.acquire()

    @app.teardown_request
    def _release_db_lock(exc=None):
        lock.release()

    app.before_request(load_session_identity)
    app.context_processor(lambda: {"can": can})
    app.jinja_env.filters["num"] = _fmt_number
    return app


if __name__ == "__main__":
    create_app().run(debug=True)
