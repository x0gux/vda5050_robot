"""T7 검증: 고장주입 엔진 + 정책 반응."""
import threading
import time

from app.battery import BatteryModel
from app.battery import manage_low_battery_warning
from app.faults import FaultEngine
from app.instant_actions import handle_instant_action
from app.order_runner import OrderRunner
from app.safeplc.base import SafeContext, Vec
from app.safeplc.reference import ReferenceSafePolicy
from app.state_machine import RobotState


def make_env():
    rs = RobotState()
    battery = BatteryModel(level=80.0, drain_pct_per_min=0.0)
    core = {"order_id": "", "order_update_id": 0, "last_node_id": None,
            "last_node_sequence_id": 0, "x": 0.0, "y": 0.0, "theta": 0.0,
            "estop_active": False, "obstacle_active": False, "comm_loss_until": 0}
    lock = threading.Lock()
    runner = OrderRunner(rs, action_duration_s=0.1, battery=battery)
    engine = FaultEngine(core=core, core_lock=lock, robot_state=rs,
                         battery=battery, runner=runner)
    return rs, battery, core, lock, runner, engine


def test_inject_obstacle_sets_flag_then_auto_clears():
    rs, battery, core, lock, runner, engine = make_env()
    engine.inject("obstacle", 0.3)
    with lock:
        assert core["obstacle_active"] is True
    time.sleep(0.5)
    with lock:
        assert core["obstacle_active"] is False    # duration 경과 후 자동 해제


def test_sto_warning_error_level_and_auto_clear():
    rs, battery, core, lock, runner, engine = make_env()
    engine.inject("sto_warning", 0.3)
    assert rs.has_error("STO")
    sto = [e for e in rs.errors if e["errorType"] == "STO"][0]
    assert sto["errorLevel"] == "WARNING"
    assert sto["errorReference"] == "0x207"
    # STO는 정지가 아니라 절반 속도 — 정책 반응 확인
    verdict = ReferenceSafePolicy().evaluate(SafeContext(
        position=Vec(0, 0), speed_requested=1.0, estop_active=False,
        obstacle_active=False, comm_ok=True, inside_zones=[],
        errors_active=["STO"]))
    assert verdict.allow_move is True
    assert verdict.max_speed_mps == 0.5
    time.sleep(0.5)
    assert not rs.has_error("STO")                 # 자동 해제


def test_drive_error_blocks_policy_then_recovers():
    rs, battery, core, lock, runner, engine = make_env()
    engine.inject("drive_error", 0.3)
    drive = [e for e in rs.errors if e["errorType"] == "DriveFault"][0]
    assert drive["errorLevel"] == "ERROR"
    assert drive["errorReference"] == "DRV-002"
    verdict = ReferenceSafePolicy().evaluate(SafeContext(
        position=Vec(0, 0), speed_requested=1.0, estop_active=False,
        obstacle_active=False, comm_ok=True, inside_zones=[],
        errors_active=["DriveFault"]))
    assert verdict.allow_move is False             # ERROR → 주행 차단
    time.sleep(0.5)
    assert not rs.has_error("DriveFault")          # 복구


def test_comm_loss_window_and_resume():
    rs, battery, core, lock, runner, engine = make_env()
    before = time.monotonic()
    engine.inject("comm_loss", 0.4)
    with lock:
        assert core["comm_loss_until"] > before    # 발행 억제 창 열림
    time.sleep(0.6)
    with lock:
        assert core["comm_loss_until"] == 0        # 창 닫힘 (복구 마커 발행은 mqtt_client가 있을 때)


def test_low_battery_forces_level_and_restores():
    rs, battery, core, lock, runner, engine = make_env()
    engine.inject("low_battery", 0.4)
    assert battery.level == 12.0
    manage_low_battery_warning(rs, battery, 20.0)
    assert rs.has_error("BatteryLow")              # 저전압 경고 발생
    time.sleep(0.6)
    assert battery.level == 80.0                   # 원래 값 복원
    manage_low_battery_warning(rs, battery, 20.0)
    assert not rs.has_error("BatteryLow")


def test_clear_all_resets_faults_but_keeps_estop():
    rs, battery, core, lock, runner, engine = make_env()
    handle_instant_action(
        {"actionType": "faxEStop", "actionId": "e1",
         "actionParameters": [{"key": "activate", "value": True}]},
        runner, core, lock)
    engine.inject("obstacle", 30)
    engine.inject("drive_error", 30)
    engine.inject("comm_loss", 30)
    engine.inject("low_battery", 30)
    cleared = engine.clear_all()
    assert set(cleared) == {"obstacle", "drive_error", "comm_loss", "low_battery"}
    with lock:
        assert core["obstacle_active"] is False
        assert core["comm_loss_until"] == 0
    assert not rs.has_error("DriveFault")
    assert not rs.has_error("STO")
    assert battery.level == 80.0
    assert core["estop_active"] is True            # E-stop은 전용 해제 경로로만
    assert engine.active_faults() == []


def test_auto_mode_lifecycle():
    rs, battery, core, lock, runner, engine = make_env()
    config = engine.set_auto(True, interval_s=5)   # 최소 간격 5s — 테스트 중 주입 없음
    assert config["enabled"] is True and config["interval_s"] == 5
    assert engine._auto_thread is not None and engine._auto_thread.is_alive()
    engine.set_auto(False)
    assert engine._auto_thread is None
    engine.stop()
