# 08 — 프론트엔드 확장 트랙 (뷰어를 만들고 싶은 당신에게)

> 이 문서는 **설계 명세**입니다. 뷰어 코드는 일부러 포함하지 않았습니다 — 만드는 사람은 당신입니다.
> 이 패키지의 가상로봇은 MQTT로 모든 것을 말하기 때문에, 브라우저에서도 같은 언어를 하면 됩니다.

## 목표

브라우저에서 로봇을 실시간으로 보고 클릭으로 제어하는 웹 뷰어:

- 지도(노드 N1~N5) + 로봇 마커 실시간 이동 (초 2회 갱신)
- 로봇 상태 표시 (opState 색상: IDLE 초록 / WORKING 파랑 / ERROR 빨강)
- 배터리 게이지 + 충전 표시
- 에러 뱃지 (WARNING 주황 / FATAL·ERROR 빨강)
- 버튼: 오더 발행(N1→N3, 충전), 비상정지/해제, 오더 취소

## 연결 방법 — 브라우저도 MQTT를 한다

mosquitto가 WebSocket(포트 9001)을 이미 열어두었습니다 (`mosquitto/mosquitto.conf` 참고).
브라우저에서는 mqtt.js를 씁니다:

```js
// npm install mqtt
import mqtt from "mqtt";

const client = mqtt.connect("ws://localhost:9001");   // WebSocket 엔드포인트

client.on("connect", () => {
  client.subscribe("uagv/v2/study/SIM-001/#");
});

client.on("message", (topic, payload) => {
  const msg = JSON.parse(payload.toString());
  // topic 끝부분으로 메시지 종류 판별: .../state | .../connection | .../visualization
});
```

명령 보내기도 같습니다:

```js
client.publish("uagv/v2/study/SIM-001/instantActions",
  JSON.stringify(estopPayload));
```

## 구독해야 할 토픽과 데이터

| 토픽 | 용도 | 갱신 주기 |
| --- | --- | --- |
| `uagv/v2/study/SIM-001/state` | 위치/상태/배터리/에러 전부 | 500ms |
| `uagv/v2/study/SIM-001/connection` | 온라인 여부 (retain) | 이벤트성 |

state 메시지 스키마 (필드별 의미는 [01 문서](01_vda5050_basics.md)):

```json
{
  "opState": "WORKING",
  "agvPosition": { "x": 3.0, "y": 0.0, "theta": 0.0, "mapId": "study_map" },
  "batteryState": { "batteryCharge": 98.4, "charging": false },
  "lastNodeId": "N2",
  "nodeStates": [{ "nodeId": "N1", "nodeStatus": "FINISHED" }],
  "errors": [{ "errorLevel": "WARNING", "errorType": "obstacle", "errorReference": "0x207", "errorDescription": "..." }]
}
```

## 지도 좌표계

| 노드 | x (m) | y (m) |
| --- | --- | --- |
| N1 | 0 | 0 |
| N2 | 3 | 0 |
| N3 | 6 | 0 |
| N4 | 6 | 3 |
| N5 | 3 | 3 |

- 화면 렌더 시: `px = x * scale + offsetX`, `py = y * -scale + offsetY` (y축 뒤집기 주의)
- 로봇 theta(도)는 +x축 기준 시계반대방향입니다 — 화면 좌표계에서는 부호를 뒤집어야 할 수 있습니다.

## 명령 전송 (버튼 → 토픽)

| 버튼 | 토픽 | 페이로드 |
| --- | --- | --- |
| 이동 (N1→N3) | `.../order` | `examples/order_move_n1_n3.json` 내용 |
| 충전 | `.../order` | `examples/order_charge_n4.json` 내용 |
| 비상정지 | `.../instantActions` | `examples/instant_actions_estop.json` |
| 해제 | `.../instantActions` | `examples/instant_actions_estop_recover.json` |
| 취소 | `.../instantActions` | `examples/instant_actions_cancel.json` |

예제 JSON 파일들이 그대로 페이로드입니다 — fetch로 읽어와 publish하면 됩니다.

## 구현 제안 (순서대로)

1. mqtt.js로 state 구독 → 콘솔에 JSON 출력 (연결 자체 확인)
2. div 하나로 로봇 위치 렌더 (absolute positioning)
3. 노드 N1~N5를 원으로 그리고 edge를 선으로
4. opState에 따라 마커 색상
5. errors 배지 + connection OFFLINE 시 회색 처리
6. 버튼으로 예제 페이로드 publish
7. (도전) 최근 state 히스토리 그래프 — 배터리 곡선

## 힌트와 주의

- **React/Next/Vue/svelte 자유** — mqtt.js는 어디서든 돌아갑니다.
- state가 초 2회 오므로 상태 관리 단순하게: 최신 state 1개만 유지해도 충분합니다.
- WebSocket은 `ws://localhost:9001` — HTTPS로 서빙하면 `wss://` 필요 (로컬 개발은 ws).
- 오더/인스턴트액션 페이로드의 `headerId`, `timestamp`는 로봇이 입력으로는 무시하지만
  형식은 지키세요 (예제 파일이 규격입니다).
- 고장주입 버튼도 만들고 싶다면 그건 REST(8090)입니다 — MQTT가 아닙니다.

## 수용기준 (완성의 정의 — 제안)

- [ ] 브라우저에서 로봇이 실시간으로 움직이는 것이 보인다
- [ ] 오더 버튼으로 로봇을 움직일 수 있다
- [ ] E-stop 버튼이 즉시 반영된다 (빨간 마커)
- [ ] 고장주입 중 상태 색과 배지가 바뀐다
- [ ] 새로고침해도 connection retain 덕에 즉시 상태가 그려진다

막히면 `examples/mosquitto_cheatsheet.md`의 관찰 명령으로 브라우저가 받는 데이터를 먼저 확인하세요.
