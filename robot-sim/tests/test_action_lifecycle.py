"""T4 검증: 노드 액션 생애주기 — RUNNING → FINISHED, 액션 중 주행 보류, cancelOrder."""
import threading

from app.motion import MotionEngine
from app.order_runner import OrderRunner
from app.safeplc.base import NullPolicy
from app.state_machine import RobotState

from tests.test_order_runner import make_order


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def make_env(action_duration_s=1.0):
    rs = RobotState()
    clock = FakeClock()
    runner = OrderRunner(rs, action_duration_s=action_duration_s, clock=clock)
    core = {"order_id": "", "order_update_id": 0, "last_node_id": None,
            "last_node_sequence_id": 0, "x": 0.0, "y": 0.0, "theta": 0.0}
    lock = threading.Lock()
    motion = MotionEngine(runner=runner, policy=NullPolicy(), speed_mps=1.0, dt_s=0.5)
    return rs, runner, core, lock, motion, clock


def drive_to_node2(runner, core, lock, rs, motion, clock):
    """N1 도달 → N2 도달(액션 보유 노드)까지 진행."""
    runner.handle_order(make_order(with_actions=True))
    for _ in range(8):                       # 틱1 N1 도달, 틱2 출발, 틱3~8 N2 도달
        motion.tick(core, lock, rs, clock.t)
        clock.advance(0.5)


def test_action_runs_and_finishes_then_motion_resumes():
    rs, runner, core, lock, motion, clock = make_env(action_duration_s=1.0)
    drive_to_node2(runner, core, lock, rs, motion, clock)

    # N2 도달 직후: pick-1 RUNNING
    _, _, action_states = runner.route_state()
    pick = [a for a in action_states if a["actionId"] == "pick-1"][0]
    assert pick["actionStatus"] == "RUNNING"

    # 액션 duration(1.0s) 미경과 — 여러 틱 지나도 여전히 RUNNING, 위치 고정
    for _ in range(3):
        motion.tick(core, lock, rs, clock.t)
        clock.advance(0.2)
    _, _, action_states = runner.route_state()
    pick = [a for a in action_states if a["actionId"] == "pick-1"][0]
    assert pick["actionStatus"] == "RUNNING"
    assert abs(core["x"] - 3.0) < 1e-6       # 액션 중 주행 보류

    # duration 경과 → FINISHED → 다음 웨이포인트로 출발
    clock.advance(2.0)
    motion.tick(core, lock, rs, clock.t)
    _, _, action_states = runner.route_state()
    pick = [a for a in action_states if a["actionId"] == "pick-1"][0]
    assert pick["actionStatus"] == "FINISHED"
    x_before = core["x"]
    motion.tick(core, lock, rs, clock.t)
    clock.advance(0.5)
    motion.tick(core, lock, rs, clock.t)
    assert core["x"] > x_before              # 주행 재개


def test_cancel_order_mid_route_stops_everything():
    rs, runner, core, lock, motion, clock = make_env()
    runner.handle_order(make_order())
    for _ in range(5):
        motion.tick(core, lock, rs, clock.t)
        clock.advance(0.5)
    assert runner.cancel() is True
    motion.tick(core, lock, rs, clock.t)
    assert rs.op_state.value == "IDLE"
    assert runner.route_state() == ([], [], [])
    x_after_cancel = core["x"]
    motion.tick(core, lock, rs, clock.t)
    clock.advance(5.0)
    motion.tick(core, lock, rs, clock.t)
    assert core["x"] == x_after_cancel       # 폐기 후 이동 없음
