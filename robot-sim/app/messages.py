"""VDA5050 v2.0.0 메시지 빌더.

- headerId: 토픽별로 단조 증가 (VDA5050 규약 — 수신 측이 유실/중복을 판별하는 데 사용)
- timestamp: ISO-8601 UTC ('Z' 접미)
- 알 수 없는 필드는 수신 측에서 무시되므로, 우리가 보내는 필드는 항상 표준 이름을 사용한다.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.identity import Identity


def utc_now_iso() -> str:
    """예: 2026-10-18T09:30:00.123Z"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_error(level: str, error_type: str, reference: str, description: str) -> Dict[str, Any]:
    """VDA5050 errors[] 엔트리.

    errorLevel: WARNING | ERROR | FATAL
      - WARNING: 작업 지속 가능 (관제는 주황 표시)
      - ERROR/FATAL(또는 레벨 누락): 관제가 opState=ERROR로 판정
    """
    return {
        "errorLevel": level,
        "errorType": error_type,
        "errorReference": reference,
        "errorDescription": description,
    }


class MessageBuilder:
    def __init__(self, identity: Identity):
        self.identity = identity
        self._header_counters: Dict[str, int] = {}

    def _header(self, topic: str) -> tuple:
        next_id = self._header_counters.get(topic, 0) + 1
        self._header_counters[topic] = next_id
        return next_id, utc_now_iso()

    def build_state(
        self,
        *,
        order_id: str = "",
        order_update_id: int = 0,
        last_node_id: Optional[str] = None,
        last_node_sequence_id: int = 0,
        x: float = 0.0,
        y: float = 0.0,
        theta: float = 0.0,
        battery_charge: float = 100.0,
        charging: bool = False,
        action_states: Optional[List[Dict[str, Any]]] = None,
        node_states: Optional[List[Dict[str, Any]]] = None,
        edge_states: Optional[List[Dict[str, Any]]] = None,
        errors: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        header_id, ts = self._header(self.identity.state_topic())
        return {
            "headerId": header_id,
            "timestamp": ts,
            "version": "2.0.0",
            "manufacturer": self.identity.manufacturer,
            "serialNumber": self.identity.serial_number,
            "orderId": order_id,
            "orderUpdateId": order_update_id,
            "lastNodeId": last_node_id,
            "lastNodeSequenceId": last_node_sequence_id,
            "agvPosition": {
                "x": round(x, 4),
                "y": round(y, 4),
                "theta": round(theta, 2),
                "mapId": self.identity.map_id,
                "positionInitialized": True,
            },
            "batteryState": {"batteryCharge": round(battery_charge, 1), "charging": charging},
            "actionStates": action_states or [],
            "nodeStates": node_states or [],
            "edgeStates": edge_states or [],
            "errors": errors or [],
        }

    def build_connection(self, state: str) -> Dict[str, Any]:
        """connectionState: ONLINE | OFFLINE | CONNECTIONBROKEN"""
        header_id, ts = self._header(self.identity.connection_topic())
        return {
            "headerId": header_id,
            "timestamp": ts,
            "version": "2.0.0",
            "manufacturer": self.identity.manufacturer,
            "serialNumber": self.identity.serial_number,
            "connectionState": state,
        }

    def build_visualization(self, *, x: float, y: float, theta: float) -> Dict[str, Any]:
        header_id, ts = self._header(self.identity.visualization_topic())
        return {
            "headerId": header_id,
            "timestamp": ts,
            "version": "2.0.0",
            "manufacturer": self.identity.manufacturer,
            "serialNumber": self.identity.serial_number,
            "agvPosition": {
                "x": round(x, 4),
                "y": round(y, 4),
                "theta": round(theta, 2),
                "mapId": self.identity.map_id,
                "positionInitialized": True,
            },
        }
