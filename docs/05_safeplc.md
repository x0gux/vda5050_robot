# 05 — STEP4: safePLC — 로봇 안의 안전 컨트롤러

목표: "안전PLC(Safety PLC)"가 무엇이고, 본 시뮬레이터의 safePLC 정책 엔진이 어떻게
같은 일을 하는지 이해하고 직접 관찰한다.

## 안전PLC란?

공장의 일반 PLC는 "컨베이어 돌려", "문 열어" 같은 **작업**을 제어합니다.
안전PLC(Safety PLC)는 그 위에 **사람과 설비를 지키는 규칙**을 담당합니다:

- 비상정지 버튼이 눌리면 → 무조건 정지 (다른 로직이 뭘 하든)
- 안전문이 열리면 → 위험한 동작 금지
- 정지 해제 후에도 → 사람이 확인 절차를 밟기 전까지 재가동 금지 (인터락)

핵심 성질: **안전 로직은 작업 로직보다 우선한다. 그리고 실패하지 않도록 단순하게 만든다.**

## 본 패키지의 safePLC

`robot-sim/app/safeplc/`이 그 역할입니다. 구조:

```
app/safeplc/base.py        계약: SafeContext(상태 스냅샷) → SafeVerdict(판정)
app/safeplc/reference.py   참조구현: 아래 규칙들
app/instant_actions.py     진입점: MQTT instantActions과 REST /estop이 같은 경로 사용
app/motion.py              불변식: allow_move == true일 때만 주행
```

참조구현의 규칙 (우선순위 순):

| 우선순위 | 상황 | 판정 | 에러 |
| --- | --- | --- | --- |
| 1 | 비상정지 (faxEStop activate) | **이동 금지** | FATAL faxEStop (ESTOP-001) |
| 2 | 장애물 감지 | **보호정지** (오더는 유지) | WARNING obstacle (0x207) |
| 3 | 통신 두절 | 로컬 정지 | (없음 — 보낼 통로가 없음) |
| 4 | 존 내부 | 속도 상한 | (없음) |
| 5 | DriveFault 활성 | 이동 금지 | (고장주입이 이미 부여) |
| 5 | STO 워닝 활성 | 속도 50% 상한 | (고장주입이 이미 부여) |

**불변식**: 주행 모터는 `SafeVerdict.allow_move == true`일 때만 구동됩니다.
이것이 안전PLC의 본질 — "작업 로직이 아무리 달라고 해도, 안전이 아니오라면 안 간다."

## 실습 1 — WARNING과 FATAL의 차이를 눈으로

STEP3에서 E-stop(FATAL)을 이미 했습니다. 이제 WARNING 계열을 관찰합니다:

```bash
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' -d '{"type": "sto_warning", "duration_s": 5}'
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
```

- STO 워닝(0x207)이 WARNING으로 뜨지만 opState는 **ERROR가 아닙니다** (레벨이 WARNING이라).
- 이 상태에서 오더를 내리면 로봇은 **절반 속도로** 주행합니다 (정지는 아님 — 충전 도킹 중 관찰되는 실제 사례).

```bash
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
# 주행을 관찰하며 0.5m/틱이 아니라 0.25m/틱으로 느려지는지 state에서 확인
```

비교: STEP3의 E-stop은 FATAL + 즉시 정지 + 오더 폐기였습니다.

## 실습 2 — 장애물 보호정지: 멈추지만 버리지는 않는다

```bash
docker compose exec mosquitto mosquitto_pub -h localhost \
  -t "uagv/v2/study/SIM-001/order" -f /tmp/order.json
sleep 2
curl -s -X POST http://localhost:8090/faults \
  -H 'Content-Type: application/json' -d '{"type": "obstacle", "duration_s": 3}'
sleep 1
curl -s http://localhost:8090/status | python3 -m json.tool
# → WARNING obstacle(0x207) + 위치 동결 + opState는 WORKING 유지 (오더가 살아 있음)
```

장애물이 사라지면(duration 경과):

```bash
sleep 3
curl -s http://localhost:8090/status | python3 -m json.tool
# → WARNING 제거 + 같은 오더로 주행 재개 → 완주
```

**교육 포인트**: E-stop은 오더를 버리고(FATAL, ERROR), 장애물은 오더를 유지한다(WARNING, WORKING).
실물 AMR도 장애물 회피 후 원래 경로를 계속 갑니다.

## 실습 3 — 존 속도제한

환경변수 `SAFETY_ZONES`로 안전 존을 정의할 수 있습니다. 예를 들어 N2 주변 반경 1.5m를 0.3m/s로
제한하려면 `docker-compose.yml`의 robot-sim 환경에:

```yaml
- SAFETY_ZONES=[{"name":"hazard","center":{"x":3,"y":0},"radius_m":1.5,"max_speed_mps":0.3}]
```

를 추가하고 `docker compose up -d robot-sim`으로 재기동한 뒤, N1→N3 오더를 내리고
x가 1.5~4.5 구간(존 내부)에서만 느려지는지 state로 관찰하세요.

## safePLC가 맞았는지 어떻게 아나 — 테스트

`robot-sim/tests/test_safeplc.py`가 정책의 모든 규칙을 검증합니다 (TDD로 작성됨):

```bash
docker compose run --rm robot-sim pytest tests/test_safeplc.py -v
```

**수용기준 (STEP4 통과 조건)**
- [ ] STO 워닝: WARNING 표시 + 작업 지속 + 절반 속도 관찰
- [ ] 장애물: WARNING + 보호정지 + 해제 시 같은 오더로 재개 관찰
- [ ] E-stop(비교): FATAL + 오더 폐기
- [ ] "WARNING은 계속, FATAL은 멈춘다"를 예시와 함께 설명할 수 있음
- [ ] safePLC 테스트가 그린인지 확인

---

다음 문서: [06 — STEP5 고장주입과 복구](06_exercise_faults.md)
