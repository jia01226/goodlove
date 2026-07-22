"""柯的房间：状态只说人话；三下轻敲交给主动消息心跳。"""
from flask import Blueprint, jsonify, send_from_directory

import relationship_state
from constants import STATIC_DIR
from utils import guard, jbody


bp = Blueprint("room", __name__)


@bp.get("/room")
def room_page():
    return send_from_directory(STATIC_DIR, "room.html")


@bp.get("/api/room/state")
@guard
def room_state():
    return jsonify(relationship_state.public_view())


@bp.post("/api/room/signal")
@guard
def room_signal():
    kind = (jbody().get("kind") or "triple_tap").strip()
    if kind != "triple_tap":
        return jsonify({"error": "unsupported signal"}), 400
    signal_id = relationship_state.queue_signal(kind)
    return jsonify({"ok": True, "id": signal_id, "message": "柯听见了"})
