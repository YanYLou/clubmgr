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


