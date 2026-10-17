# 07 — STEP6 (심화): 나만의 안전정책 만들기

목표: 참조구현을 읽고, SafePolicy 인터페이스를 구현한 **자신만의 안전정책**을 만들고 테스트로 증명한다.

## 준비 — 참조구현 읽기

`robot-sim/app/safeplc/reference.py` 전체를 읽어보세요. 코드가 100줄이 안 됩니다.
핵심은 이 한 메서드입니다:

```python
def evaluate(self, ctx: SafeContext) -> SafeVerdict:
    ...
    return SafeVerdict(allow_move=..., max_speed_mps=...,
                       new_errors=[...], clear_error_types=[...])
```

- **입력 SafeContext**: 위치, 요청 속도, E-stop 여부, 장애물 여부, 통신 상태, 속한 존, 활성 에러 목록
- **출력 SafeVerdict**: 움직여도 되는가 / 속도 상한 / 새로 켤 에러 / 끌 에러

**주행 코드는 정책이 뭐라고 하든 `allow_move == true`일 때만 움직입니다.**
이것이 바로 안전 로직과 작업 로직의 분리입니다.

## 과제: 새로운 안전 규칙 2개 구현

### 과제 A — 야간 감속 (시간대 속도제한)

"22:00~06:00 사이에는 최대 속도를 0.5m/s로 제한한다"는 규칙을 추가하세요.

힌트:
- `SafeContext`에 필드를 추가하는 대신, 정책 생성자에 `night_speed_mps`와 시간 판단 함수를 주입하세요.
- 순수 파이썬 정책 유닛 테스트는 실제 시계가 필요 없습니다 — 시간 함수를 가짜(fake)로 주입하세요.

### 과제 B — 배터리 예비 구간 (보수적 주행)

"배터리가 30% 미만이면 최대 속도를 0.7m/s로 제한한다" 규칙을 추가하세요.
(SafeContext에 배터리 잔량 필드를 추가해야 합니다 — base.py와 motion.py도 함께 수정)

### 제약 (반드시 지킬 것)

1. 기존 규칙(비상정지/장애물/통신/존)의 동작을 깨뜨리지 말 것 — 기존 테스트가 전부 그린이어야 함
2. 새 규칙마다 **실패하는 테스트를 먼저** 작성할 것 (TDD)
3. 우선순위를 명확히: 비상정지는 어떤 규칙보다 우선해야 함

## 테스트 작성 가이드

`robot-sim/tests/test_safeplc_custom.py`를 만들고:

```python
from app.safeplc.base import SafeContext, Vec
# 아래는 예시 — 여러분의 정책 클래스 이름으로 바꾸세요

def ctx(**kw):
    base = dict(position=Vec(0, 0), speed_requested=1.0, estop_active=False,
                obstacle_active=False, comm_ok=True, inside_zones=[], errors_active=[])
    base.update(kw)
    return SafeContext(**base)

def test_night_speed_cap():
    policy = MyNightPolicy(is_night=lambda: True)
    v = policy.evaluate(ctx())
    assert v.max_speed_mps == 0.5

def test_day_no_cap():
    policy = MyNightPolicy(is_night=lambda: False)
    v = policy.evaluate(ctx())
    assert v.max_speed_mps == float("inf")

def test_estop_still_wins_at_night():
    policy = MyNightPolicy(is_night=lambda: True)
    v = policy.evaluate(ctx(estop_active=True))
    assert v.allow_move is False     # 안전 최우선 불변식
```

## 실행

```bash
docker compose build robot-sim
docker compose run --rm robot-sim pytest tests/test_safeplc_custom.py -v
docker compose run --rm robot-sim pytest        # 기존 테스트도 전부 그린인지
```

## 수용기준 (STEP6 통과 조건)

- [ ] 규칙 2개가 테스트로 증명됨
- [ ] 기존 테스트 전부 그린 (규칙 간 간섭 없음)
- [ ] "내 규칙의 우선순위는 어디인가"를 한 문장으로 설명할 수 있음

## 더 나아가기 (자율)

- 장애물 회피 우회 경로 생성 (오더 경로를 바꾸는 것은 safePLC가 아니라 "라우팅"의 영역입니다 — 왜 그런지 생각해보세요)
- 안전 이벤트 감사 로그 (정책 판정 이력을 파일로)
- 복수 안전존 중첩 시 가장 엄격한 상한 적용 (이미 참조구현에 있음 — 코드를 찾아보세요)
