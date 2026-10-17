"""T7 검증: 제어 REST API (TestClient — lifespan 없이 엔드포인트만 검증)."""
import time

from fastapi.testclient import TestClient

from app.main import app, core, core_lock, motion, robot_state

client = TestClient(app)


def tick_once():
    """실제 state 루프 1틱을 대행 — 정책 심의(opState/에러 반영)를 유발한다."""
    motion.tick(core, core_lock, robot_state, time.monotonic())


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_estop_endpoint_uses_same_safety_path():
    r = client.post("/estop", json={"activate": True})
    assert r.status_code == 200 and r.json() == {"success": True, "estop_active": True}
    tick_once()
    status = client.get("/status").json()
    assert status["opState"] == "ERROR"
    assert any(e["errorType"] == "faxEStop" and e["errorLevel"] == "FATAL"
               for e in status["errors"])
    # 해제 (테스트 격리 복구)
    client.post("/estop", json={"activate": False})
    tick_once()
    assert client.get("/status").json()["opState"] == "IDLE"


def test_fault_inject_and_clear():
    r = client.post("/faults", json={"type": "drive_error", "duration_s": 30})
    assert r.status_code == 200 and r.json()["type"] == "drive_error"
    assert "drive_error" in client.get("/faults").json()["active"]
    tick_once()
    status = client.get("/status").json()
    assert status["opState"] == "ERROR"
    assert any(e["errorType"] == "DriveFault" for e in status["errors"])

    client.post("/faults/clear")
    tick_once()
    status = client.get("/status").json()
    assert not any(e["errorType"] == "DriveFault" for e in status["errors"])
    assert client.get("/faults").json()["active"] == []


def test_unknown_fault_type_returns_400():
    r = client.post("/faults", json={"type": "meteor", "duration_s": 5})
    assert r.status_code == 400


def test_auto_faults_endpoint_toggle():
    r = client.post("/auto-faults", json={"enabled": True, "interval_s": 5})
    assert r.status_code == 200 and r.json()["enabled"] is True
    r = client.post("/auto-faults", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False


def test_status_endpoint_shape():
    status = client.get("/status").json()
    for key in ("identity", "position", "battery", "opState", "orderId", "errors", "mqttConnected"):
        assert key in status
