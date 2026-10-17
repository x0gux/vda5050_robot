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
    def __init__(self, runner: OrderRunner, policy: SafePolicy, speed_mps: float, dt_s: float,
                 zones=None, comm_ok=None):
        self.runner = runner
        self.policy = policy
        self.speed_mps = speed_mps
        self.dt_s = dt_s
        self.zones = zones or []            # [{name, center{x,y}, radius_m, max_speed_mps}]
        self.comm_ok = comm_ok              # Callable[[], bool] | None

    def _zones_at(self, pos: Vec) -> list:
        names = []
        for zone in self.zones:
            d = math.hypot(pos.x - float(zone["center"]["x"]), pos.y - float(zone["center"]["y"]))
            if d <= float(zone["radius_m"]):
                names.append(zone.get("name", "?"))
        return names

    def tick(self, core: Dict[str, Any], core_lock, robot_state: RobotState, now: float) -> None:
        """state 발행 주기마다 1회 호출 — 1틱 = dt_s초의 움직임."""
        with core_lock:
            # 0) 안전 심의는 오더 유무와 무관하게 "항상" 먼저 수행한다.
            #    E-stop 중에도 관제가 FATAL을 봐야 하기 때문이다 (safePLC 불변식).
            pos = Vec(core["x"], core["y"])
            comm_ok = self.comm_ok() if self.comm_ok else True
            verdict = self.policy.evaluate(SafeContext(
                position=pos,
                speed_requested=self.speed_mps,
                estop_active=bool(core.get("estop_active", False)),
                obstacle_active=bool(core.get("obstacle_active", False)),
                comm_ok=comm_ok,
                inside_zones=self._zones_at(pos),
                errors_active=[e.get("errorType", "") for e in robot_state.errors],
            ))
            for e in verdict.new_errors:
                robot_state.add_error(e["errorLevel"], e["errorType"],
                                      e["errorReference"], e["errorDescription"])
            for error_type in verdict.clear_error_types:
                robot_state.remove_error(error_type)

            active = self.runner.active
            if active is None or active.finished:
                robot_state.recalculate_op_state(working=False)
                return

            t = active.target_idx
            w = active.current_waypoint()
            target = Vec(w.x, w.y)

            # 보호정지/비상정지/통신두절 — 이동도, 노드 액션 진행도 멈춘다
            if not verdict.allow_move:
                robot_state.recalculate_op_state(working=True)
                return

            # 1) 노드 위에 서 있으면: 노드 액션 진행 (차량 정지 — 실물도 노드에서 액션 중엔 멈춘다)
            if active.arrived_idx == t:
                self.runner.advance_actions(now)
                robot_state.recalculate_op_state(working=not active.finished)
                return

            # 2) 이동 — 정책이 허용한 상한 속도로
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
