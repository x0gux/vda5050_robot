# 02 — STEP0: 환경 준비와 첫 관찰

목표: 패키지를 띄우고, 로봇이 브로커에 하는 말을 **직접 눈으로** 본다.

## 사전 준비

- Docker Desktop 설치 (https://www.docker.com/products/docker-desktop/)
- 터미널에서 `docker --version`이 되는지 확인

## 기동

저장소 루트에서:

```bash
docker compose up -d --build
```

첫 빌드는 몇 분 걸립니다 (Python 이미지 + 패키지 설치). 완료 후 상태 확인:

```bash
docker compose ps
```

`study-mosquitto`와 `study-robot-sim`이 둘 다 healthy/running이면 성공.

## 첫 관찰 — 로봇의 말 듣기

```bash
docker compose exec mosquitto mosquitto_sub -h localhost -t 'uagv/#' -v -C 10 -W 15
```

- `-v`: 토픽 이름을 메시지 앞에 같이 출력
- `-C 10`: 10개 받으면 종료
- `-W 15`: 최대 15초 대기 (끝나지 않는 구독 방지 — 앞으로 항상 붙입니다)

**수용기준**: `uagv/v2/study/SIM-001/state ...` 줄이 초당 약 2개씩 보이고,
그중 `uagv/v2/study/SIM-001/connection ... {"connectionState": "ONLINE"}`이 최초 1회 보여야 합니다.

## state 하나 뜯어보기

```bash
docker compose exec mosquitto mosquitto_sub -h localhost \
  -t "uagv/v2/study/SIM-001/state" -C 1 -W 5 | python3 -m json.tool
```

확인할 것:
1. `headerId`가 이전 캡처보다 큰가? (몇 번 반복해 보세요)
2. `agvPosition`의 x, y가 무엇인가? (기본 출발점 N1 = (0, 0))
3. `batteryState.batteryCharge`가 서서히 줄어드는가? (기본 방전 0.5%/분 — 1분 뒤 다시 캡처해 비교)
4. `errors`가 비어 있는가?

## 제어 API 확인

```bash
curl -s http://localhost:8090/health
curl -s http://localhost:8090/status | python3 -m json.tool
```

## 종료 방법

```bash
docker compose down        # 컨테이너 정지+제거 (데이터 없음, 언제든 다시 up)
docker compose down -v     # + 네트워크/볼륨까지 완전 삭제
```

**수용기준 (STEP0 통과 조건)**
- [ ] `docker compose up -d --build` 후 두 컨테이너 healthy
- [ ] state가 초당 2회 관측됨
- [ ] connection ONLINE 최초 1회 관측
- [ ] `/health`가 `{"status":"ok"}` 반환

---

다음 문서: [03 — STEP1-2 state 관찰과 오더 주행](03_exercise_order.md)
