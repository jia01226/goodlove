"""聊天：SSE 对话、历史消息、会话抽屉、模型选择器，以及 /chat 页面。"""
import json
import re
import logging
from flask import Blueprint, Response, jsonify, request, send_from_directory

import db
import chat_ai
from constants import (STATIC_DIR, MAIN_SESSION, SESSION_NAME_MAXLEN,
                       DEFAULT_SESSION_NAME, USAGE_TAG, THINK_TAG,
                       SSE_CONTENT_TYPE, SSE_HEADERS)
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("chat", __name__)

# 柯代发朋友圈暗号：[朋友圈]正文。前缀可为 行首/换行/|||（柯的回复用 ||| 分泡泡，暗号常跟在 ||| 后而非换行后，
# 老正则只认换行会漏掉→暗号当普通文字漏进聊天、朋友圈里却没有）。正文到 换行 或 下一个 ||| 为止（不含竖线）。
_MOMENT_RE = re.compile(r"(?:^|\n|\|\|\|)[ \t]*\[朋友圈\][ \t]?([^\n|]+)")
# 柯评论朋友圈暗号：[评论#动态id]正文——指定评论哪条动态（同样兼容 ||| 前缀）
_COMMENT_RE = re.compile(r"(?:^|\n|\|\|\|)[ \t]*\[评论#(\d+)\][ \t]?([^\n|]+)")


def _extract_moments(text):
    """从助手回复里提取 [朋友圈]... / [评论#id]... 暗号，并返回去掉这些暗号的干净文本。
    兼容 ||| 分句：暗号跟在 ||| 后也能识别；抽走后把残留的分隔符/空泡泡收拾干净。
    返回 (moments:list[str], comments:list[(mid,body)], clean_text:str)。"""
    moments = [m.strip() for m in _MOMENT_RE.findall(text) if m.strip()]
    comments = [(int(mid), body.strip()) for mid, body in _COMMENT_RE.findall(text) if body.strip()]
    clean = _COMMENT_RE.sub("", _MOMENT_RE.sub("", text))
    # 抽走暗号后收尾：连续 ||| 压成一个、连续空行压一个、去掉首尾的分隔符与空白（免得留个空泡泡）
    clean = re.sub(r"\|\|\|(?:[ \t]*\|\|\|)+", "|||", clean)
    clean = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", clean).strip()
    clean = clean.strip("|").strip()
    return moments, comments, clean


def _moments_context():
    """把最近几条朋友圈动态+评论拼成一段，注入柯的上下文——让他"看见"朋友圈、能评论回应。
    没有动态返回空串。"""
    try:
        rows = db.list_moments(limit=8)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["\n\n===== 朋友圈近况（你和佳佳的动态墙；想回应就用暗号，见下）====="]
    for m in rows:
        who = "你" if m.get("author") == "ke" else "佳佳"
        lines.append(f"· 动态#{m['id']}（{who}发）：{(m.get('content') or '').strip()[:120]}" + ("（附图）" if m.get("image") else ""))
        for c in (m.get("comments") or []):
            cwho = "你" if c.get("author") == "ke" else "佳佳"
            lines.append(f"    └ {cwho}评论：{(c.get('content') or '').strip()[:80]}")
    lines.append("【怎么回应朋友圈】想给某条评论/回复，另起一行写 [评论#动态id]你的话（如 [评论#3]这张拍得真好看）；"
                 "想自己发条动态用 [朋友圈]内容。别硬回、有话才说，一次别刷太多。")
    return "\n".join(lines)


@bp.get("/chat")
def chat_page(): return send_from_directory(STATIC_DIR, "chat.html")


def _chat_sid(raw):
    """把前端传来的会话 id 收敛成合法的 1对1 会话 id：非法/群聊/不存在都退回主对话 1。"""
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return MAIN_SESSION
    if sid == db.GROUP_SID or not db.session_exists(sid):
        return MAIN_SESSION
    return sid


@bp.post("/api/chat")
@guard
def api_chat():
    data = jbody()
    text = (data.get("text") or "").strip()
    image = (data.get("image") or "").strip()
    if not text and not image:
        return jsonify({"error": "empty"}), 400
    sid = _chat_sid(data.get("session_id"))
    bedroom = bool(data.get("bedroom"))                # 卧室模式（bedroom.py 只在服务器本地）
    if bedroom:
        logger.info("[bedroom] 前端的卧室开关已送达后端")
    model = chat_ai.resolve_model(data.get("model"))   # 前端可选模型，白名单外回落默认
    db.add_message("user", text, session_id=sid, image=image, msg_type=("image" if image else "text"))
    history = db.recent_messages(session_id=sid)
    posts = db.retrieve_l2("single")   # 单聊记忆：active 的 L2 卡，已排除 no_model/已忘/已归档/repo-only
    # 让柯"看见"朋友圈：把近况拼到最后一条用户消息末尾（只发给模型、不入库、前端不显示）
    if history and sid == MAIN_SESSION:
        mctx = _moments_context()
        if mctx:
            for m in reversed(history):
                if m["author"] == "user":
                    m["content"] = (m["content"] or "") + mctx
                    break

    def gen():
        acc = ""
        for piece in chat_ai.stream_chat(history, posts, model=model, bedroom=bedroom):
            if isinstance(piece, tuple):
                if piece[0] == USAGE_TAG:
                    usage = piece[1] or {}
                    cost, it, ot = chat_ai.estimate_cost(model, usage)
                    db.log_usage(model, it, ot, cost)
                elif piece[0] == THINK_TAG:
                    yield ("data: " + json.dumps({"think": piece[1]}, ensure_ascii=False) + "\n\n").encode("utf-8")
                continue
            acc += piece
            yield ("data: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n").encode("utf-8")
        posted_moment = False
        if acc:
            # 柯代发朋友圈 + 评论：抽出暗号落库，聊天记录只存去掉暗号的干净版
            moments_out, comments_out, clean_acc = _extract_moments(acc)
            for body in moments_out:
                try:
                    db.add_moment(author="ke", content=body)
                    posted_moment = True
                except Exception as e:
                    logger.warning("柯代发朋友圈失败：%s", e)
            for mid, body in comments_out:
                try:
                    if db.add_comment(mid, "ke", body) is not None:
                        posted_moment = True
                except Exception as e:
                    logger.warning("柯评论朋友圈失败：%s", e)
            if clean_acc:
                db.add_message("assistant", clean_acc, session_id=sid)
        yield ("data: " + json.dumps({"done": True, "moment": posted_moment}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type=SSE_CONTENT_TYPE, headers=dict(SSE_HEADERS))


@bp.get("/api/models")
@guard
def api_models():
    """给前端模型选择器（知言的 UI 调这个）：可选模型（白名单）+ 当前默认。"""
    return jsonify({"models": chat_ai.MODEL_WHITELIST, "default": chat_ai.MODEL})


@bp.get("/api/messages")
@guard
def api_messages():
    sid = _chat_sid(request.args.get("session_id"))
    return jsonify(db.recent_messages(session_id=sid, limit=200))


@bp.post("/api/messages/delete")
@guard
def api_delete_message():
    mid = jget("id")
    if not mid:
        return jsonify({"error": "need id"}), 400
    db.delete_message(mid)
    return jsonify({"ok": True})


# ---- 会话抽屉（多条 1对1 对话）----
@bp.get("/api/sessions")
@guard
def api_sessions(): return jsonify(db.list_chat_sessions())


@bp.post("/api/sessions")
@guard
def api_session_new():
    name = (jget("name") or DEFAULT_SESSION_NAME).strip()[:SESSION_NAME_MAXLEN] or DEFAULT_SESSION_NAME
    return jsonify({"id": db.create_chat_session(name), "name": name})


@bp.post("/api/sessions/rename")
@guard
def api_session_rename():
    d = jbody()
    name = (d.get("name") or "").strip()[:SESSION_NAME_MAXLEN]
    if not d.get("id") or not name:
        return jsonify({"error": "need id+name"}), 400
    db.rename_chat_session(d["id"], name)
    return jsonify({"ok": True})


@bp.post("/api/sessions/delete")
@guard
def api_session_delete():
    ok = db.delete_chat_session(jget("id"))
    return jsonify({"ok": ok})
