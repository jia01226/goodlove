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
    return jsonify({
        "sealed": bool(view.get("sealed")),
        "outside": view.get("outside") or [],
        # 这是页面外壳，不是抽屉内容；柯以后可以通过自主层替换为他主动留下的话。
        "note": "知道你会来翻。想要什么，自己来问我。",
    })
