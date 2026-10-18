# bsm_study_vda5050 — VDA5050 스터디용 가상로봇

VDA5050 표준으로 로봇을 제어하고, 안전정책(safePLC)과 고장 복구를 배우는 **교육용 가상로봇 패키지**입니다.

`docker compose up -d --build` 한 번이면 연습용 MQTT 브로커와 실물처럼 말하는 가상로봇 한 대가 함께 뜹니다.
가상로봇은 다음을 수행합니다:

- **실물처럼 상태 보고** — VDA5050 v2.0.0 `state`(초 2회)·`connection`·`visualization` 발행
- **오더 실행** — `order` 토픽의 노드/엣지 경로를 따라 주행, `instantActions` 수신 (비상정지·취소)
- **에러를 던짐** — 실물에서 관찰되는 형태 그대로: WARNING(obstacle 0x207, STO, 저전압) / ERROR(DriveFault) / FATAL(faxEStop)
- **safePLC 안전정책 내장** — 비상정지 인터락, 장애물 보호정지, 존 속도제한, 통신두절 failsafe
- **고장주입 제어API** — 데모/실습용 REST(포트 8090)

## 3커맨드 퀵스타트

```bash
git clone <this-repo-url> && cd bsm_study_vda5050
docker compose up -d --build
docker compose exec mosquitto mosquitto_sub -h localhost -t 'uagv/#' -v -C 5 -W 15
```

마지막 커맨드에서 로봇의 state가 초 2회씩 흘러나오면 성공입니다.
이제 [STEP0 퀵스타트](docs/02_quickstart.md)부터 시작하세요.

## 아키텍처

```
┌─────────────────────┐   MQTT 1883 (TCP)    ┌──────────────────────────┐
│  study-mosquitto    │◀────────────────────▶│      study-robot-sim     │
│  (MQTT 브로커)       │   MQTT 9001 (WS)     │  VDA5050 가상로봇 (Python)│
└─────────┬───────────┘                      │  ┌────────────────────┐  │
          │                                  │  │ motion (주행)       │  │
          │  uagv/v2/study/SIM-001/#         │  │ order_runner (오더) │  │
          ▼                                  │  │ safeplc (안전정책)  │  │
   당신의 실습 도구:                          │  │ faults (고장주입)   │  │
   mosquitto_sub/pub, MQTTX,                │  └────────────────────┘  │
   or 당신이 만들 뷰어 (docs/08)              │  REST :8090 (제어)        │
                                             └──────────────────────────┘
```

## 커리큘럼

| 문서 | 단계 | 내용 |
| --- | --- | --- |
| [01 VDA5050 기초](docs/01_vda5050_basics.md) | 이론 | 토픽 체계, state/order/instantActions, 에러 레벨 |
| [02 STEP0](docs/02_quickstart.md) | 실습 | 기동과 첫 관찰 |
| [03 STEP1-2](docs/03_exercise_order.md) | 실습 | state 관찰 → 오더로 주행 |
| [04 STEP3](docs/04_exercise_instant_actions.md) | 실습 | 비상정지·오더 취소 |
| [05 STEP4](docs/05_safeplc.md) | 실습 | safePLC: WARNING vs FATAL, 보호정지, 존 속도 |
| [06 STEP5](docs/06_exercise_faults.md) | 실습 | 고장주입 5종과 복구 절차 |
| [07 STEP6](docs/07_advanced_policy.md) | 심화 | 자작 안전정책 구현 (TDD) |
| [08 프론트 트랙](docs/08_frontend_track.md) | 확장 | 웹 뷰어 직접 만들기 (설계 명세) |

부속물: [examples/](examples/) 발행용 예제 페이로드 · [mosquitto 치트시트](examples/mosquitto_cheatsheet.md)

## 📖 명령 레퍼런스 (Swagger 스타일)

**[docs/vda5050_reference.html](docs/vda5050_reference.html)** — 브라우저로 열면:
- 토픽 규칙(`uagv/v2/{manufacturer}/{serialNumber}/{messageType}`)·메시지 필드·명령 카탈로그를 한 화면에서
- 명령마다 **[복사] 버튼** — 터미널에 붙여넣어 바로 실행
- **라이브 콘솔** — 브라우저에서 브로커(WebSocket 9001)에 직접 연결해 state 실시간 관찰 + 버튼으로 오더/E-stop/고장주입 실행 (오프라인 동작, 외부 CDN 없음)
- REST 제어API의 Swagger UI는 별도: <http://localhost:8090/docs>

## 구성 요소

```
robot-sim/           가상로봇 (Python 3.12 + paho-mqtt + FastAPI)
  app/safeplc/       안전정책 엔진 (플러그인 구조 — STEP6에서 여러분이 확장)
  app/               주행·오더·배터리·고장주입·MQTT
  tests/             pytest 44개 (안전정책은 TDD)
mosquitto/           브로커 설정 (1883 MQTT + 9001 WebSocket)
examples/            오더/인스턴트액션 예제 JSON
docs/                한국어 커리큘럼
```

## 자주 쓰는 명령

```bash
docker compose up -d --build          # 기동
docker compose logs -f robot-sim      # 로봇 로그
docker compose run --rm robot-sim pytest   # 전체 테스트 (44개)
docker compose down                   # 종료
```

## 주의

- 이 패키지의 브로커는 **연습용**입니다. 실물 로봇이 붙어 있는 브로커에 절대 연결하지 마세요
  (`MQTT_BROKER_URL` 기본값은 compose 내부 mosquitto로 고정 — 바꾸지 마세요).
- 제어 API(8090)는 인증이 없습니다 — 로컬/교육 환경 전용입니다.
- 로봇 신원을 바꾸고 싶으면 `docker-compose.yml`의 `ROBOT_MANUFACTURER` / `ROBOT_SERIAL`을 수정하세요.
  소문자 제조사를 권장합니다 (VDA5050 토픽 관례).

## 라이선스

MIT — 자유롭게 쓰고, 후배에게 전파하세요.
GitHub에 올릴 때: 저장소 생성 후 `git remote add origin <url> && git push -u origin main`
