"""robot-sim 엔트리포인트.

기동 흐름:
  1. MQTT 접속 (접속되면 connection ONLINE 발행 + order/instantActions 구독)
  2. 백그라운드 스레드가 500ms(2Hz)마다 state 발행
  3. 같은 틱에서 MotionEngine이 오더 경로를 따라 주행 (T4)
  4. FastAPI(제어API) 기동 — /health, /status (T7에서 고장주입 엔드포인트 추가)

T6(safePLC)는 MotionEngine에 주입되는 정책을 교체하는 방식으로 꽂힌다.
"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI

from app.battery import BatteryModel, manage_low_battery_warning
from app.config import settings
from app.identity import Identity
from app.messages import MessageBuilder
from app.motion import MotionEngine
from app.mqtt_client import SimMqttClient
from app.order_runner import OrderRunner
from app.safeplc.base import NullPolicy
from app.state_machine import RobotState

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("robot-sim")

identity = Identity(
    manufacturer=settings.robot_manufacturer,
    serial_number=settings.robot_serial,
    map_id=settings.map_id,
)
builder = MessageBuilder(identity)
battery = BatteryModel(
    level=settings.battery_start_level,
    drain_pct_per_min=settings.battery_drain_pct_per_min,
    charge_pct_per_min=settings.battery_charge_pct_per_min,
    low_threshold=settings.low_battery_threshold,
)
robot_state = RobotState()
stop_event = threading.Event()

# --- 공유 로봇 코어 상태 ---
core_lock = threading.Lock()
core: Dict[str, Any] = {
    "order_id": "",
    "order_update_id": 0,
    "last_node_id": None,
    "last_node_sequence_id": 0,
    "x": 0.0,   # N1 (0, 0) 출발
    "y": 0.0,
    "theta": 0.0,
}

runner = OrderRunner(robot_state, action_duration_s=settings.action_duration_s, battery=battery)
policy = NullPolicy()  # T6에서 ReferenceSafePolicy로 교체
motion = MotionEngine(runner=runner, policy=policy,
                      speed_mps=settings.speed_mps,
                      dt_s=max(settings.state_period_ms, 500) / 1000.0)


def snapshot_state_payload() -> Dict[str, Any]:
    node_states, edge_states, action_states = runner.route_state()
    with core_lock:
        return builder.build_state(
            op_state=robot_state.op_state.value,
            order_id=core["order_id"],
            order_update_id=core["order_update_id"],
            last_node_id=core["last_node_id"],
            last_node_sequence_id=core["last_node_sequence_id"],
            x=core["x"],
            y=core["y"],
            theta=core["theta"],
            battery_charge=battery.level,
            charging=battery.charging,
            action_states=action_states,
            node_states=node_states,
            edge_states=edge_states,
            errors=robot_state.errors,
        )


def on_order(data: Dict[str, Any]) -> None:
    result = runner.handle_order(data)
    log.info("[order] %s orderId=%s", result, data.get("orderId"))
    if result in ("accepted", "updated"):
        with core_lock:
            core["order_id"] = str(data.get("orderId") or "")
            core["order_update_id"] = int(data.get("orderUpdateId") or 0)


def on_instant_actions(data: Dict[str, Any]) -> None:
    for action in data.get("actions", []):
        action_type = action.get("actionType")
        action_id = action.get("actionId")
        if action_type == "cancelOrder":
            had = runner.cancel()
            if had:
                with core_lock:
                    core["order_id"] = ""
                    core["order_update_id"] = 0
            log.info("[instant] cancelOrder done (had_active=%s) actionId=%s", had, action_id)
        else:
            # faxEStop 등 안전 액션은 T6(safePLC)에서 처리된다
            log.info("[instant] %s received — handling lands in T6 (actionId=%s)", action_type, action_id)


mqtt_client = SimMqttClient(
    identity=identity,
    broker_url=settings.mqtt_broker_url,
    connection_factory=builder.build_connection,
    on_order=on_order,
    on_instant_actions=on_instant_actions,
)


def state_loop() -> None:
    """2Hz: 주행 틱 → state 발행 → visualization 발행 → 배터리 진행."""
    period_s = max(settings.state_period_ms, 500) / 1000.0  # 하한 가드: 2Hz 초과 금지
    while not stop_event.is_set():
        try:
            motion.tick(core, core_lock, robot_state, now=time.monotonic())
            battery.tick()
            manage_low_battery_warning(robot_state, battery, settings.low_battery_threshold)
            payload = snapshot_state_payload()
            mqtt_client.publish(identity.state_topic(), payload, qos=0)
            with core_lock:
                vis = builder.build_visualization(x=core["x"], y=core["y"], theta=core["theta"])
            mqtt_client.publish(identity.visualization_topic(), vis, qos=0)
        except Exception:  # 루프는 절대 죽지 않는다 — 로봇은 발행을 멈추지 않는다
            log.exception("state loop iteration failed")
        stop_event.wait(period_s)


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop_event.clear()
    mqtt_client.start()
    t = threading.Thread(target=state_loop, name="state-publisher", daemon=True)
    t.start()
    log.info(
        "robot-sim up: %s/%s map=%s state_period=%dms speed=%.1fm/s",
        identity.manufacturer, identity.serial_number, identity.map_id,
        settings.state_period_ms, settings.speed_mps,
    )
    yield
    stop_event.set()
    mqtt_client.stop()


app = FastAPI(title="bsm_study_vda5050 robot-sim", lifespan=lifespan)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status() -> Dict[str, Any]:
    with core_lock:
        return {
            "identity": {
                "manufacturer": identity.manufacturer,
                "serialNumber": identity.serial_number,
                "mapId": identity.map_id,
            },
            "position": {
                "x": core["x"], "y": core["y"], "theta": core["theta"],
                "lastNodeId": core["last_node_id"],
            },
            "battery": {"charge": round(battery.level, 1), "charging": battery.charging},
            "opState": robot_state.op_state.value,
            "orderId": core["order_id"],
            "errors": robot_state.errors,
            "mqttConnected": mqtt_client.connected,
        }
