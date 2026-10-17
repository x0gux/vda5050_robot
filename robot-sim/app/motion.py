"""주행 엔진 — 웨이포인트 추적 + 노드 액션 스케줄링.

불변식: 모든 이동은 SafePolicy.evaluate()의 SafeVerdict.allow_move == true일 때만 발생한다.
(T6의 ReferenceSafePolicy가 이 자리를 대체한다.)
"""
import logging
import math
import time
from typing import Any, Dict

from app.order_runner import OrderRunner
from app.safeplc.base import NullPolicy, SafeContext, SafePolicy, Vec
from app.state_machine import RobotState

log = logging.getLogger("robot-sim.motion")


def step_toward(from_v: Vec, to_v: Vec, max_step: float) -> Vec:
    dx, dy = to_v.x - from_v.x, to_v.y - from_v.y
    dist = math.hypot(dx, dy)
    if dist <= max_step or dist == 0.0:
        return Vec(to_v.x, to_v.y)
    k = max_step / dist
    return Vec(from_v.x + dx * k, from_v.y + dy * k)


def heading_deg(from_v: Vec, to_v: Vec) -> float:
    return math.degrees(math.atan2(to_v.y - from_v.y, to_v.x - from_v.x))


def _same(a: Vec, b: Vec, eps: float = 1e-9) -> bool:
    return abs(a.x - b.x) < eps and abs(a.y - b.y) < eps


class MotionEngine:
    def __init__(self, runner: OrderRunner, policy: SafePolicy, speed_mps: float, dt_s: float):
        self.runner = runner
        self.policy = policy
        self.speed_mps = speed_mps
        self.dt_s = dt_s

    def tick(self, core: Dict[str, Any], core_lock, robot_state: RobotState, now: float) -> None:
        """state 발행 주기마다 1회 호출 — 1틱 = dt_s초의 움직임."""
        with core_lock:
            active = self.runner.active
            if active is None or active.finished:
                robot_state.recalculate_op_state(working=False)
                return

            t = active.target_idx
            w = active.current_waypoint()
            pos = Vec(core["x"], core["y"])
            target = Vec(w.x, w.y)

            # 1) 노드 위에 서 있으면: 노드 액션 진행 (차량 정지 — 실물도 노드에서 액션 중엔 멈춘다)
            if active.arrived_idx == t:
                self.runner.advance_actions(now)
                robot_state.recalculate_op_state(working=not active.finished)
                return

            # 2) 이동 — 안전정책 심의 통과 필요 (safePLC 불변식)
            verdict = self.policy.evaluate(SafeContext(
                position=pos,
                speed_requested=self.speed_mps,
                estop_active=False,      # T6에서 실제 값 주입
                obstacle_active=False,   # T6/T7
                comm_ok=True,            # T6/T7
                inside_zones=[],         # T6
                errors_active=[e.get("errorType", "") for e in robot_state.errors],
            ))
            if not verdict.allow_move:
                robot_state.recalculate_op_state(working=True)
                return

            speed = min(self.speed_mps, verdict.max_speed_mps)
            moved = step_toward(pos, target, speed * self.dt_s)
            core["x"], core["y"] = moved.x, moved.y
            if not _same(pos, target):
                core["theta"] = heading_deg(pos, target)
            if _same(moved, target):
                self.runner.on_arrival(t)
                core["last_node_id"] = w.node_id
                core["last_node_sequence_id"] = w.sequence_id
            robot_state.recalculate_op_state(working=True)
