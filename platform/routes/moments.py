"""朋友圈（moments）：佳佳与柯你来我往发的动态、评论，以及 /moments 页面。"""
import logging
from flask import Blueprint, jsonify, send_from_directory

import db
from constants import STATIC_DIR
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("moments", __name__)


@bp.get("/moments")
def moments_page(): return send_from_directory(STATIC_DIR, "moments.html")


@bp.get("/api/moments")
@guard
def api_moments(): return jsonify(db.list_moments())


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
    mid = db.add_moment(author="user", content=content, image=image, visibility=visibility)
    return jsonify({"id": mid})


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
    cid = db.add_comment(d.get("moment_id"), "user", content)
    if cid is None:
        return jsonify({"error": "moment not found"}), 404
    return jsonify({"id": cid})


@bp.post("/api/moments/comment/delete")
@guard
def api_delete_comment():
    cid = jget("id")
    if not cid:
        return jsonify({"error": "need id"}), 400
    db.delete_comment(cid)
    return jsonify({"ok": True})
