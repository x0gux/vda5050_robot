"""제어 REST API — 실습/데모용 고장주입·비상정지 트리거.

주의: 인증 없음 — 교육용 로컬 신뢰 환경 전용. 외부 노출 금지 (compose에서 8090만 로컬 바인딩 권장).
"""
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.instant_actions import handle_instant_action


class EstopRequest(BaseModel):
    activate: bool


class FaultRequest(BaseModel):
    type: str
    duration_s: float = 30.0


class AutoFaultsRequest(BaseModel):
    enabled: bool
    interval_s: float = 120.0
    types: Optional[List[str]] = None


def create_control_router(engine) -> APIRouter:
    router = APIRouter()

    @router.post("/estop")
    def estop(req: EstopRequest) -> Dict[str, Any]:
        """비상정지 트리거 — MQTT faxEStop과 동일한 안전 경로를 탄다."""
        action = {
            "actionType": "faxEStop",
            "actionId": f"api-estop-{uuid.uuid4().hex[:8]}",
            "actionParameters": [{"key": "activate", "value": req.activate}],
        }
        handle_instant_action(action, engine.runner, engine.core, engine.core_lock)
        with engine.core_lock:
            return {"success": True, "estop_active": bool(engine.core.get("estop_active"))}

    @router.post("/faults")
    def inject_fault(req: FaultRequest) -> Dict[str, Any]:
        try:
            return engine.inject(req.type, req.duration_s)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/faults/clear")
    def clear_faults() -> Dict[str, Any]:
        return {"cleared": engine.clear_all()}

    @router.get("/faults")
    def active_faults() -> Dict[str, Any]:
        return {"active": engine.active_faults()}

    @router.post("/auto-faults")
    def auto_faults(req: AutoFaultsRequest) -> Dict[str, Any]:
        try:
            return engine.set_auto(req.enabled, req.interval_s, req.types)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return router
