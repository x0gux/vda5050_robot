"""안전정책 인터페이스 — safePLC의 계약(T4에서 자리만 잡고, T6에서 참조구현 작성).

불변식: 주행 모터는 반드시 SafeVerdict.allow_move == true일 때만 구동된다.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


@dataclass
class Vec:
    x: float
    y: float


@dataclass
class SafeContext:
    """정책이 판단에 쓰는 현재 상태 스냅샷."""
    position: Vec
    speed_requested: float          # 로봇이 요청한 속도 (m/s)
    estop_active: bool              # 비상정지(STO) 활성 여부
    obstacle_active: bool           # 장애물 감지 활성 여부
    comm_ok: bool                   # 통신 상태 (브로커 연결)
    inside_zones: List[str]         # 현재 위치가 속한 존 이름들
    errors_active: List[str]        # 현재 활성 에러의 errorType 목록


@dataclass
class SafeVerdict:
    """정책의 판정 결과."""
    allow_move: bool
    max_speed_mps: float
    new_errors: List[Dict[str, Any]] = field(default_factory=list)      # 추가할 errors[] 엔트리
    clear_error_types: List[str] = field(default_factory=list)          # 제거할 errorType 목록


@runtime_checkable
class SafePolicy(Protocol):
    def evaluate(self, ctx: SafeContext) -> SafeVerdict: ...


class NullPolicy:
    """T6 이전 기본 정책 — 항상 허용, 속도 상한 없음."""

    def evaluate(self, ctx: SafeContext) -> SafeVerdict:
        return SafeVerdict(allow_move=True, max_speed_mps=float("inf"))
