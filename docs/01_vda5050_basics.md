# 01 — VDA5050 기초

VDA5050은 AGV/AMR(무인운반로봇)과 마스터 컨트롤(관제) 사이의 통신을 표준화한 인터페이스입니다(버전 2.0 기준).
핵심 아이디어는 단순합니다: **로봇은 MQTT 토픽으로 자기 상태를 계속 알리고, 관제는 그 로봇의 토픽으로 명령(오더)을 던진다.**

## 토픽 체계

```
uagv/v2/{manufacturer}/{serialNumber}/{메시지 타입}
```

본 패키지의 로봇은 `manufacturer=study`, `serialNumber=SIM-001`이므로:

| 토픽 | 방향 | 역할 |
| --- | --- | --- |
| `uagv/v2/study/SIM-001/state` | 로봇 → 관제 | 상태 보고 (위치/배터리/진행률/에러) — 초 2회 |
| `uagv/v2/study/SIM-001/connection` | 로봇 → 관제 | ONLINE / OFFLINE / CONNECTIONBROKEN |
| `uagv/v2/study/SIM-001/visualization` | 로봇 → 관제 | 위치 스트림 (지도 그리기용) |
| `uagv/v2/study/SIM-001/order` | 관제 → 로봇 | 경로 오더 |
| `uagv/v2/study/SIM-001/instantActions` | 관제 → 로봇 | 즉시 동작 (비상정지, 오더 취소 등) |

## state 메시지 — 가장 중요한 메시지

```json
{
  "headerId": 84,                       ← 토픽별로 1씩 증가 (유실/중복 판별)
  "timestamp": "2026-10-18T00:00:00.123Z",
  "version": "2.0.0",
  "manufacturer": "study",
  "serialNumber": "SIM-001",
  "opState": "WORKING",                 ← IDLE | WORKING | ERROR
  "orderId": "ORDER-MOVE-N1-N3",        ← 현재 수행 중인 오더
  "orderUpdateId": 0,                   ← 오더 갱신 버전
  "lastNodeId": "N2",                   ← 마지막으로 통과한 노드
  "lastNodeSequenceId": 3,
  "agvPosition": { "x": 3.0, "y": 0.0, "theta": 0.0, "mapId": "study_map", "positionInitialized": true },
  "batteryState": { "batteryCharge": 98.4, "charging": false },
  "actionStates": [ { "actionId": "charge-1", "actionType": "charge", "actionStatus": "RUNNING" } ],
  "nodeStates": [ { "nodeId": "N1", "sequenceId": 1, "nodeStatus": "FINISHED" }, ... ],
  "edgeStates": [ { "sequenceId": 2, "edgeStatus": "RUNNING" }, ... ],
  "errors": []
}
```

### headerId 규칙

- 토픽마다 **독립적으로** 1부터 단조 증가합니다.
- 수신 측(관제)은 headerId가 건너뛰면 "유실 발생", 뒤로 가면 "구버전 메시지"로 판단합니다.
- 직접 확인: `mosquitto_sub`로 state를 몇 초 보면 headerId가 계속 올라가는 걸 볼 수 있습니다.

### opState는 어디서 오나?

VDA5050 표준은 opState 필드를 정의하지 않습니다 — 관제가 **내용으로부터 추론**합니다:
- `errors[]`에 FATAL/ERROR 레벨이 하나라도 있으면 → ERROR
- nodeStates/edgeStates/actionStates에 진행 중인 게 있으면 → WORKING
- 아니면 → IDLE

본 시뮬레이터는 학습 편의를 위해 이 추론 결과를 `opState` 필드로 같이 실어 보냅니다
(실제 관제 시스템도 같은 방식으로 판정합니다 — 표준은 "판정 재료"를 줄 뿐입니다).

## errors[] — 에러 레벨의 의미

```json
{ "errorLevel": "WARNING", "errorType": "obstacle", "errorReference": "0x207", "errorDescription": "There are obstacles around" }
```

| errorLevel | 관제 해석 | 로봇 행동 (본 패키지의 safePLC) |
| --- | --- | --- |
| WARNING | 노랑 — "참고" | **작업 지속** (단, 장애물·STO처럼 위험한 것은 보호정지/감속) |
| ERROR | 빨강 — 작업 실패 | 주행 차단, 해제 대기 |
| FATAL | 빨강 — 즉시 대응 | 즉시 정지 + 인터락 |

- `errorType`: 에러 종류 식별자 (예: faxEStop, obstacle, DriveFault, BatteryLow, STO)
- `errorReference`: 코드 (예: 0x207 — 실제 AMR에서 관찰되는 STO 관련 코드)
- `errorDescription`: 사람이 읽는 설명

**교육 포인트**: WARNING은 "화면에는 띄우되 작업은 계속"이 관례입니다. FATAL까지 빨갛게 띄우면
태스크가 오중단됩니다. 실제 운영 현장에서도 같은 원리를 씁니다.

## order 메시지 — 경로는 노드+엣지

```json
{
  "orderId": "ORDER-MOVE-N1-N3",
  "orderUpdateId": 0,
  "nodes": [ { "nodeId": "N1", "sequenceId": 1, "nodePosition": {"x": 0, "y": 0, "mapId": "study_map"}, "actions": [] },
             { "nodeId": "N2", "sequenceId": 3, ... } ],
  "edges": [ { "sequenceId": 2, "startNodeId": "N1", "endNodeId": "N2", "released": true } ]
}
```

- **sequenceId**: 노드/엣지의 실행 순서. 오더 전체에서 단조 증가합니다 (보통 노드 1,3,5 / 엣지 2,4).
- **orderUpdateId**: 같은 orderId로 경로를 바꿀 때 1씩 올립니다. 로봇은 더 큰 updateId만 받아들입니다.
- **released**: 부분 오더(horizon)에서 "이 구간은 실행해도 됨" 표시. 본 패키지는 항상 true.
- **actions**: 노드에 도달하면 실행할 동작 (pick/drop/charge 등).

## instantActions — 오더 밖의 즉시 동작

경로와 무관하게 즉시 수행해야 하는 동작:

| actionType | 의미 |
| --- | --- |
| faxEStop | 비상정지 activate=true → 즉시 정지. activate=false → 해제 |
| cancelOrder | 현재 오더 폐기 |

## connection — 왜 OFFLINE을 따로 알리나

로봇이 브로커와 끊기면 state도 못 보냅니다. 그래서 관제는 "마지막 state가 언제 왔는가"로
오프라인을 판단하거나, 로봇이 복구 시 `connectionState: ONLINE`을 다시 보내며 복귀를 알립니다.
STEP5에서 통신두절 고장을 주입해 이 현상을 직접 볼 것입니다.

## 수용기준 (읽기 이해 체크리스트)

- [ ] 토픽 5종의 방향(로봇→관제 / 관제→로봇)을 말할 수 있다
- [ ] headerId가 "토픽별 단조 증가"인 이유를 설명할 수 있다
- [ ] opState가 표준 필드가 아니라 "관제가 추론한 값"임을 설명할 수 있다
- [ ] WARNING과 FATAL의 관제 해석 차이를 말할 수 있다
- [ ] order의 sequenceId와 orderUpdateId의 역할을 구분할 수 있다

---

다음 문서: [02 — STEP0 퀵스타트](02_quickstart.md)
