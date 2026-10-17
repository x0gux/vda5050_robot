"""safePLC 참조구현 — 실물 안전PLC의 판단을 VDA5050으로 관측 가능한 동작으로 재현.

우선순위 (산업 안전 관례):
  1. 비상정지(STO)  → FATAL, 즉시 정지, 해제 전까지 어떤 조합이든 이동 금지
  2. 장애물 감지    → WARNING + 보호정지 (에러는 노랑, 움직임은 멈춤 — 해제 시 같은 오더 재개)
  3. 통신두절       → 로컬 정지 (에러 엔트리 없음: 브로커가 없으면 보낼 통로도 없다)
  4. 존 속도제한    → 존 내부에서는 존의 상한속도로 감속 (정지 아님)
"""
import math
from typing import Any, Dict, List, Optional

from app.messages import make_error
from app.safeplc.base import SafeContext, SafeVerdict


class ReferenceSafePolicy:
    def __init__(self, zones: Optional[List[Dict[str, Any]]] = None):
        self.zones = zones or []

    def evaluate(self, ctx: SafeContext) -> SafeVerdict:
        allow_move = True
        max_speed = float("inf")
        new_errors: List[Dict[str, Any]] = []
        clear_error_types: List[str] = []

        # 1) 비상정지 (STO)
        if ctx.estop_active:
            allow_move = False
            if "faxEStop" not in ctx.errors_active:
                new_errors.append(make_error(
                    "FATAL", "faxEStop", "ESTOP-001", "emergency stop activated"))
        elif "faxEStop" in ctx.errors_active:
            clear_error_types.append("faxEStop")

        # 2) 장애물 보호정지
        if ctx.obstacle_active:
            allow_move = False
            if "obstacle" not in ctx.errors_active:
                new_errors.append(make_error(
                    "WARNING", "obstacle", "0x207", "There are obstacles around"))
        elif "obstacle" in ctx.errors_active:
            clear_error_types.append("obstacle")

        # 3) 통신 failsafe — 로컬 정지, 에러 엔트리 없음
        if not ctx.comm_ok:
            allow_move = False

        # 4) 존 속도제한 — 여러 존에 걸리면 가장 엄격한 상한 적용
        for zone in self.zones:
            distance = math.hypot(
                ctx.position.x - float(zone["center"]["x"]),
                ctx.position.y - float(zone["center"]["y"]),
            )
            if distance <= float(zone["radius_m"]):
                max_speed = min(max_speed, float(zone["max_speed_mps"]))

        # 5) 활성 에러에 대한 안전 반응 (T7 고장주입과 연결)
        #    - 구동유닛 고장(ERROR) → 주행 차단
        #    - STO 워닝(WARNING)   → 정지는 아니지만 속도 절반 상한 (충전 도킹 관찰 사례)
        if "DriveFault" in ctx.errors_active:
            allow_move = False
        if "STO" in ctx.errors_active:
            max_speed = min(max_speed, 0.5 * ctx.speed_requested)

        return SafeVerdict(allow_move=allow_move, max_speed_mps=max_speed,
                           new_errors=new_errors, clear_error_types=clear_error_types)
