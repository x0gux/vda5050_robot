"""고장주입 엔진 — 실물에서 관측된 고장을 안전하게 재현한다 (T7).

시나리오 카탈로그 (모두 시간 기반 자동 해제):
  obstacle    장애물 감지      → safePLC 보호정지 + WARNING(0x207)
  sto_warning STO 워닝         → WARNING(0x207) + 속도 50% 상한 (정지 아님 — 충전 도킹 관찰 사례)
  drive_error 구동유닛 고장    → ERROR(DRV-002) + 주행 차단 → 해제 시 복구
  comm_loss   통신 두절        → state/connection 발행 중단 + 로컬 정지 → 복구 시 ONLINE 재발행
  low_battery 저전압 강제      → 배터리 12% 강제 → BatteryLow WARNING (충전 시 해제)

auto 모드: 일정 간격으로 무작위 시나리오 주입 (데모용).
"""
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("robot-sim.faults")

FAULT_TYPES = ("obstacle", "sto_warning", "drive_error", "comm_loss", "low_battery")


class FaultEngine:
    def __init__(self, core: Dict[str, Any], core_lock, robot_state, battery,
                 mqtt_client=None, runner=None, clock=time.monotonic):
        self.core = core
        self.core_lock = core_lock
        self.robot_state = robot_state
        self.battery = battery
        self.mqtt_client = mqtt_client
        self.runner = runner            # /estop → handle_instant_action에서 사용
        self.clock = clock
        self._timers: Dict[str, threading.Timer] = {}
        self._saved_battery_level: Optional[float] = None
        self._auto_stop = threading.Event()
        self._auto_thread: Optional[threading.Thread] = None
        self._auto_interval_s = 120.0
        self._auto_types: List[str] = list(FAULT_TYPES)
        self._lock = threading.Lock()

    # ---- 주입 ----
    def inject(self, fault_type: str, duration_s: float) -> Dict[str, Any]:
        if fault_type not in FAULT_TYPES:
            raise ValueError(f"unknown fault type: {fault_type}")
        with self._lock:
            self._cancel_timer(fault_type)
            applied: Dict[str, Any] = {"type": fault_type, "duration_s": duration_s}

            if fault_type == "obstacle":
                with self.core_lock:
                    self.core["obstacle_active"] = True
                self._arm(fault_type, duration_s, self._clear_obstacle)

            elif fault_type == "sto_warning":
                self.robot_state.add_error("WARNING", "STO", "0x207", "STO warning during docking")
                self._arm(fault_type, duration_s, lambda: self.robot_state.remove_error("STO"))

            elif fault_type == "drive_error":
                self.robot_state.add_error("ERROR", "DriveFault", "DRV-002", "drive unit fault")
                self._arm(fault_type, duration_s, lambda: self.robot_state.remove_error("DriveFault"))

            elif fault_type == "comm_loss":
                with self.core_lock:
                    self.core["comm_loss_until"] = self.clock() + duration_s
                self._arm(fault_type, duration_s, self._resume_comm)

            elif fault_type == "low_battery":
                self._saved_battery_level = self.battery.level
                self.battery.level = 12.0
                self._arm(fault_type, duration_s, self._restore_battery)

            log.info("fault injected: %s (%.1fs)", fault_type, duration_s)
            return applied

    def clear_all(self) -> List[str]:
        """주입된 고장을 즉시 해제. 단, E-stop(faxEStop)은 전용 해제 경로로만 푼다."""
        cleared: List[str] = []
        with self._lock:
            for fault_type in list(self._timers.keys()):
                self._cancel_timer(fault_type)
                cleared.append(fault_type)
        if "obstacle" in cleared:
            self._clear_obstacle()
        if "sto_warning" in cleared:
            self.robot_state.remove_error("STO")
        if "drive_error" in cleared:
            self.robot_state.remove_error("DriveFault")
        if "comm_loss" in cleared:
            self._resume_comm()
        if "low_battery" in cleared:
            self._restore_battery()
        log.info("faults cleared: %s (estop은 유지)", cleared or "none")
        return cleared

    def active_faults(self) -> List[str]:
        with self._lock:
            return list(self._timers.keys())    # ---- auto 모드 ----
    def set_auto(self, enabled: bool, interval_s: float = 120.0,
                 types: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            self._auto_interval_s = max(5.0, float(interval_s))
            if types:
                unknown = [t for t in types if t not in FAULT_TYPES]
                if unknown:
                    raise ValueError(f"unknown fault types: {unknown}")
                self._auto_types = list(types)
            if enabled and not self._auto_thread:
                self._auto_stop.clear()
                self._auto_thread = threading.Thread(
                    target=self._auto_loop, name="auto-faults", daemon=True)
                self._auto_thread.start()
            elif not enabled and self._auto_thread:
                self._auto_stop.set()
                self._auto_thread = None
            config = {"enabled": enabled, "interval_s": self._auto_interval_s,
                      "types": list(self._auto_types)}
        log.info("auto-faults: %s", config)
        return config

    def stop(self) -> None:
        self._auto_stop.set()
        with self._lock:
            for t in list(self._timers.keys()):
                self._cancel_timer(t)

    def _auto_loop(self) -> None:
        while not self._auto_stop.wait(self._auto_interval_s):
            fault_type = random.choice(self._auto_types)
            try:
                self.inject(fault_type, duration_s=min(30.0, self._auto_interval_s / 2))
            except Exception:
                log.exception("auto injection failed")

    # ---- 내부 ----
    def _arm(self, fault_type: str, duration_s: float, on_expire) -> None:
        timer = threading.Timer(max(0.1, duration_s), lambda: self._on_expire(fault_type, on_expire))
        timer.daemon = True
        self._timers[fault_type] = timer
        timer.start()

    def _on_expire(self, fault_type: str, on_expire) -> None:
        """자연 만료 — active 목록에서도 제거해야 /faults가 정직하게 보인다."""
        with self._lock:
            self._timers.pop(fault_type, None)
        on_expire()

    def _cancel_timer(self, fault_type: str) -> None:
        timer = self._timers.pop(fault_type, None)
        if timer:
            timer.cancel()

    def _clear_obstacle(self) -> None:
        with self.core_lock:
            self.core["obstacle_active"] = False

    def _resume_comm(self) -> None:
        with self.core_lock:
            self.core["comm_loss_until"] = 0
        if self.mqtt_client is not None:
            # 복구 마커: connection ONLINE 재발행 (관제가 OFFLINE→ONLINE 전이를 보게 한다)
            try:
                self.mqtt_client.publish(
                    self.mqtt_client.identity.connection_topic(),
                    self.mqtt_client.connection_factory("ONLINE"), qos=0, retain=True)
            except Exception:
                log.exception("resume connection publish failed")

    def _restore_battery(self) -> None:
        if self._saved_battery_level is not None:
            self.battery.level = self._saved_battery_level
            self._saved_battery_level = None
