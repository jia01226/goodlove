"""朋友圈（moments）：佳佳与柯你来我往发的动态、评论，以及 /moments 页面。"""
import logging
from flask import Blueprint, jsonify, send_from_directory

import db
import moments_ai
from constants import STATIC_DIR
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("moments", __name__)


@bp.get("/moments")
def moments_page(): return send_from_directory(STATIC_DIR, "moments.html")


@bp.get("/api/moments")
@guard
def api_moments():
    # 到期回复在后台生成；列表先返回，页面不会被模型调用卡住。
    moments_ai.kick_due_processing()
    response = jsonify(db.list_moments())
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/api/moments/status")
@guard
def api_moments_status():
    response = jsonify(db.moments_activity_status())
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/api/moments")
@guard
def api_add_moment():
    d = jbody()
    content = (d.get("content") or "").strip()
    image = (d.get("image") or "").strip()
    if not content and not image:
        return jsonify({"error": "empty"}), 400
    visibility = d.get("visibility") or "private"
    if visibility not in ("private", "public"):
        visibility = "private"
    # author 固定为 user：佳佳从界面只能以自己身份发（柯的动态走聊天暗号）
    due = moments_ai.next_due("moment")
    mid = db.add_moment(author="user", content=content, image=image, visibility=visibility,
                        context_note="佳佳从朋友圈发出的动态。",
                        reply_due_at=due, reply_status="pending")
    return jsonify({"id": mid, "reply_due_at": due})


@bp.post("/api/moments/edit")
@guard
def api_edit_moment():
    d = jbody()
    mid = d.get("id")
    content = (d.get("content") or "").strip()
    if not mid:
        return jsonify({"error": "need id"}), 400
    if not content:
        return jsonify({"error": "need content"}), 400
    if not db.edit_moment(mid, content, author="user"):
        return jsonify({"error": "moment not found"}), 404
    return jsonify({"ok": True})


@bp.post("/api/moments/like")
@guard
def api_like_moment():
    d = jbody()
    mid = d.get("id")
    if not mid:
        return jsonify({"error": "need id"}), 400
    if not db.set_moment_like(mid, d.get("liked") is True, actor="user"):
        return jsonify({"error": "moment not found"}), 404
    return jsonify({"ok": True, "liked": d.get("liked") is True})


@bp.post("/api/moments/delete")
@guard
def api_delete_moment():
    mid = jget("id")
    if not mid:
        return jsonify({"error": "need id"}), 400
    db.delete_moment(mid)
    return jsonify({"ok": True})


@bp.post("/api/moments/comment")
@guard
def api_add_comment():
    d = jbody()
    content = (d.get("content") or "").strip()
    if not content:
        return jsonify({"error": "need content"}), 400
    due = moments_ai.next_due("comment")
    cid = db.add_comment(d.get("moment_id"), "user", content,
                         reply_due_at=due, reply_status="pending")
    if cid is None:
        return jsonify({"error": "moment not found"}), 404
    return jsonify({"id": cid, "reply_due_at": due})


@bp.post("/api/moments/comment/delete")
@guard
def api_delete_comment():
    cid = jget("id")
    if not cid:
        return jsonify({"error": "need id"}), 400
    db.delete_comment(cid)
    return jsonify({"ok": True})


@bp.post("/api/moments/comment/edit")
@guard
def api_edit_comment():
    d = jbody()
    cid = d.get("id")
    content = (d.get("content") or "").strip()
    if not cid:
        return jsonify({"error": "need id"}), 400
    if not content:
        return jsonify({"error": "need content"}), 400
    if not db.edit_comment(cid, content, author="user"):
        return jsonify({"error": "comment not found"}), 404
    return jsonify({"ok": True})
