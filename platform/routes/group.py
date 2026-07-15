"""群聊（高级吗喽科技公司：佳佳 + 柯/小克/知言）。"""
import json
import logging
from flask import Blueprint, Response, jsonify, send_from_directory

import db
import chat_ai
from constants import (STATIC_DIR, GROUP_SESSION, USAGE_TAG, THINK_TAG,
                       SSE_CONTENT_TYPE, SSE_HEADERS)
from utils import guard, jbody

logger = logging.getLogger(__name__)
bp = Blueprint("group", __name__)


@bp.get("/group")
def group_page(): return send_from_directory(STATIC_DIR, "group.html")


@bp.get("/api/group/members")
@guard
def api_group_members():
    import group_chat
    cfg = group_chat.load_config()
    return jsonify({"group_name": cfg.get("group_name", "群聊"),
                    "default_speaker": cfg.get("default_speaker", ""),
                    "members": [{"name": m.get("name"), "emoji": m.get("emoji", "🤖"),
                                 "role": m.get("role", "")} for m in cfg.get("members", [])]})


@bp.get("/api/group/messages")
@guard
def api_group_messages():
    return jsonify(db.recent_messages(session_id=GROUP_SESSION, limit=200))


@bp.post("/api/group/chat")
@guard
def api_group_chat():
    import group_chat
    data = jbody()
    text = (data.get("text") or "").strip()
    image = (data.get("image") or "").strip()
    if not text and not image:
        return jsonify({"error": "empty"}), 400
    db.add_message("user", text, session_id=GROUP_SESSION,
                   image=image, msg_type=("image" if image else "text"))
    member = group_chat.pick_speaker(text)
    if not member:
        return jsonify({"error": "no members"}), 500
    history = db.recent_messages(session_id=GROUP_SESSION, limit=40)
    # 隐私硬隔离（柯钉死）：群聊只喂 shared/group-safe 记忆，private/未定档/no_model 在查询层就够不着。
    # 曾经这里用 app_posts()＝和单聊同一份记忆，私密内容会漏进群聊——此改从工程层堵死。
    posts = db.group_visible_posts()

    def gen():
        # 先告诉前端这轮谁发言（好显示名字/头像）
        yield ("data: " + json.dumps({"speaker": member["name"],
                                      "emoji": member.get("emoji", "🤖")},
                                     ensure_ascii=False) + "\n\n").encode("utf-8")
        acc = ""
        model_used = (member.get("model") or "").strip() or chat_ai.MODEL
        for piece in group_chat.stream_reply(member, history, posts):
            if isinstance(piece, tuple):
                if piece[0] == USAGE_TAG:
                    usage = piece[1] or {}
                    cost, it, ot = chat_ai.estimate_cost(model_used, usage)
                    db.log_usage(model_used, it, ot, cost)
                elif piece[0] == THINK_TAG:
                    yield ("data: " + json.dumps({"think": piece[1]}, ensure_ascii=False) + "\n\n").encode("utf-8")
                continue
            acc += piece
            yield ("data: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n").encode("utf-8")
        if acc:
            db.add_message(member["name"], acc, session_id=GROUP_SESSION)
        yield ("data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type=SSE_CONTENT_TYPE, headers=dict(SSE_HEADERS))
