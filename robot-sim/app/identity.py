"""로봇 신원과 VDA5050 토픽 체계.

VDA5050 토픽 규약:
    uagv/v2/{manufacturer}/{serialNumber}/state
    uagv/v2/{manufacturer}/{serialNumber}/connection
    uagv/v2/{manufacturer}/{serialNumber}/visualization
    uagv/v2/{manufacturer}/{serialNumber}/order              (마스터 → 로봇)
    uagv/v2/{manufacturer}/{serialNumber}/instantActions     (마스터 → 로봇)
"""
from dataclasses import dataclass


@dataclass
class Identity:
    manufacturer: str
    serial_number: str
    map_id: str

    def _base(self) -> str:
        return f"uagv/v2/{self.manufacturer}/{self.serial_number}"

    def state_topic(self) -> str:
        return f"{self._base()}/state"

    def connection_topic(self) -> str:
        return f"{self._base()}/connection"

    def visualization_topic(self) -> str:
        return f"{self._base()}/visualization"

    def order_topic(self) -> str:
        return f"{self._base()}/order"

    def instant_actions_topic(self) -> str:
        return f"{self._base()}/instantActions"
