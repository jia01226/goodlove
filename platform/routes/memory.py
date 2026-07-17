"""记忆库（posts）与向量索引。"""
import logging
from flask import Blueprint, jsonify, send_from_directory

import db
from constants import STATIC_DIR
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("memory", __name__)


@bp.get("/inbox")
def inbox_page():
    """记忆·待确认收件箱页面（骨架，待部署）。"""
    return send_from_directory(STATIC_DIR, "inbox.html")


@bp.get("/api/posts")
@guard
def api_posts(): return jsonify(db.all_posts())


@bp.post("/api/posts")
@guard
def api_add_post():
    d = jbody()
    content = d.get("content", "").strip()
    pid = db.add_post(d.get("type", "MEMORY"), content, d.get("visibility", "both"))
    # 新记忆顺手建一条向量（失败不影响保存）
    try:
        import vector_search
        vector_search.index_post(pid, content)
    except Exception as e:
        logger.warning("索引新记忆失败：%s", e)
    return jsonify({"id": pid})


@bp.post("/api/posts/delete")
@guard
def api_delete_post():
    pid = jget("id")
    if not pid:
        return jsonify({"error": "need id"}), 400
    db.delete_post(pid)
    return jsonify({"ok": True})


@bp.get("/api/vector/status")
@guard
def api_vector_status():
    import vector_search
    return jsonify({
        "backend": vector_search.EMBED_BACKEND,
        "model": vector_search.EMBED_MODEL,
        "available": vector_search.available(),
        "indexed": db.embedding_count(vector_search.EMBED_MODEL),
        "posts": len(db.all_posts()),
    })


@bp.post("/api/vector/backfill")
@guard
def api_vector_backfill():
    import vector_search
    n = vector_search.backfill()
    return jsonify({"indexed_new": n})


# ==================== 记忆卡片系统（对知言 UI / 佳佳纠错）====================
@bp.get("/api/memory/pending")
@guard
def api_mem_pending():
    """待确认收件箱：机器猜的记忆，佳佳点头才当真。"""
    return jsonify(db.list_pending())


@bp.post("/api/memory/pending/review")
@guard
def api_mem_review():
    d = jbody()
    cid = d.get("id"); store = d.get("store", "l2")
    if not cid:
        return jsonify({"error": "need id"}), 400
    approve = bool(d.get("approve", True))
    # 确认时若带了修改后的内容，先落库再转正
    if approve and d.get("content"):
        try:
            tbl = "private_memories" if store == "private" else "posts"
            conn = db.get_db()
            conn.execute(f"UPDATE {tbl} SET content=?, updated_at=datetime('now','+8 hours') WHERE id=?",
                         (d["content"].strip(), cid))
            conn.commit(); conn.close()
        except Exception as e:
            logger.warning("改内容失败：%s", e)
    db.review_card(cid, store=store, approve=approve)
    return jsonify({"ok": True})


@bp.get("/api/memory/cards")
@guard
def api_mem_cards():
    """卡片库：默认单聊视角（含 private，排除 no_model）。"""
    return jsonify(db.retrieve_l2("single"))


@bp.post("/api/memory/card/scope")
@guard
def api_mem_scope():
    d = jbody()
    if not d.get("id") or not d.get("scope"):
        return jsonify({"error": "need id+scope"}), 400
    ok = db.set_card_scope(d["id"], d["scope"], store=d.get("store", "l2"))
    return jsonify({"ok": ok})


@bp.post("/api/memory/card/forget")
@guard
def api_mem_forget():
    """忘掉＝进七天冷静期，随时可找回（柯给佳佳低谷时的保险）。"""
    d = jbody()
    if not d.get("id"):
        return jsonify({"error": "need id"}), 400
    db.forget_card(d["id"], store=d.get("store", "l2"))
    return jsonify({"ok": True, "note": "已进七天冷静期，随时可找回"})


@bp.post("/api/memory/card/recover")
@guard
def api_mem_recover():
    d = jbody()
    if not d.get("id"):
        return jsonify({"error": "need id"}), 400
    db.recover_card(d["id"], store=d.get("store", "l2"))
    return jsonify({"ok": True})


@bp.get("/api/memory/breath")
@guard
def api_mem_breath():
    """记忆诊断（Breath Lab，挂在设置→开发者模式）：给个查询词，看各层各自想起了什么、分数多少、谁过线。
    只读、不改任何数据；日常界面不露这些技术信息。"""
    from flask import request
    q = (request.args.get("q") or "").strip()
    out = {"query": q, "vector_available": False, "l2": [], "private": [], "always_types": [], "note": ""}
    if not q:
        out["note"] = "给个查询词试试，如 /api/memory/breath?q=樱粉色"
        return jsonify(out)
    try:
        import vector_search, chat_ai
        out["vector_available"] = vector_search.available()
        out["l2"] = [{"id": h["ref_id"], "text": h["text"][:80], "score": round(h["score"], 4)}
                     for h in vector_search.search(q, k=chat_ai.TOPK, kind="post")]
        out["private"] = [{"id": h["ref_id"], "text": h["text"][:80], "score": round(h["score"], 4)}
                          for h in vector_search.search(q, k=chat_ai.PRIVATE_TOPK, kind="private")]
        out["always_types"] = sorted(chat_ai.ALWAYS_TYPES)
    except Exception as e:
        out["note"] = f"诊断失败：{e}"
    return jsonify(out)


@bp.get("/api/memory/injection-log")
@guard
def api_mem_injlog():
    """最近的记忆注入日志（归因用：柯忽然像助手/提了不该提的时，回看是哪一步的问题）。"""
    return jsonify(db.recent_injection_logs(100))


@bp.post("/api/memory/private")
@guard
def api_mem_add_private():
    """新增一条私密卡（L1.5B，柯切卡灌库/单聊沉淀用）。顺手建向量，失败不影响保存。"""
    d = jbody()
    content = (d.get("content") or "").strip()
    if not content:
        return jsonify({"error": "empty"}), 400
    pid = db.add_private_memory(content, topic=d.get("topic", ""), scope=d.get("scope", "private"),
                                source=d.get("source", "user_explicit"),
                                importance=int(d.get("importance", 4)),
                                review_state=d.get("review_state", "approved"))
    try:
        import vector_search
        vector_search.index_private(pid, content)
    except Exception as e:
        logger.warning("索引私密卡失败：%s", e)
    return jsonify({"id": pid})
