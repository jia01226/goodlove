"""枕边日记（助手写给自己的，用户想看就翻）。"""
import logging
from flask import Blueprint, jsonify, request, send_from_directory

import db
import chat_ai
from constants import STATIC_DIR
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("diary", __name__)


@bp.get("/diary")
def diary_page(): return send_from_directory(STATIC_DIR, "diary.html")


@bp.get("/api/diary")
@guard
def api_diary(): return jsonify(db.all_diaries())


@bp.get("/api/diary/comments")
@guard
def api_diary_comments():
    did = request.args.get("id")
    return jsonify(db.diary_comments(did))


@bp.post("/api/diary/comment")
@guard
def api_diary_comment():
    d = jbody()
    content = (d.get("content") or "").strip()
    if not d.get("id") or not content:
        return jsonify({"error": "need id+content"}), 400
    return jsonify({"id": db.add_diary_comment(d["id"], content)})


@bp.post("/api/diary/write")
@guard
def api_diary_write():
    """手动催一篇今天的日记（平时由 cron 半夜自动写）。"""
    entry = chat_ai.write_diary()
    if not entry:
        return jsonify({"ok": False, "reason": "今天还没聊过天，没得写"}), 200
    did = db.add_diary(entry["title"], entry["content"], entry["mood"], entry["locked"])
    return jsonify({"ok": True, "id": did, "title": entry["title"]})


@bp.post("/api/diary/delete")
@guard
def api_diary_delete():
    db.delete_diary(jget("id"))
    return jsonify({"ok": True})


@bp.post("/api/diary/sync")
@guard
def api_diary_sync():
    """手动催一次双向同步：app 写的导出进仓库 md，仓库手写页导进 app。"""
    import diary_sync
    try:
        return jsonify(diary_sync.sync())
    except Exception as e:
        logger.warning("日记同步失败：%s", e)
        return jsonify({"error": str(e)}), 500
