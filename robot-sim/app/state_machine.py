"""로봇 운용 상태 — opState 전이와 errors[] 홀더.

opState는 관제가 화면 색으로 보는 값:
  IDLE    대기 (초록)
  WORKING 작업 중 (파랑)
  ERROR   치명 오류 (빨강) — FATAL/ERROR 레벨 에러가 하나라도 있으면 관제가 이렇게 판정한다.
"""
from enum import Enum
from typing import Any, Dict, List

from app.messages import make_error


class OpState(str, Enum):
    IDLE = "IDLE"
    WORKING = "WORKING"
    ERROR = "ERROR"


class RobotState:
    def __init__(self) -> None:
        self.op_state: OpState = OpState.IDLE
        self._errors: List[Dict[str, Any]] = []

    def set_op_state(self, op_state: OpState) -> None:
        self.op_state = op_state

    def add_error(self, level: str, error_type: str, reference: str, description: str) -> None:
        """동일 errorType 중복 추가 방지 — state는 고빈도 메시지라 같은 에러를 반복 보내면 로그가 도배된다."""
        if self.has_error(error_type):
            return
        self._errors.append(make_error(level, error_type, reference, description))

    def remove_error(self, error_type: str) -> None:
        self._errors = [e for e in self._errors if e.get("errorType") != error_type]

    def clear_all_errors(self) -> None:
        self._errors.clear()

    def has_error(self, error_type: str) -> bool:
        return any(e.get("errorType") == error_type for e in self._errors)

    @property
    def errors(self) -> List[Dict[str, Any]]:
        return list(self._errors)

    def recalculate_op_state(self, working: bool) -> OpState:
        """FATAL/ERROR 레벨 에러가 있으면 ERROR, 작업 중이면 WORKING, 아니면 IDLE."""
        has_fatal = any(
            e.get("errorLevel", "FATAL").upper() in ("FATAL", "ERROR") for e in self._errors
        )
        if has_fatal:
            self.op_state = OpState.ERROR
        elif working:
            self.op_state = OpState.WORKING
        else:
            self.op_state = OpState.IDLE
        return self.op_state
