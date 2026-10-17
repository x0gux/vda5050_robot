"""MQTT 클라이언트 래퍼 — paho-mqtt 2.x 콜백 API.

로봇 온보드 입장에서:
  - 발행: state / connection / visualization
  - 구독: order (마스터가 주는 경로), instantActions (마스터가 주는 즉시 동작)
"""
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt

from app.identity import Identity

log = logging.getLogger("robot-sim.mqtt")


def parse_broker_url(url: str) -> tuple:
    """tcp://host:port → (host, port)"""
    raw = url
    if "://" in raw:
        raw = raw.split("://", 1)[1]
    host, _, port = raw.partition(":")
    return host, int(port) if port else 1883


class SimMqttClient:
    def __init__(
        self,
        identity: Identity,
        broker_url: str,
        connection_factory: Callable[[str], Dict[str, Any]],
        on_order: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_instant_actions: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.identity = identity
        self.connection_factory = connection_factory
        self.on_order_cb = on_order
        self.on_instant_actions_cb = on_instant_actions
        self.connected = False

        host, port = parse_broker_url(broker_url)
        self._host, self._port = host, port
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{identity.manufacturer}-{identity.serial_number}-sim",
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=10)
        self._pub_lock = threading.Lock()

    # ---- lifecycle ----
    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=30)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()

    # ---- paho callbacks (v2 signatures) ----
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        log.info("broker connected: %s (rc=%s)", self._host, reason_code)
        self.connected = True
        # 접속 직후 connection ONLINE을 retain으로 남긴다 — 늦게 구독한 관제도 즉시 상태를 받는다.
        self.publish(self.identity.connection_topic(), self.connection_factory("ONLINE"), qos=0, retain=True)
        client.subscribe(self.identity.order_topic(), qos=1)
        client.subscribe(self.identity.instant_actions_topic(), qos=1)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        log.warning("broker disconnected (rc=%s) — 자동 재접속 대기", reason_code)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("non-JSON payload on %s (%dB) — 무시", msg.topic, len(payload))
            return
        if msg.topic == self.identity.order_topic() and self.on_order_cb:
            self.on_order_cb(data)
        elif msg.topic == self.identity.instant_actions_topic() and self.on_instant_actions_cb:
            self.on_instant_actions_cb(data)

    # ---- publishing ----
    def publish(self, topic: str, payload: Dict[str, Any], qos: int = 0, retain: bool = False) -> None:
        with self._pub_lock:
            info = self._client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
            if info.rc == mqtt.MQTT_ERR_NO_CONN:
                log.debug("publish skipped (not connected): %s", topic)
