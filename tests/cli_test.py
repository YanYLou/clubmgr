"""阶段 2.1：CLI 测试（其中第一个用例就是阶段 1 的验收流程）。"""

import json

import pytest

from interfaces.cli import main as cli_main


@pytest.fixture
def cli(tmp_path, capsys):
    """``run(*argv)``：跑一次 CLI，断言退出码，返回对应的输出。"""
    db_path = tmp_path / "club.db"

    def run(*argv, expect_code=0):
        code = cli_main(["--db", str(db_path), *argv])
        captured = capsys.readouterr()
        assert code == expect_code, captured.err or captured.out
        return captured.out if expect_code == 0 else captured.err

    return run


def test_phase1_acceptance_via_cli(cli):
    """建社员 → 学期初发额度 → 记录打印 → 额度 / 库存 / 经费报表。"""
    assert "已创建社长" in cli("member", "bootstrap", "--name", "社长",
                              "--student-id", "10001")
    assert "已新增社员" in cli("--operator", "10001", "member", "add",
                              "--name", "张三", "--student-id", "10005")
    assert "已新增耗材" in cli("--operator", "10001", "filament", "add",
                              "--name", "PLA 白", "--unit-price", "0.1")
    assert "已给 2 人发放额度" in cli("--operator", "10001", "quota", "init",
                                     "--amount", "200")

    out = cli("--operator", "10001", "record", "print", "--member", "10005",
              "--filament", "PLA 白", "--grams", "42.5", "--printer", "P1")
    assert "已记录打印" in out

    out = cli("--operator", "10001", "report", "quota")
    assert "张三" in out
    assert "157.5" in out

    out = cli("--operator", "10001", "filament", "stock")
    assert "-42.5" in out

    out = cli("--operator", "10001", "report", "statement", "--member", "张三")
    assert "剩余额度 157.5 克" in out
    assert "打印记录" in out


def test_cli_surfaces_permission_and_lookup_errors(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "社员", "--student-id", "10005")

    err = cli("--operator", "10005", "quota", "init", "--amount", "200", expect_code=1)
    assert "权限" in err

    err = cli("--operator", "查无此人", "report", "quota", expect_code=1)
    assert "找不到操作人" in err

    err = cli("member", "add", "--name", "没写操作人", expect_code=1)
    assert "--operator" in err


def test_cli_json_output(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "quota", "init", "--amount", "200")

    payload = json.loads(cli("--json", "--operator", "10001", "report", "quota"))

    assert payload[0]["name"] == "社长"
    assert payload[0]["balance"] == 200


def test_cli_fund_purchase_and_contribution(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "filament", "add", "--name", "PLA 白")
    cli("--operator", "10001", "quota", "init", "--amount", "200")

    cli("--operator", "10001", "fund", "income", "--amount", "500", "--note", "会费")
    cli("--operator", "10001", "filament", "purchase", "--filament", "PLA 白",
        "--grams", "1000", "--cost", "150", "--note", "采购 1kg")

    assert "经费余额：350 元" in cli("--operator", "10001", "report", "fund")
    assert "1000" in cli("--operator", "10001", "filament", "stock")

    out = cli("--operator", "10001", "contribution", "add", "--member", "10001",
              "--amount", "100", "--reward-quota", "50", "--note", "捐赠耗材费")
    assert "奖励额度 50 克" in out
    assert "250" in cli("--operator", "10001", "quota", "balance")


def test_cli_member_lifecycle(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "李四",
        "--student-id", "10005", "--role", "op2")

    out = cli("--operator", "10001", "member", "list")
    assert "李四" in out and "op2" in out

    assert "已退社" in cli("--operator", "10001", "member", "left", "--member", "10005")
    out = cli("--operator", "10001", "member", "list", "--status", "left")
    assert "李四" in out


def test_cli_user_commands(cli):
    """阶段 2.2：账号管理命令（同时也是 Web 登录用的初始账号创建方式）。"""
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")

    out = cli("--operator", "10001", "user", "add", "--username", "admin",
              "--password", "admin123", "--member", "10001")
    assert "已创建账号 admin" in out

    out = cli("--operator", "10001", "user", "list")
    assert "admin" in out and "社长" in out and "president" in out

    out = cli("--operator", "10001", "user", "passwd",
              "--user", "admin", "--password", "newpass123")
    assert "已重置 admin 的口令" in out

    out = cli("--operator", "10001", "user", "disable", "--user", "admin")
    assert "已停用账号 admin" in out

    err = cli("--operator", "10001", "user", "add", "--username", "ab",
              "--password", "admin123", "--member", "10001", expect_code=1)
    assert "至少" in err


# ---------------------------------------------------------------------------
# 维护命令（阶段 2.4）
# ---------------------------------------------------------------------------

def test_cli_backup_and_list(cli, tmp_path):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")

    out = cli("backup")
    assert "已备份并校验通过" in out
    assert "club-" in out

    backups = list((tmp_path / "backups").glob("club-*.db"))
    assert len(backups) == 1

    out = cli("backup", "--list")
    assert "备份列表（1 份）" in out
    assert backups[0].name in out


def test_cli_backup_without_database(tmp_path, capsys):
    from interfaces.cli import main as cli_main

    code = cli_main(["--db", str(tmp_path / "nope.db"), "backup"])
    assert code == 1
    assert "数据库不存在" in capsys.readouterr().err


def test_cli_doctor_reports_healthy_database(cli, tmp_path):
    out = cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    assert out

    out = cli("doctor")
    assert "数据库正常" in out
    assert "结构版本" in out and "数据完整性" in out
    # 还没有登录账号 → 应该提示
    assert "没有任何登录账号" in out


def test_cli_doctor_flags_broken_schema(tmp_path, capsys):
    import sqlite3

    from interfaces.cli import main as cli_main

    db_path = tmp_path / "old.db"
    cli_main(["--db", str(db_path), "member", "bootstrap", "--name", "社长"])
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA user_version = 1")       # 假装是旧结构
    connection.close()
    capsys.readouterr()

    code = cli_main(["--db", str(db_path), "doctor"])

    assert code == 1
    out = capsys.readouterr().out
    assert "结构版本" in out and "异常" in out


# ---------------------------------------------------------------------------
# 预约（阶段 2.3）
# ---------------------------------------------------------------------------

def _club_for_reservations(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "张三", "--student-id", "10005")
    cli("--operator", "10001", "member", "add", "--name", "运营2",
        "--student-id", "10002", "--role", "op2")


def test_cli_reservation_flow(cli):
    _club_for_reservations(cli)

    # 谁都能提交
    out = cli("--operator", "10005", "reservation", "add",
              "--day", "wed", "--week", "2026-10-05")
    assert "已提交预约" in out and "pending" in out

    # 待审核队列：普通社员看不到，运维能看（显示姓名而不是 id）
    assert "权限" in cli("--operator", "10005", "reservation", "pending", expect_code=1)
    out = cli("--operator", "10002", "reservation", "pending")
    assert "张三" in out and "pending" in out and "周三" in out

    # 审核通过并排班
    out = cli("--operator", "10002", "reservation", "approve", "--id", "1")
    assert "排班序号 1" in out

    # 排班表（所有人可看）
    out = cli("--operator", "10005", "reservation", "schedule", "--week", "2026-10-05")
    assert "周三" in out and "张三" in out

    # 撤销后名额释放
    out = cli("--operator", "10005", "reservation", "cancel", "--id", "1")
    assert "已撤销预约" in out
    out = cli("--operator", "10005", "reservation", "mine")
    assert "cancelled" in out


def test_cli_reservation_reject_and_json(cli):
    _club_for_reservations(cli)
    cli("--operator", "10005", "reservation", "add", "--day", "mon", "--week", "2026-10-05")

    out = cli("--operator", "10001", "reservation", "reject", "--id", "1",
              "--note", "当天名额满了")
    assert "已驳回预约" in out and "当天名额满了" in out

    payload = json.loads(cli("--json", "--operator", "10001", "reservation",
                             "schedule", "--week", "2026-10-05"))
    assert payload["week_start"] == "2026-10-05"
    assert payload["days"]["mon"] == []            # 被驳回的不进排班表


# ---------------------------------------------------------------------------
# 通知与全局配置（阶段 3.2）
# ---------------------------------------------------------------------------

def test_cli_settings_and_low_stock_notification(cli):
    _club_for_reservations(cli)
    cli("--operator", "10001", "filament", "add", "--name", "PLA 白")
    cli("--operator", "10001", "quota", "init", "--amount", "200")

    # 阈值默认 100 克；这里显式设一次并确认能读回
    out = cli("--operator", "10001", "settings", "set",
              "--key", "low_stock_threshold", "--value", "100")
    assert "已更新配置" in out
    assert "低库存阈值：100 克" in cli("--operator", "10001", "settings", "show")

    # 入库 150 → 打印 90：跨过阈值 → 运营2 收到站内通知
    cli("--operator", "10001", "filament", "purchase",
        "--filament", "PLA 白", "--grams", "150")
    cli("--operator", "10002", "record", "print", "--member", "10005",
        "--filament", "PLA 白", "--grams", "90")

    out = cli("--operator", "10002", "notify", "list")
    assert "low_stock" in out and "只剩 60 克" in out and "未读 1 条" in out

    assert "已标记为已读" in cli("--operator", "10002", "notify", "read", "--id", "1")
    assert "未读 0 条" in cli("--operator", "10002", "notify", "list")

    # 体检也会提示低库存
    assert "低于低库存阈值" in cli("doctor")


def test_cli_settings_set_requires_admin(cli):
    _club_for_reservations(cli)

    err = cli("--operator", "10002", "settings", "set",
              "--key", "low_stock_threshold", "--value", "50", expect_code=1)
    assert "权限" in err


# ---------------------------------------------------------------------------
# 时间格排班（阶段 3.6）
# ---------------------------------------------------------------------------

def test_cli_schedule_flow(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "张三", "--student-id", "10005")
    cli("--operator", "10001", "member", "add", "--name", "运营1",
        "--student-id", "10006", "--role", "op1")
    for index in (1, 2, 3):
        cli("--operator", "10001", "printer", "add", "--name", f"打印机 {index}")

    # 默认格：周一 / 周三 / 周五，16:55–17:40，容量 = 可用打印机台数
    out = cli("--operator", "10006", "schedule", "week", "--week", "2026-10-05", "--ensure")
    assert "2026-10-05" in out and "周三" in out and "16:55-17:40" in out
    assert "0/3" in out and "空闲打印机：3 台" in out

    # 社员提交 → 运营审核 → 一键填充
    cli("--operator", "10005", "reservation", "add", "--day", "wed", "--week", "2026-10-05")
    cli("--operator", "10006", "reservation", "approve", "--id", "1")
    out = cli("--operator", "10006", "schedule", "fill", "--week", "2026-10-05")
    assert "排进 1 条" in out and "1. 张三" in out

    # 取出来再手工排回去
    out = cli("--operator", "10006", "schedule", "unassign", "--id", "1")
    assert "（空）" in out
    out = cli("--operator", "10006", "schedule", "assign", "--id", "1", "--slot", "2")
    assert "已把预约 #1 排进时间格 #2" in out and "1. 张三" in out

    # 停用周三那格 → 人变待重排
    out = cli("--operator", "10006", "schedule", "close", "--id", "2", "--note", "场地被占")
    assert "已停用时间格 #2" in out and "停用" in out
    assert "待重排" in cli("--operator", "10006", "reservation", "reschedule")

    # 启用后又可以排人（先重新通过审核）
    cli("--operator", "10006", "schedule", "open", "--id", "2")
    cli("--operator", "10006", "reservation", "approve", "--id", "1")
    out = cli("--operator", "10006", "schedule", "assign", "--id", "1", "--slot", "2")
    assert "1. 张三" in out

    payload = json.loads(cli("--json", "--operator", "10006", "schedule", "week",
                             "--week", "2026-10-05"))
    assert payload["available_printers"] == 3
    assert len(payload["slots"]) == 3
    assert payload["slots"][1]["assigned"][0]["member_name"] == "张三"


def test_cli_schedule_permission_and_validation(cli):
    _club_for_reservations(cli)
    cli("--operator", "10001", "printer", "add", "--name", "打印机 1")

    # 普通社员只能看，不能改
    err = cli("--operator", "10005", "schedule", "week", "--week", "2026-10-05",
              "--ensure", expect_code=1)
    assert "权限" in err

    cli("--operator", "10001", "schedule", "week", "--week", "2026-10-05", "--ensure")
    err = cli("--operator", "10001", "schedule", "add", "--date", "2026-10-08",
              "--start", "16:00", "--end", "15:00", expect_code=1)
    assert "结束时间" in err

    # 加一个周四的临时格
    out = cli("--operator", "10001", "schedule", "add", "--date", "2026-10-08",
              "--start", "13:00", "--end", "14:00", "--note", "临时加场")
    assert "已新增时间格" in out and "周四" in out and "临时加场" in out


# ---------------------------------------------------------------------------
# 自助注册（阶段 3.5）
# ---------------------------------------------------------------------------

def test_cli_signup_pending_approve(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "人事",
        "--student-id", "10010", "--role", "hr")
    cli("--operator", "10001", "member", "add", "--name", "张三", "--student-id", "10005")

    # 自助注册不需要 --operator（这是社员自己用的入口）
    out = cli("user", "signup", "--name", "李四", "--student-id", "10008",
              "--username", "lisi", "--password", "lisi123456", "--qq", "123456")
    assert "注册已提交" in out and "待人事审核" in out and "pending" in out

    out = cli("--operator", "10010", "user", "pending")
    assert "李四" in out and "10008" in out and "123456" in out

    # 通过之后账号是 active
    assert "已通过 李四" in cli("--operator", "10010", "user", "approve", "--id", "1")

    payload = json.loads(cli("--json", "--operator", "10001", "user", "list"))
    assert any(u["username"] == "lisi" and u["status"] == "active" for u in payload)
    assert cli("--operator", "10010", "user", "pending").count("李四") == 0


def test_cli_signup_reject_and_permission(cli):
    _club_for_reservations(cli)          # 社长 10001 / 张三 10005 / 运营2 10002
    cli("--operator", "10001", "member", "add", "--name", "人事",
        "--student-id", "10010", "--role", "hr")
    cli("user", "signup", "--name", "李四", "--student-id", "10008",
        "--username", "lisi", "--password", "lisi123456")

    # 普通社员与运营都不能审核注册
    err = cli("--operator", "10005", "user", "approve", "--id", "1", expect_code=1)
    assert "权限" in err
    err = cli("--operator", "10002", "user", "pending", expect_code=1)
    assert "权限" in err

    out = cli("--operator", "10010", "user", "reject", "--id", "1",
              "--note", "不是本校学生")
    assert "已驳回 李四" in out and "rejected" in out


# ---------------------------------------------------------------------------
# 打印机（阶段 3.3）
# ---------------------------------------------------------------------------

def test_cli_printer_flow(cli):
    cli("member", "bootstrap", "--name", "社长", "--student-id", "10001")
    cli("--operator", "10001", "member", "add", "--name", "王老师",
        "--student-id", "T001", "--role", "teacher")

    out = cli("--operator", "10001", "printer", "add", "--name", "打印机 1")
    assert "已新增打印机" in out and "空闲 1 台" in out

    out = cli("--operator", "T001", "printer", "use", "--id", "1",
              "--until", "2026-10-04 17:40", "--note", "打教具")
    assert "已标记使用中" in out and "使用中" in out

    out = cli("--operator", "10001", "printer", "maintain", "--id", "1",
              "--note", "喷头堵了")
    assert "已标记维修中" in out

    err = cli("--operator", "10001", "printer", "use", "--id", "1", expect_code=1)
    assert "正在维修" in err

    out = cli("--operator", "T001", "printer", "fixed", "--id", "1")
    assert "已修好" in out and "空闲 1 台" in out

    payload = json.loads(cli("--json", "--operator", "10001", "printer", "list"))
    assert payload["available"] == 1
    assert payload["printers"][0]["status"] == "idle"


