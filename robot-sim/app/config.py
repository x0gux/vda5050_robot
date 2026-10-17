"""환경설정 — 모든 값은 환경변수로 치환 가능 (docker-compose.yml 참고)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 로봇 신원 (VDA5050 토픽의 {manufacturer}/{serialNumber} 자리에 들어감)
    robot_manufacturer: str = "study"
    robot_serial: str = "SIM-001"

    # MQTT 브로커 (compose 네트워크 안에서는 서비스명 mosquitto로 접속)
    mqtt_broker_url: str = "tcp://mosquitto:1883"

    # state 발행 주기 (ms). VDA5050 관습적으로 최대 10Hz이며, 본 패키지는 2Hz(500ms) 기본.
    state_period_ms: int = 500

    # 좌표계/동작
    map_id: str = "study_map"
    speed_mps: float = 1.0

    # 제어 REST API 포트
    control_api_port: int = 8090

    # 노드 액션(pick/drop 등) 소요 시간 (초)
    action_duration_s: float = 2.0

    # 배터리 (T5에서 충전 관련 값 추가 사용)
    battery_drain_pct_per_min: float = 0.5
    battery_charge_pct_per_min: float = 10.0
    low_battery_threshold: float = 20.0


settings = Settings()
