# 03 — STEP1-2: state 관찰 → 오더로 로봇 움직이기

목표: 관제가 로봇을 움직이는 전체 흐름(state 구독 → order 발행 → 진행률 관찰)을 경험한다.

## STEP1 — state 필드 관찰 (오더 없이)

로봇이 대기 중일 때 state를 관찰하며 아래 표를 채워보세요:

```bash
docker compose exec mosquitto mosquitto_sub -h localhost \
  -t "uagv/v2/study/SIM-001/state" -C 1 -W 5 | python3 -m json.tool
```

| 관찰 항목 | 값 | 의미 |
| --- | --- | --- |
| opState | (기록) | |
| agvPosition.x / y | (기록) | |
| lastNodeId | (기록) | |
| batteryState.batteryCharge | (기록) | |
| nodeStates / edgeStates | (기록) | |
| errors | (기록) | |

**기대값**: opState=IDLE, 위치 (0,0)=N1 또는 이전 실습에서 옮겨진 노드, nodeStates/edgeStates **비어 있음**.
nodeStates가 비어 있다는 것 = "하는 일이 없다" = 관제가 IDLE로 판정하는 근거입니다.

## STEP2 — 첫 오더 발행: N1 → N3

오더 페이로드를 브로커에 흘리면 로봇이 달립니다:

```bash
docker cp examples/order_move_n1_n3.json study-mosquitto:/tmp/order.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
```

발행 즉시 주행을 관찰하세요:

```bash
docker compose exec mosquitto mosquitto_sub -h localhost \
  -t "uagv/v2/study/SIM-001/state" -W 25 | python3 -u -c "
import sys, json
prev = None
seen_working = False          # 재실행 시 '이전 완주의 스테일 IDLE'에 걸리지 않는 가드
for line in sys.stdin:
    s = json.loads(line)
    cur = (s['opState'], round(s['agvPosition']['x'], 1), s['lastNodeId'], len(s['nodeStates']))
    if cur != prev:
        print(cur)
        prev = cur
    if cur[0] == 'WORKING':
        seen_working = True
    if seen_working and s['opState'] == 'IDLE' and not s['nodeStates'] and s['orderId']:
        print('완주!'); break
"
```

> 위 스크립트는 로봇 어디에 있든 동작합니다 — 오더의 첫 노드로 먼저 돌아간 뒤 경로를 주행하기 때문입니다.
> 단, 로봇이 이미 그 오더를 **완주한 뒤에** 스트림을 시작하면 WORKING이 안 보일 수 있습니다 —
> 그 경우 오더를 다시 발행하고 바로 스트림을 시작하세요.

**무엇이 보이는가** (예상 출력 흐름):

```
('WORKING', 0.0, 'N1', 3)     ← 오더 수용, nodeStates 3개 채워짐 (관제는 이걸 보고 WORKING 판정)
('WORKING', 0.5, 'N1', 3)     ← 1m/s로 이동
...
('WORKING', 3.0, 'N2', 3)     ← N2 통과: lastNodeId 갱신
...
('WORKING', 6.0, 'N3', 3)     ← 마지막 노드 도달
('IDLE', 6.0, 'N3', 0)        ← 완주: nodeStates 클리어 → 관제는 IDLE로 전환 감지
```

### 관찰 포인트 (이것이 VDA5050의 핵심)

1. **lastNodeId는 도달할 때만 바뀐다** — 이동 중에는 직전 노드를 유지합니다.
2. **nodeStates/edgeStates가 "하는 일"의 증거**입니다 — 관제는 이걸 보고 WORKING을 판정합니다.
3. **완주는 이벤트가 아니라 상태 전이**입니다 — "WORKING이던 로봇이 같은 orderId로 IDLE이 되었다" = 완료.
4. theta가 이동 방향(라디안→도)을 따라가는 것도 확인하세요. N1→N3은 +x 방향이라 theta=0입니다.

### 시간 재어보기

N1→N3은 6m이고 기본 속도는 1m/s. 대략 몇 초 걸릴지 예측해보고, 실제 측정과 비교해보세요
(노드 체류 틱 때문에 약간 더 걸립니다 — 왜인지 생각해보세요).

## 심화 — 경로 바꾸기 (orderUpdateId)

주행 중에 같은 orderId로 `orderUpdateId`를 1 올린 오더를 보내면 로봇이 경로를 교체합니다.
`examples/order_move_n1_n3.json`의 `orderUpdateId`를 1로 고치고 orderId를 동일하게 유지해 발행해 보세요.
(직접 해보기 과제 — state에서 `orderUpdateId`가 1로 바뀌는지 확인)

## 실패 케이스도 체험

주행 중인 로봇에게 **다른 orderId**의 오더를 발행하면 거절됩니다:

```bash
# 주행 시작
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
sleep 1
# 다른 orderId를 가진 사본을 만들어 발행 → busy 거절
sed 's/ORDER-MOVE-N1-N3/ORDER-OTHER/' examples/order_move_n1_n3.json > /tmp/order2.json
docker cp /tmp/order2.json study-mosquitto:/tmp/order2.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order2.json
sleep 0.5
docker compose logs robot-sim --tail 5
```

> 반대로 **같은 orderId**를 다시 보내면 "거절"이 아니라 `ignored: stale orderUpdateId`
> (중복 무시)로 처리됩니다 — QoS1에서 같은 메시지가 두 번 오는 상황을 로봇이 흡수하는 장치입니다.

**수용기준 (STEP1-2 통과 조건)**
- [ ] IDLE 상태에서 nodeStates/edgeStates가 비어 있음을 관측
- [ ] 오더 발행 → WORKING 전이 + x가 0→6 증가 관측
- [ ] lastNodeId가 N1→N2→N3 순서로만 바뀜
- [ ] 최종 IDLE + nodeStates 클리어
- [ ] 주행 중 타 오더 발행 시 거절 로그 확인

---

다음 문서: [04 — STEP3 instantActions](04_exercise_instant_actions.md)
