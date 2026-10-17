"""T4 검증: 웨이포인트 주행 — 진행/도달/완주/거리 상한."""
import threading

from app.motion import MotionEngine
from app.order_runner import OrderRunner
from app.safeplc.base import NullPolicy, SafeContext, SafeVerdict
from app.state_machine import OpState, RobotState

from tests.test_order_runner import make_order


def make_env(policy=None, speed_mps=1.0, dt_s=0.5):
    rs = RobotState()
    runner = OrderRunner(rs, action_duration_s=0.0)  # 액션 즉시 완료 — 주행에 집중
    core = {"order_id": "", "order_update_id": 0, "last_node_id": None,
            "last_node_sequence_id": 0, "x": 0.0, "y": 0.0, "theta": 0.0}
    lock = threading.Lock()
    motion = MotionEngine(runner=runner, policy=policy or NullPolicy(),
                          speed_mps=speed_mps, dt_s=dt_s)
    return rs, runner, core, lock, motion


def run_ticks(motion, core, lock, rs, now, n):
    for _ in range(n):
        motion.tick(core, lock, rs, now)
        now += 0.5
    return now


def test_robot_drives_route_and_completes():
    rs, runner, core, lock, motion = make_env()
    runner.handle_order(make_order())
    now = 1000.0
    # 틱1: N1 도달(출발점), 틱2: N2로 출발, 틱3~8: 3m 주행 → N2 도달
    now = run_ticks(motion, core, lock, rs, now, 8)
    assert core["last_node_id"] == "N2"
    assert abs(core["x"] - 3.0) < 1e-6
    # 틱9~16: N3까지 3m → 완주
    now = run_ticks(motion, core, lock, rs, now, 8)
    assert runner.active.finished
    assert core["last_node_id"] == "N3"
    assert abs(core["x"] - 6.0) < 1e-6
    assert rs.op_state == OpState.IDLE
    # 완료 후 상태 보고는 비어야 한다 (관제 busy 판정 → IDLE)
    assert runner.route_state() == ([], [], [])


def test_step_is_capped_per_tick():
    rs, runner, core, lock, motion = make_env()  # 1.0 m/s * 0.5s = 0.5m/tick
    runner.handle_order(make_order())
    run_ticks(motion, core, lock, rs, 1000.0, 3)   # N1 도달 + 출발 틱
    run_ticks(motion, core, lock, rs, 1000.0 + 10, 1)
    x_before = core["x"]
    motion.tick(core, lock, rs, 1000.0 + 11)
    assert core["x"] - x_before <= 0.5 + 1e-6      # 틱당 0.5m 상한


def test_blocked_policy_freezes_position():
    class BlockAll:
        def evaluate(self, ctx: SafeContext) -> SafeVerdict:
            return SafeVerdict(allow_move=False, max_speed_mps=0.0)

    rs, runner, core, lock, motion = make_env(policy=BlockAll())
    runner.handle_order(make_order())
    run_ticks(motion, core, lock, rs, 1000.0, 10)
    assert core["x"] == 0.0                        # 한 칸도 못 움직임
    assert not runner.active.finished
    assert rs.op_state == OpState.WORKING          # 오더는 활성 — 작업 중 표시 유지
