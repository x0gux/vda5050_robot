"""T6 검증: safePLC 참조정책 (TDD — 이 테스트가 먼저, 구현은 나중).

안전 불변식:
  I-1  비상정지(FATAL) 중엔 어떤 경우에도 주행 금지
  I-2  비상정지 해제 시 FATAL 에러 제거 (오더는 활성화 시점에 이미 폐기됨 → IDLE)
  I-3  장애물 보호정지는 WARNING — 에러는 있되 오더는 유지, 해제 시 같은 오더로 재개
  I-4  존 내부에서는 존의 최대속도로 상한
  I-5  통신두절 시 로컬 정지 (에러 엔트리 없음 — 발행 자체가 불가)
"""
import threading

from app.battery import BatteryModel
from app.instant_actions import handle_instant_action
from app.motion import MotionEngine
from app.order_runner import OrderRunner
from app.safeplc.base import SafeContext, SafeVerdict, Vec
from app.state_machine import OpState, RobotState

from tests.test_order_runner import make_order

ZONES = [{"name": "hazard", "center": {"x": 3, "y": 0}, "radius_m": 1.5, "max_speed_mps": 0.3}]


def ctx(**kw):
    base = dict(position=Vec(0, 0), speed_requested=1.0, estop_active=False,
                obstacle_active=False, comm_ok=True, inside_zones=[], errors_active=[])
    base.update(kw)
    return SafeContext(**base)


# ---- 정책 단위 테스트 ----

def test_estop_blocks_and_emits_fatal():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=[]).evaluate(ctx(estop_active=True))
    assert v.allow_move is False
    e = v.new_errors[0]
    assert e["errorLevel"] == "FATAL"
    assert e["errorType"] == "faxEStop"
    assert e["errorReference"] == "ESTOP-001"


def test_estop_recover_clears_fatal():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=[]).evaluate(ctx(estop_active=False, errors_active=["faxEStop"]))
    assert v.allow_move is True
    assert v.clear_error_types == ["faxEStop"]
    assert v.new_errors == []


def test_estop_error_not_duplicated():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=[]).evaluate(ctx(estop_active=True, errors_active=["faxEStop"]))
    assert v.new_errors == []          # 이미 활성 에러 — state 도배 방지


def test_obstacle_protective_stop_with_warning_then_resume():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=[]).evaluate(ctx(obstacle_active=True))
    assert v.allow_move is False
    e = v.new_errors[0]
    assert e["errorLevel"] == "WARNING"           # 장애물은 WARNING — 관제는 주황
    assert e["errorType"] == "obstacle"
    assert e["errorReference"] == "0x207"

    v2 = ReferenceSafePolicy(zones=[]).evaluate(ctx(obstacle_active=False, errors_active=["obstacle"]))
    assert v2.allow_move is True                  # 해제 시 재개
    assert v2.clear_error_types == ["obstacle"]


def test_zone_caps_speed_inside_only():
    from app.safeplc.reference import ReferenceSafePolicy
    policy = ReferenceSafePolicy(zones=ZONES)
    inside = policy.evaluate(ctx(position=Vec(3.5, 0)))       # 존 중심(3,0) r=1.5 내부
    assert inside.allow_move is True
    assert inside.max_speed_mps == 0.3
    outside = policy.evaluate(ctx(position=Vec(0, 0)))
    assert outside.max_speed_mps == float("inf")              # 존 밖 — 상한 없음


def test_comm_loss_blocks_locally_without_error_entries():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=[]).evaluate(ctx(comm_ok=False))
    assert v.allow_move is False
    assert v.new_errors == []                     # 브로커 단선 — 보낼 통로가 없다


def test_estop_beats_zone_and_obstacle():
    from app.safeplc.reference import ReferenceSafePolicy
    v = ReferenceSafePolicy(zones=ZONES).evaluate(ctx(position=Vec(3, 0), estop_active=True, obstacle_active=True))
    assert v.allow_move is False                  # 어떤 조합이든 E-stop이면 정지


# ---- 모션 통합 테스트 ----

def make_env(zones=None):
    from app.safeplc.reference import ReferenceSafePolicy
    rs = RobotState()
    battery = BatteryModel(level=100.0, drain_pct_per_min=0.0)
    runner = OrderRunner(rs, action_duration_s=0.0, battery=battery)
    core = {"order_id": "", "order_update_id": 0, "last_node_id": None,
            "last_node_sequence_id": 0, "x": 0.0, "y": 0.0, "theta": 0.0,
            "estop_active": False, "obstacle_active": False}
    lock = threading.Lock()
    motion = MotionEngine(runner=runner, policy=ReferenceSafePolicy(zones=zones or []),
                          speed_mps=1.0, dt_s=0.5)
    return rs, runner, core, lock, motion


def run_ticks(motion, core, lock, rs, now, n):
    for _ in range(n):
        motion.tick(core, lock, rs, now)
        now += 0.5
    return now


def test_estop_mid_route_freezes_emits_fatal_and_recover_goes_idle():
    rs, runner, core, lock, motion = make_env()
    runner.handle_order(make_order())
    now = run_ticks(motion, core, lock, rs, 1000.0, 5)     # 주행 중 (x≈1.5)
    x_before = core["x"]
    assert runner.has_active()

    # faxEStop activate — 실제 핸들러 경로(MQTT/REST 공용)를 그대로 사용
    handle_instant_action(
        {"actionType": "faxEStop", "actionId": "estop-1",
         "actionParameters": [{"key": "activate", "value": True}]},
        runner, core, lock)
    run_ticks(motion, core, lock, rs, now, 4)
    assert core["x"] == x_before                            # I-1 동결
    fatal = [e for e in rs.errors if e["errorType"] == "faxEStop"]
    assert fatal and fatal[0]["errorLevel"] == "FATAL"
    assert rs.op_state == OpState.ERROR                     # 관제 빨간 불
    assert runner.active is None                            # E-stop 활성 시 오더 폐기

    core["estop_active"] = False                            # faxEStop deactivate
    handle_instant_action(
        {"actionType": "faxEStop", "actionId": "estop-1",
         "actionParameters": [{"key": "activate", "value": False}]},
        runner, core, lock)
    run_ticks(motion, core, lock, rs, now + 10, 2)
    assert not rs.has_error("faxEStop")                     # I-2 FATAL 제거
    assert rs.op_state == OpState.IDLE                      # 오더 폐기됨 → IDLE


def test_obstacle_stops_then_resumes_same_order():
    rs, runner, core, lock, motion = make_env()
    runner.handle_order(make_order())
    now = run_ticks(motion, core, lock, rs, 1000.0, 5)     # x≈1.5
    x_at_obstacle = core["x"]

    core["obstacle_active"] = True                          # 장애물 발생
    run_ticks(motion, core, lock, rs, now, 4)
    assert core["x"] == x_at_obstacle                       # 보호정지
    warning = [e for e in rs.errors if e["errorType"] == "obstacle"]
    assert warning and warning[0]["errorLevel"] == "WARNING"
    assert rs.op_state == OpState.WORKING                   # WARNING — 작업중 표시 유지
    assert runner.has_active()                              # I-3 오더 유지

    core["obstacle_active"] = False                         # 장애물 해제
    run_ticks(motion, core, lock, rs, now + 10, 20)
    assert runner.active.finished                           # 같은 오더로 완주
    assert not rs.has_error("obstacle")                     # WARNING 제거
    assert rs.op_state == OpState.IDLE
    assert abs(core["x"] - 6.0) < 1e-6


def test_zone_slows_motion_inside():
    rs, runner, core, lock, motion = make_env(zones=ZONES)  # hazard 존: 중심(3,0) r=1.5, 상한 0.3m/s
    runner.handle_order(make_order())
    run_ticks(motion, core, lock, rs, 1000.0, 2)            # N1 도달 + 출발
    x_start = core["x"]
    run_ticks(motion, core, lock, rs, 1000.0 + 10, 1)       # 존 밖 구간 1틱: 0.5m
    assert core["x"] - x_start <= 0.5 + 1e-6
    # x=2.6 (존 경계 1.5+r=4.5? 존 중심 3 r 1.5 → x∈[1.5,4.5]) — 존 내 진입 후 속도 저하 확인
    ticks_to_enter = 0
    while core["x"] < 2.0 and ticks_to_enter < 20:
        run_ticks(motion, core, lock, rs, 1000.0 + 20 + ticks_to_enter, 1)
        ticks_to_enter += 1
    x_in = core["x"]
    assert x_in >= 1.5                                      # 존 진입 확인
    run_ticks(motion, core, lock, rs, 1000.0 + 50, 1)       # 존 내부 1틱
    assert core["x"] - x_in <= 0.3 * 0.5 + 1e-6             # I-4: 0.15m/틱 상한
