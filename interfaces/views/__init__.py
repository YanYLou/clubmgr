"""蓝图注册（阶段 2.2）。按领域切分，页面只调用服务层。"""

from interfaces.views.admin import bp as admin_bp
from interfaces.views.auth import bp as auth_bp
from interfaces.views.dashboard import bp as dashboard_bp
from interfaces.views.filaments import bp as filaments_bp
from interfaces.views.fund import bp as fund_bp
from interfaces.views.members import bp as members_bp
from interfaces.views.notifications import bp as notifications_bp
from interfaces.views.quota import bp as quota_bp
from interfaces.views.records import bp as records_bp
from interfaces.views.reservations import bp as reservations_bp
from interfaces.views.users import bp as users_bp

BLUEPRINTS = (
    auth_bp,
    dashboard_bp,
    members_bp,
    records_bp,
    filaments_bp,
    quota_bp,
    fund_bp,
    users_bp,
    admin_bp,
    reservations_bp,
    notifications_bp,
)


def register_blueprints(app) -> None:
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
