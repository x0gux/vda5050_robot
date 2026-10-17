"""오더 해석/실행 엔진 (VDA5050 order).

마스터(관제)가 보내는 order 페이로드:
  { orderId, orderUpdateId, nodes:[{nodeId, sequenceId, nodePosition{x,y}, actions[]}], edges:[{sequenceId, startNodeId, endNodeId}] }

수용 규칙 (교육용 단순화 + VDA5050 실무 근사):
  - 신규 orderId: 활성 오더가 없을 때만 수용 (바쁠 때는 거절 — 관제가 409를 받는 이유)
  - 동일 orderId + 더 큰 orderUpdateId: 경로 교체(replan) — QoS1 중복/구버전은 무시
  - cancelOrder 인스턴트 액션: 즉시 폐기
"""
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.state_machine import RobotState

log = logging.getLogger("robot-sim.order")


@dataclass
class Waypoint:
    node_id: str
    sequence_id: int
    x: float
    y: float
    actions: List[Dict[str, Any]]


@dataclass
class ActiveOrder:
    order_id: str
    order_update_id: int
    waypoints: List[Waypoint]
    edges: List[Dict[str, Any]]          # 체인 순 edge 메타 [{sequenceId}]
    target_idx: int = 0                  # 향하고 있는(또는 현재 있는) 웨이포인트
    arrived_idx: int = -1                # 마지막 도달 웨이포인트
    action_cursor: int = 0               # 현재 웨이포인트 actions 중 실행 완료 개수
    running_action: Optional[Dict[str, Any]] = None  # {actionId, actionType, started_at}
    finished: bool = False

    def current_waypoint(self) -> Waypoint:
        return self.waypoints[self.target_idx]

    def actions_done(self) -> bool:
        if self.arrived_idx < 0:
            return True
        w = self.waypoints[self.arrived_idx]
        return self.running_action is None and self.action_cursor >= len(w.actions)

    # ---- 상태 보고 (state 메시지용) ----
    def node_states(self) -> List[Dict[str, Any]]:
        out = []
        for i, w in enumerate(self.waypoints):
            if i < self.arrived_idx or (i == self.arrived_idx and self.actions_done()):
                status = "FINISHED"
            elif i == self.arrived_idx or i == self.target_idx:
                status = "RUNNING"
            else:
                status = "PENDING"
            out.append({"nodeId": w.node_id, "sequenceId": w.sequence_id, "nodeStatus": status})
        return out

    def edge_states(self) -> List[Dict[str, Any]]:
        out = []
        for i, e in enumerate(self.edges):
            if i + 1 <= self.arrived_idx:
                status = "FINISHED"
            elif i == self.arrived_idx and self.target_idx == self.arrived_idx + 1:
                status = "RUNNING"
            else:
                status = "PENDING"
            out.append({"sequenceId": e["sequenceId"], "edgeStatus": status})
        return out

    def action_states(self) -> List[Dict[str, Any]]:
        out = []
        for wi, w in enumerate(self.waypoints):
            for ai, a in enumerate(w.actions):
                aid = str(a.get("actionId") or f"{w.node_id}-action-{ai}")
                if wi < self.arrived_idx:
                    status = "FINISHED"
                elif wi == self.arrived_idx:
                    if self.running_action and self.running_action.get("actionId") == aid:
                        status = "RUNNING"
                    elif ai < self.action_cursor:
                        status = "FINISHED"
                    else:
                        status = "WAITING"
                else:
                    status = "WAITING"
                out.append({"actionId": aid, "actionType": a.get("actionType"), "actionStatus": status})
        return out


class OrderRunner:
    def __init__(self, state: RobotState, action_duration_s: float = 2.0, clock=None):
        self.robot_state = state
        self.action_duration_s = action_duration_s
        self.clock = clock or time.monotonic
        self.active: Optional[ActiveOrder] = None
        self._lock = threading.Lock()

    # ---- 수입 (MQTT 콜백에서 호출) ----
    def handle_order(self, data: Dict[str, Any]) -> str:
        """반환: accepted / updated / ignored: ... / rejected: ..."""
        try:
            order_id = str(data.get("orderId") or "").strip()
            update_id = int(data.get("orderUpdateId") or 0)
            nodes = data.get("nodes") or []
            if not order_id or not nodes:
                return "rejected: malformed order (orderId/nodes required)"
            with self._lock:
                if self.active and self.active.order_id == order_id:
                    if update_id <= self.active.order_update_id:
                        return f"ignored: stale orderUpdateId {update_id} <= {self.active.order_update_id}"
                    waypoints, edge_meta = self._build_waypoints(nodes, data.get("edges") or [])
                    if not waypoints:
                        return "rejected: replan produced empty route"
                    self.active = ActiveOrder(order_id=order_id, order_update_id=update_id,
                                              waypoints=waypoints, edges=edge_meta)
                    log.info("order replanned: %s updateId=%d (%d waypoints)", order_id, update_id, len(waypoints))
                    return "updated"
                if self.active and not self.active.finished:
                    return f"rejected: busy with {self.active.order_id}"
                waypoints, edge_meta = self._build_waypoints(nodes, data.get("edges") or [])
                if not waypoints:
                    return "rejected: empty route (nodes lack nodePosition?)"
                self.active = ActiveOrder(order_id=order_id, order_update_id=update_id,
                                          waypoints=waypoints, edges=edge_meta)
                log.info("order accepted: %s updateId=%d route=%s", order_id, update_id,
                         "→".join(w.node_id for w in waypoints))
                return "accepted"
        except Exception as e:
            log.warning("order handling failed: %s", e)
            return f"rejected: {e}"

    def cancel(self) -> bool:
        with self._lock:
            had = self.active is not None
            self.active = None
            if had:
                log.info("order cancelled — 활성 오더 폐기")
            return had

    def has_active(self) -> bool:
        with self._lock:
            return self.active is not None and not self.active.finished

    # ---- 진행 (모션 스레드에서 호출) ----
    def on_arrival(self, waypoint_idx: int) -> None:
        """웨이포인트 도달: node FINISHED 전환 + 노드 액션 시작."""
        with self._lock:
            active = self.active
            if active is None or active.finished:
                return
            active.arrived_idx = waypoint_idx
            active.target_idx = waypoint_idx
            active.action_cursor = 0
            active.running_action = self._start_next_action(active)
            w = active.waypoints[waypoint_idx]
            log.info("node reached: %s (seq=%d) actions=%d", w.node_id, w.sequence_id, len(w.actions))

    def advance_actions(self, now: float) -> None:
        """노드 액션 타이머 진행 — 끝나면 다음 웨이포인트로 출발 or 오더 완료."""
        with self._lock:
            active = self.active
            if active is None or active.finished or active.arrived_idx < 0:
                return
            if active.running_action and now - active.running_action["started_at"] >= self.action_duration_s:
                log.info("action finished: %s (%s)", active.running_action["actionId"],
                         active.running_action["actionType"])
                active.running_action = None
                active.action_cursor += 1
                active.running_action = self._start_next_action(active)
            if active.actions_done():
                if active.arrived_idx >= len(active.waypoints) - 1:
                    active.finished = True
                    log.info("order completed: %s", active.order_id)
                else:
                    active.target_idx = active.arrived_idx + 1

    def _start_next_action(self, active: ActiveOrder) -> Optional[Dict[str, Any]]:
        w = active.waypoints[active.arrived_idx]
        while active.action_cursor < len(w.actions):
            a = w.actions[active.action_cursor]
            if not a.get("actionId"):
                active.action_cursor += 1  # actionId 없는 액션은 실행 불가 — 스킵
                continue
            return {"actionId": str(a["actionId"]), "actionType": a.get("actionType"),
                    "started_at": self.clock()}
        return None

    # ---- state 보고 (publish 루프에서 호출) ----
    def route_state(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """(nodeStates, edgeStates, actionStates) — 완료/없음이면 전부 빈 리스트."""
        with self._lock:
            active = self.active
            if active is None or active.finished:
                return [], [], []
            return active.node_states(), active.edge_states(), active.action_states()

    # ---- 헬퍼 ----
    @staticmethod
    def _build_waypoints(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Tuple[List[Waypoint], List[Dict[str, Any]]]:
        node_map: Dict[str, Dict[str, Any]] = {}
        for n in nodes:
            nid = n.get("nodeId")
            if nid is not None:
                node_map[str(nid)] = n

        def pos_of(node_id: str) -> Optional[Tuple[float, float]]:
            p = (node_map.get(node_id) or {}).get("nodePosition") or {}
            x, y = p.get("x"), p.get("y")
            if x is None or y is None:
                return None
            return float(x), float(y)

        chain_ids: List[str] = []
        edge_meta: List[Dict[str, Any]] = []
        if edges:
            sorted_edges = sorted(edges, key=lambda e: int(e.get("sequenceId") or 0))
            first = sorted_edges[0].get("startNodeId")
            if first is not None and str(first) in node_map:
                chain_ids.append(str(first))
            for e in sorted_edges:
                end = e.get("endNodeId")
                if end is None:
                    continue
                end = str(end)
                if not chain_ids or chain_ids[-1] != end:
                    chain_ids.append(end)
            edge_meta = [{"sequenceId": int(e.get("sequenceId") or 0)} for e in sorted_edges]
        else:
            sorted_nodes = sorted(nodes, key=lambda n: int(n.get("sequenceId") or 0))
            chain_ids = [str(n.get("nodeId")) for n in sorted_nodes if n.get("nodeId") is not None]

        waypoints: List[Waypoint] = []
        for cid in chain_ids:
            p = pos_of(cid)
            if p is None:
                log.warning("node %s has no nodePosition — 스킵", cid)
                continue
            n = node_map[cid]
            waypoints.append(Waypoint(
                node_id=cid,
                sequence_id=int(n.get("sequenceId") or 0),
                x=p[0], y=p[1],
                actions=list(n.get("actions") or []),
            ))
        if edge_meta and len(edge_meta) != len(waypoints) - 1:
            log.warning("edge/waypoint 불일치 (edges=%d waypoints=%d) — edgeStates 생략",
                        len(edge_meta), len(waypoints))
            edge_meta = []
        return waypoints, edge_meta
