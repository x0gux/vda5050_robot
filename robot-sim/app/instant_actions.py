"""인스턴트 액션 처리 — MQTT(instantActions 토픽)와 제어 REST API(T7)가 함께 쓰는 단일 진입점.

한 곳에 모은 이유: 안전 동작(E-stop, 취소)의 의미가 채널마다 달라지면 안 된다.
브로커로 들어오든 REST로 들어오든 같은 판단을 거친다.
"""
import logging
from typing import Any, Dict

log = logging.getLogger("robot-sim.instant")


def handle_instant_action(action: Dict[str, Any], runner, core: Dict[str, Any], core_lock) -> None:
    """단일 action 객체를 처리한다. runner/core는 main의 공유 인스턴스."""
    action_type = action.get("actionType")
    action_id = action.get("actionId")

    if action_type == "cancelOrder":
        had = runner.cancel()
        if had:
            with core_lock:
                core["order_id"] = ""
                core["order_update_id"] = 0
        log.info("cancelOrder done (had_active=%s) actionId=%s", had, action_id)

    elif action_type == "faxEStop":
        params = {p.get("key"): p.get("value") for p in (action.get("actionParameters") or [])}
        activate = str(params.get("activate", "true")).lower() in ("true", "1", "yes")
        with core_lock:
            core["estop_active"] = activate
            if activate:
                # E-stop 활성 = 안전 최우선: 활성 오더 즉시 폐기 (복구 전까지 이동 인터락)
                runner.cancel()
                core["order_id"] = ""
                core["order_update_id"] = 0
        log.info("faxEStop activate=%s actionId=%s", activate, action_id)

    else:
        log.info("%s received (actionId=%s) — 핸들러 미정의, 무시", action_type, action_id)
