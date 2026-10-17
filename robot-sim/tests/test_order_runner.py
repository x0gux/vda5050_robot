"""T4 검증: 오더 해석 규칙 (수용/거절/replan/중복)."""
from app.order_runner import OrderRunner
from app.state_machine import RobotState


def make_order(order_id="ORDER-TEST1", update_id=0, with_actions=False):
    nodes = [
        {"nodeId": "N1", "sequenceId": 1, "released": True,
         "nodePosition": {"x": 0, "y": 0, "theta": 0, "mapId": "study_map"}},
        {"nodeId": "N2", "sequenceId": 3, "released": True,
         "nodePosition": {"x": 3, "y": 0, "theta": 0, "mapId": "study_map"}},
        {"nodeId": "N3", "sequenceId": 5, "released": True,
         "nodePosition": {"x": 6, "y": 0, "theta": 0, "mapId": "study_map"}},
    ]
    if with_actions:
        nodes[1]["actions"] = [{"actionId": "pick-1", "actionType": "pick", "blockingType": "NONE"}]
    edges = [
        {"sequenceId": 2, "startNodeId": "N1", "endNodeId": "N2", "released": True},
        {"sequenceId": 4, "startNodeId": "N2", "endNodeId": "N3", "released": True},
    ]
    return {"headerId": 1, "timestamp": "2026-01-01T00:00:00Z", "version": "2.0.0",
            "manufacturer": "study", "serialNumber": "SIM-001",
            "orderId": order_id, "orderUpdateId": update_id, "nodes": nodes, "edges": edges}


def test_accept_and_build_chain():
    runner = OrderRunner(RobotState())
    assert runner.handle_order(make_order()) == "accepted"
    active = runner.active
    assert [w.node_id for w in active.waypoints] == ["N1", "N2", "N3"]
    assert [w.x for w in active.waypoints] == [0.0, 3.0, 6.0]
    assert [e["sequenceId"] for e in active.edges] == [2, 4]
    assert runner.has_active()


def test_malformed_orders_rejected():
    runner = OrderRunner(RobotState())
    assert runner.handle_order({"orderId": "", "nodes": []}).startswith("rejected")
    assert runner.handle_order({"orderId": "X", "nodes": []}).startswith("rejected")
    assert runner.handle_order({"orderId": "X", "nodes": [{"nodeId": "N9"}]}).startswith("rejected")
    assert runner.active is None


def test_stale_update_ignored_and_replan_works():
    runner = OrderRunner(RobotState())
    runner.handle_order(make_order(update_id=2))
    assert runner.handle_order(make_order(update_id=1)).startswith("ignored")   # QoS1 구버전 중복
    assert runner.handle_order(make_order(update_id=2)).startswith("ignored")   # 동일 버전 중복
    assert runner.handle_order(make_order(update_id=3)) == "updated"            # 경로 교체
    assert runner.active.order_update_id == 3


def test_busy_robot_rejects_new_order_then_accepts_after_cancel():
    runner = OrderRunner(RobotState())
    runner.handle_order(make_order("ORDER-A"))
    assert runner.handle_order(make_order("ORDER-B")).startswith("rejected")
    assert runner.cancel() is True
    assert runner.cancel() is False  # 이미 폐기됨
    assert runner.handle_order(make_order("ORDER-B")) == "accepted"


def test_route_state_shape_while_active():
    runner = OrderRunner(RobotState())
    runner.handle_order(make_order())
    node_states, edge_states, action_states = runner.route_state()
    assert [n["nodeId"] for n in node_states] == ["N1", "N2", "N3"]
    assert node_states[0]["nodeStatus"] == "RUNNING"
    assert [e["sequenceId"] for e in edge_states] == [2, 4]
    assert action_states == []
