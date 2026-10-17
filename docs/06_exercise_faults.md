# 06 — STEP5: 고장주입과 복구 절차

목표: 실물 로봇에서 실제로 일어나는 고장을 안전하게 재현하고, **관제 관점에서 어떻게 보이는지**,
복구 절차는 무엇인지 익힌다.

## 왜 고장을 내나

모니터링 시스템을 만드는 사람이 제일 어려워하는 것은 "정상 동작"이 아니라 **이상 상태의 판별**입니다.
고장을 마음대로 재현할 수 있어야 화면·알림·복구 절차를 검증할 수 있습니다.

고장은 제어 REST API(포트 8090)로 주입합니다. 모든 고장은 `duration_s` 후 자동 해제되거나
`/faults/clear`로 즉시 해제할 수 있습니다.

## 시나리오 카탈로그

| type | 재현하는 실물 고장 | 관측되는 것 |
| --- | --- | --- |
| `obstacle` | 주행 경로의 장애물 (사람/파렛트) | WARNING obstacle(0x207) + 보호정지 |
| `sto_warning` | 충전 도킹 중 STO 워닝 | WARNING STO(0x207) + 절반 속도 (작업 지속) |
| `drive_error` | 구동유닛 고장 | ERROR DriveFault(DRV-002) + opState ERROR |
| `comm_loss` | 와이파이 끊김 | state 발행 중단 → 관제에서 OFFLINE처럼 보임 |
| `low_battery` | 배터리 급방전 | 배터리 12% + WARNING BatteryLow(BAT-001) |

## 실습 1 — 통신 두절 (가장 실무적인 시나리오)

```bash
# 복구 후 모니터링용: connection 토픽 구독 시작 (다른 터미널)
docker compose exec mosquitto mosquitto_sub -h localhost \
  -t "uagv/v2/study/SIM-001/connection" -C 1 -W 10

# 통신 두절 주입 (3초)
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' -d '{"type": "comm_loss", "duration_s": 3}'
```

구독 창에서 `connectionState: ONLINE`이 재발행되는 것(복구 마커)을 확인하세요.
3초 동안 state가 완전히 끊기는 것도 관찰하세요:

```bash
docker compose exec mosquitto mosquitto_sub -h localhost \
  -t "uagv/v2/study/SIM-001/state" -W 3 | wc -l    # 0이 나와야 함 (주입 중이라면)
```

**논의 과제**: 관제 화면에서 로봇이 갑자기 사라지면(타임아웃) 어떻게 표시할까?
OFFLINE과 CONNECTIONBROKEN을 구분해야 할까? 그 이유는?

## 실습 2 — 구동유닛 고장 (ERROR 레벨)

```bash
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' -d '{"type": "drive_error", "duration_s": 3}'
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
# → opState ERROR + DriveFault(DRV-002)
```

이 상태에서 주행을 시도해도 safePLC가 이동을 차단합니다. 3초 후 자동 해제되면 IDLE 복귀.

## 실습 3 — 저전압 + 충전 복구 사이클

```bash
# 1) 저전압 강제
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' -d '{"type": "low_battery", "duration_s": 30}'
sleep 1
curl -s http://localhost:8090/status | python3 -c "import sys,json; s=json.load(sys.stdin); print(s['battery'], s['errors'])"
# → batteryCharge 12.0 + BatteryLow WARNING

# 2) 충전 스테이션으로 (N4)
docker cp examples/order_charge_n4.json study-mosquitto:/tmp/charge.json
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/charge.json

# 3) 충전 시작 → BatteryLow 해제, batteryCharge 상승 관찰
```

**교육 포인트**: 저전압 경고는 충전이 시작되면 사라집니다(미충전 조건이 아니라서).
경고의 "해제 조건"을 설계할 때는 항상 "무엇이 이 경고를 끄는가"를 정의해야 합니다.

## 실습 4 — 자동 고장 모드 (카오스 테스트 맛보기)

```bash
curl -s -X POST http://localhost:8090/auto-faults \
  -H 'Content-Type: application/json' \
  -d '{"enabled": true, "interval_s": 10}'
# 30초쯤 지켜본 뒤:
curl -s http://localhost:8090/faults
curl -s -X POST http://localhost:8090/auto-faults \
  -H 'Content-Type: application/json' -d '{"enabled": false}'
curl -s -X POST http://localhost:8090/faults/clear
```

**수용기준 (STEP5 통과 조건)**
- [ ] 5종 고장을 각각 주입 → 예상 표시(WARNING/ERROR/무음/저전압) 확인
- [ ] comm_loss 중 state 0건 + 복구 마커 관찰
- [ ] 저전압 → 충전 → 경고 해제 사이클 완주
- [ ] "각 고장의 해제 조건"을 표로 정리할 수 있음

---

다음 문서: [07 — STEP6 자작 안전정책](07_advanced_policy.md)
