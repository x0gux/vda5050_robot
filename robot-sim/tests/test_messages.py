"""T3 검증: VDA5050 메시지 빌더/배터리/상태머신 기본 계약."""
import re

from app.battery import BatteryModel
from app.identity import Identity
from app.messages import MessageBuilder, utc_now_iso
from app.state_machine import OpState, RobotState

IDENTITY = Identity(manufacturer="study", serial_number="SIM-001", map_id="study_map")

REQUIRED_STATE_KEYS = {
    "headerId", "timestamp", "version", "manufacturer", "serialNumber",
    "orderId", "orderUpdateId", "lastNodeId", "lastNodeSequenceId",
    "agvPosition", "batteryState", "actionStates", "nodeStates", "edgeStates", "errors",
}
REQUIRED_AGV_POSITION_KEYS = {"x", "y", "theta", "mapId", "positionInitialized"}
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_state_envelope_has_all_required_keys():
    builder = MessageBuilder(IDENTITY)
    state = builder.build_state()
    assert REQUIRED_STATE_KEYS.issubset(state.keys())
    assert REQUIRED_AGV_POSITION_KEYS.issubset(state["agvPosition"].keys())
    assert state["version"] == "2.0.0"
    assert state["manufacturer"] == "study"
    assert state["serialNumber"] == "SIM-001"
    assert state["agvPosition"]["positionInitialized"] is True
    assert {"batteryCharge", "charging"} == set(state["batteryState"].keys())


def test_header_id_strictly_increases_per_topic():
    builder = MessageBuilder(IDENTITY)
    first = builder.build_state()["headerId"]
    second = builder.build_state()["headerId"]
    assert second == first + 1

    # 토픽별 카운터는 독립이다 (state 카운터가 connection에 영향 X)
    conn = builder.build_connection("ONLINE")
    assert conn["headerId"] == 1
    another_state = builder.build_state()["headerId"]
    assert another_state == second + 1


def test_timestamp_format_iso8601_utc():
    builder = MessageBuilder(IDENTITY)
    assert TIMESTAMP_RE.match(utc_now_iso())
    assert TIMESTAMP_RE.match(builder.build_state()["timestamp"])


def test_connection_payload_online():
    builder = MessageBuilder(IDENTITY)
    conn = builder.build_connection("ONLINE")
    assert conn["connectionState"] == "ONLINE"
    assert TIMESTAMP_RE.match(conn["timestamp"])
    assert conn["headerId"] == 1  # connection 토픽의 첫 메시지


def test_battery_linear_drain_and_low_flag():
    battery = BatteryModel(level=100.0, drain_pct_per_min=60.0)  # 1%/초로 가속 테스트
    battery.tick()  # 첫 틱은 기준점만 설정
    start = battery.level
    import time
    time.sleep(1.1)
    level = battery.tick()
    assert 0 < start - level <= 2.5  # 대략 1%/초
    assert not battery.is_low
    battery.level = 10.0
    assert battery.is_low  # 20% 미만 & 미충전
    battery.charging = True
    assert not battery.is_low  # 충전 중이면 저전압 플래그 해제


def test_robot_state_error_idempotency_and_op_state():
    state = RobotState()
    state.add_error("WARNING", "obstacle", "0x207", "There are obstacles around")
    state.add_error("WARNING", "obstacle", "0x207", "There are obstacles around")  # 중복 무시
    assert len(state.errors) == 1

    assert state.recalculate_op_state(working=False) == OpState.IDLE  # WARNING은 작업 지속
    state.add_error("FATAL", "faxEStop", "ESTOP-001", "emergency stop activated")
    assert state.recalculate_op_state(working=False) == OpState.ERROR
    state.remove_error("faxEStop")
    assert state.recalculate_op_state(working=False) == OpState.IDLE
