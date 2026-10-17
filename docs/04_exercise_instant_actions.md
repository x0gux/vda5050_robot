# 04 — STEP3: instantActions — 비상정지와 오더 취소

목표: 경로와 무관하게 즉시 동작을 지시하는 instantActions를 익힌다.

## 준비 — 주행 중인 상태 만들기

```bash
docker cp examples/order_move_n1_n3.json study-mosquitto:/tmp/order.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
sleep 2    # 주행 중 상태 (x ≈ 1~2)
```

## 오더 취소 (cancelOrder)

```bash
docker cp examples/instant_actions_cancel.json study-mosquitto:/tmp/cancel.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/cancel.json
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
```

**확인**: opState가 IDLE로 돌아오고 orderId가 비어 있음. 위치는 취소 순간에 멈춰 있습니다.

## 비상정지 (faxEStop)

주행 중에 E-stop을 날려봅니다:

```bash
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
sleep 2
docker cp examples/instant_actions_estop.json study-mosquitto:/tmp/estop.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/estop.json
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
```

**확인할 것**:
1. `errors[]`에 `{"errorLevel": "FATAL", "errorType": "faxEStop", "errorReference": "ESTOP-001"}`이 들어옴
2. opState가 ERROR
3. orderId가 비어 있음 — **E-stop은 활성 오더를 폐기합니다** (안전 최우선)
4. 위치가 멈춰 있음

## 비상정지 해제 (recover)

```bash
docker cp examples/instant_actions_estop_recover.json study-mosquitto:/tmp/recover.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/instantActions" -f /tmp/recover.json
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
```

**확인**: FATAL 에러가 사라지고 IDLE 복귀. 단, 오더는 이미 폐기되어 **주행이 자동 재개되지 않습니다** —
다시 이동하려면 새 오더를 발행해야 합니다. (이것이 STEP4에서 배울 "인터락"의 일부입니다)

## cancelOrder vs faxEStop — 무엇이 다른가

| | cancelOrder | faxEStop (activate) |
| --- | --- | --- |
| 목적 | 작업 취소 (업무 판단) | 안전 확보 (위험 대응) |
| 에러 발생 | 없음 | FATAL |
| opState | IDLE | ERROR |
| 해제 절차 | 필요 없음 | activate=false 필요 |
| 복구 후 | 바로 새 오더 가능 | 오더는 이미 폐기됨 |

**수용기준 (STEP3 통과 조건)**
- [ ] cancelOrder → 즉시 IDLE + orderId 클리어
- [ ] faxEStop activate → FATAL 에러 + opState ERROR + 오더 폐기
- [ ] faxEStop deactivate → 에러 클리어 + IDLE
- [ ] 두 동작의 차이를 말로 설명할 수 있음

---

다음 문서: [05 — STEP4 safePLC](05_safeplc.md)
