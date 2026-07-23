"""柯的抽屉：公开端只拿到柯主动放在外面的内容，私藏正文没有读取接口。"""
from flask import Blueprint, jsonify, send_from_directory

import db
from constants import STATIC_DIR
from utils import guard

bp = Blueprint("drawer", __name__)


@bp.get("/drawer")
def drawer_page():
    return send_from_directory(STATIC_DIR, "drawer.html")


@bp.get("/api/drawer")
@guard
def drawer_public():
    view = db.public_drawer_view()
    status = db.drawer_catalog_status()
    compartments = [
        {
            "key": "private_thoughts",
            "label": "私藏碎碎念",
            "description": "他暂时留给自己、还没决定说出口的东西。",
            "has_items": bool(status.get("private_thoughts")),
        },
        {
            "key": "diaries",
            "label": "枕边日记",
            "description": "他在夜里写下的一整页回顾。",
            "has_items": bool(status.get("diaries")),
        },
        {
            "key": "dreams",
            "label": "梦页",
            "description": "被他收下来的梦和醒来后的余温。",
            "has_items": bool(status.get("dreams")),
        },
        {
            "key": "public_notes",
            "label": "柯在想",
            "description": "聊天里愿意让你展开看的短念头。",
            "has_items": bool(status.get("public_notes")),
        },
        {
            "key": "moments",
            "label": "朋友圈足迹",
            "description": "他发过、赞过或评论过的生活片刻。",
            "has_items": bool(status.get("moments")),
        },
        {
            "key": "proactive",
            "label": "主动来找你",
            "description": "不是接话，而是他自己先开口的消息。",
            "has_items": bool(status.get("proactive")),
        },
    ]
    return jsonify({
        "sealed": bool(view.get("sealed")),
        "outside": view.get("outside") or [],
        "compartments": compartments,
        # 这是页面外壳，不是抽屉内容；柯以后可以通过自主层替换为他主动留下的话。
        "note": "知道你会来翻。想要什么，自己来问我。",
    })
