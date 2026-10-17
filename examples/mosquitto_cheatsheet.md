# mosquitto 치트시트

모든 명령은 저장소 루트에서 실행한다고 가정합니다 (`docker compose`가 브로커를 띄워둔 상태).

## 토픽 지도

| 토픽 | 방향 | 내용 |
| --- | --- | --- |
| `uagv/v2/study/SIM-001/state` | 로봇 → 관제 | 위치·배터리·노드 진행률·에러 (초 2회) |
| `uagv/v2/study/SIM-001/connection` | 로봇 → 관제 | ONLINE / OFFLINE / CONNECTIONBROKEN |
| `uagv/v2/study/SIM-001/visualization` | 로봇 → 관제 | 위치만 (고빈도용) |
| `uagv/v2/study/SIM-001/order` | 관제 → 로봇 | 경로 오더 (nodes/edges) |
| `uagv/v2/study/SIM-001/instantActions` | 관제 → 로봇 | 즉시 동작 (E-stop, 취소) |

## 관찰 (subscribe)

```bash
# 전체 트래픽 훑어보기 (-v는 토픽을 같이 보여줌)
docker compose exec mosquitto mosquitto_sub -h localhost -t 'uagv/#' -v

# state만, 5개 받으면 종료 (-W 5는 최대 5초 대기 — 터미널이 멈추지 않게 항상 쓰세요)
docker compose exec mosquitto mosquitto_sub -h localhost -t "uagv/v2/study/SIM-001/state" -C 5 -W 5

# connection 메시지 (retain되어 있어 구독 즉시 1개 받음)
docker compose exec mosquitto mosquitto_sub -h localhost -t "uagv/v2/study/SIM-001/connection" -C 1 -W 5
```

## 발행 (publish)

```bash
# 오더: N1 → N2 → N3 주행 (examples/order_move_n1_n3.json)
docker cp examples/order_move_n1_n3.json study-mosquitto:/tmp/order.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json

# 충전 오더: N2 → N3 → N4 (N4에서 충전)
docker cp examples/order_charge_n4.json study-mosquitto:/tmp/charge.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/charge.json

# 비상정지 (E-stop)
docker cp examples/instant_actions_estop.json study-mosquitto:/tmp/estop.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/estop.json

# 비상정지 해제
docker cp examples/instant_actions_estop_recover.json study-mosquitto:/tmp/recover.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/recover.json

# 오더 취소
docker cp examples/instant_actions_cancel.json study-mosquitto:/tmp/cancel.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/cancel.json
```

## 제어 REST API (고장주입 · 포트 8090)

```bash
curl -s http://localhost:8090/health
curl -s http://localhost:8090/status | python3 -m json.tool

# 고장 주입: obstacle | sto_warning | drive_error | comm_loss | low_battery
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' \
  -d '{"type": "obstacle", "duration_s": 5}'

curl -s http://localhost:8090/faults           # 현재 활성 고장
curl -s -X POST http://localhost:8090/faults/clear

curl -s -X POST http://localhost:8090/estop \
  -H 'Content-Type: application/json' -d '{"activate": true}'
curl -s -X POST http://localhost:8090/estop \
  -H 'Content-Type: application/json' -d '{"activate": false}'
```

## 노드 좌표표 (mapId: study_map)

| 노드 | x (m) | y (m) | 비고 |
| --- | --- | --- | --- |
| N1 | 0 | 0 | 기본 출발점 |
| N2 | 3 | 0 | |
| N3 | 6 | 0 | |
| N4 | 6 | 3 | 충전 스테이션 |
| N5 | 3 | 3 | |

## 팁

- `mosquitto_sub`에는 항상 `-W <초>`를 붙이세요 — 없으면 터미널이 계속 대기합니다.
- `-C N`은 N개 메시지를 받으면 종료합니다.
- JSON을 예쁘게 보려면 파이프로 `python3 -m json.tool`을 붙이세요.
