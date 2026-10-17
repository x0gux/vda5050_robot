"""T5 검증: 배터리 방전/충전, 저전압 경고, charge 액션 완료 조건."""
import threading

from app.battery import BatteryModel, manage_low_battery_warning
from app.motion import MotionEngine
from app.order_runner import OrderRunner
from app.safeplc.base import NullPolicy
from app.state_machine import RobotState


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def make_charge_order(order_id="ORDER-CHARGE", update_id=0):
    """N1(0,0) → N4(6,3). N4에서 charge 액션."""
    return {
        "headerId": 1, "timestamp": "2026-01-01T00:00:00Z", "version": "2.0.0",
        "manufacturer": "study", "serialNumber": "SIM-001",
        "orderId": order_id, "orderUpdateId": update_id,
        "nodes": [
            {"nodeId": "N1", "sequenceId": 1, "released": True,
             "nodePosition": {"x": 0, "y": 0, "theta": 0, "mapId": "study_map"}},
            {"nodeId": "N2", "sequenceId": 3, "released": True,
             "nodePosition": {"x": 3, "y": 0, "theta": 0, "mapId": "study_map"}},
            {"nodeId": "N3", "sequenceId": 5, "released": True,
             "nodePosition": {"x": 6, "y": 0, "theta": 0, "mapId": "study_map"}},
            {"nodeId": "N4", "sequenceId": 7, "released": True,
             "nodePosition": {"x": 6, "y": 3, "theta": 0, "mapId": "study_map"},
             "actions": [{"actionId": "charge-1", "actionType": "charge", "blockingType": "NONE"}]},
        ],
        "edges": [
            {"sequenceId": 2, "startNodeId": "N1", "endNodeId": "N2", "released": True},
            {"sequenceId": 4, "startNodeId": "N2", "endNodeId": "N3", "released": True},
            {"sequenceId": 6, "startNodeId": "N3", "endNodeId": "N4", "released": True},
        ],
    }


def make_env(battery_level=100.0, charge_pct_per_min=6000.0):
    rs = RobotState()
    clock = FakeClock()
    battery = BatteryModel(level=battery_level, drain_pct_per_min=0.0,  # 테스트에서 수동 제어
                           charge_pct_per_min=charge_pct_per_min, low_threshold=20.0)
    runner = OrderRunner(rs, action_duration_s=1.0, clock=clock, battery=battery)
    core = {"order_id": "", "order_update_id": 0, "last_node_id": None,
            "last_node_sequence_id": 0, "x": 0.0, "y": 0.0, "theta": 0.0}
    lock = threading.Lock()
    motion = MotionEngine(runner=runner, policy=NullPolicy(), speed_mps=1.0, dt_s=0.5)
    return rs, runner, core, lock, motion, clock, battery


def drive_to_node(runner, core, lock, rs, motion, clock, ticks):
    for _ in range(ticks):
        motion.tick(core, lock, rs, clock.t)
        clock.advance(0.5)


def test_charging_battery_stops_draining_and_recovers():
    battery = BatteryModel(level=50.0, drain_pct_per_min=60.0, charge_pct_per_min=60.0)
    battery.tick()
    battery.charging = True
    import time
    time.sleep(1.1)
    level = battery.tick()
    assert level >= 50.0  # 충전 중엔 방전하지 않는다 (회복 or 유지)
    battery.charging = False
    battery.level = 50.0
    time.sleep(1.1)
    assert battery.tick() < 50.0  # 충전 해제 후 다시 방전


def test_low_battery_warning_toggles():
    rs = RobotState()
    battery = BatteryModel(level=15.0, low_threshold=20.0)
    manage_low_battery_warning(rs, battery, 20.0)
    assert rs.has_error("BatteryLow")
    warning = [e for e in rs.errors if e["errorType"] == "BatteryLow"][0]
    assert warning["errorLevel"] == "WARNING"        # 저전압은 WARNING — 작업 지속
    assert warning["errorReference"] == "BAT-001"

    battery.charging = True                          # 충전 시작 → 경고 해제
    manage_low_battery_warning(rs, battery, 20.0)
    assert not rs.has_error("BatteryLow")

    battery.charging = False                         # 충전 해제 + 여전히 낮음 → 재발
    manage_low_battery_warning(rs, battery, 20.0)
    assert rs.has_error("BatteryLow")

    battery.level = 80.0                             # 임계 회복 → 해제
    manage_low_battery_warning(rs, battery, 20.0)
    assert not rs.has_error("BatteryLow")


def test_charge_action_runs_until_battery_full():
    rs, runner, core, lock, motion, clock, battery = make_env(battery_level=50.0)
    runner.handle_order(make_charge_order())
    # N1→N2→N3→N4: 9m = 18틱 + 노드 체류 틱들 → 여유있게 24틱
    drive_to_node(runner, core, lock, rs, motion, clock, 24)
    assert core["last_node_id"] == "N4"
    assert abs(core["x"] - 6.0) < 1e-6 and abs(core["y"] - 3.0) < 1e-6

    # charge 액션 RUNNING 중 — 배터리 100% 미만이면 끝나지 않는다
    _, _, action_states = runner.route_state()
    charge = [a for a in action_states if a["actionId"] == "charge-1"][0]
    assert charge["actionStatus"] == "RUNNING"
    assert battery.charging is True
    assert not runner.active.finished

    # 배터리가 가득 차는 순간 → 액션 완료 + 충전 플래그 해제 + 오더 완주(마지막 노드)
    battery.level = 100.0
    motion.tick(core, lock, rs, clock.t)
    clock.advance(0.5)
    motion.tick(core, lock, rs, clock.t)
    assert runner.active.finished                    # 마지막 노드라 오더 즉시 완주
    assert runner.route_state() == ([], [], [])      # 완료 후 상태 보고 클리어 (관제 IDLE 판정용)
    assert battery.charging is False


def test_cancel_mid_charge_stops_charging():
    rs, runner, core, lock, motion, clock, battery = make_env(battery_level=50.0)
    runner.handle_order(make_charge_order())
    drive_to_node(runner, core, lock, rs, motion, clock, 24)
    assert battery.charging is True
    runner.cancel()
    assert battery.charging is False                 # 충전 중 취소 → 충전 정지
    assert runner.active is None
