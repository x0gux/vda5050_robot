"""배터리 모델 — 실제 시간 기반 선형 방전/충전.

T3: 방전 + charging 플래그
T5: 충전 회복, 저전압 경고 로직과 연결
"""
import time
from typing import Optional


class BatteryModel:
    def __init__(
        self,
        level: float = 100.0,
        drain_pct_per_min: float = 0.5,
        charge_pct_per_min: float = 10.0,
        low_threshold: float = 20.0,
    ):
        self.level = max(0.0, min(100.0, level))
        self.drain_pct_per_min = drain_pct_per_min
        self.charge_pct_per_min = charge_pct_per_min
        self.low_threshold = low_threshold
        self.charging = False
        self._last_tick: Optional[float] = None

    def tick(self) -> float:
        """경과 시간만큼 방전/충전을 반영하고 현재 잔량(%) 반환."""
        now = time.monotonic()
        if self._last_tick is None:
            self._last_tick = now
            return self.level
        elapsed_min = (now - self._last_tick) / 60.0
        self._last_tick = now
        if self.charging:
            self.level = min(100.0, self.level + self.charge_pct_per_min * elapsed_min)
        else:
            self.level = max(0.0, self.level - self.drain_pct_per_min * elapsed_min)
        return self.level

    @property
    def is_low(self) -> bool:
        return self.level < self.low_threshold and not self.charging


def manage_low_battery_warning(robot_state, battery: "BatteryModel", threshold: float) -> None:
    """저전압 WARNING 관리 — T5.

    - 배터리 < threshold && 미충전: WARNING(BatteryLow, BAT-001) 유지 (중복 추가는 add_error가 흡수)
    - 충전 시작 또는 임계 회복: WARNING 제거
    """
    if battery.is_low:
        robot_state.add_error("WARNING", "BatteryLow", "BAT-001",
                              f"battery below {threshold:.0f}%")
    elif robot_state.has_error("BatteryLow"):
        robot_state.remove_error("BatteryLow")
