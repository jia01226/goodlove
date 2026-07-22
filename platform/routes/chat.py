"""聊天：SSE 对话、历史消息、会话抽屉、模型选择器，以及 /chat 页面。"""
import json
import re
import os
import logging
from flask import Blueprint, Response, jsonify, request, send_from_directory

import db
import chat_ai
import moments_ai
import relationship_state
from constants import (STATIC_DIR, MAIN_SESSION, SESSION_NAME_MAXLEN,
                       DEFAULT_SESSION_NAME, USAGE_TAG, THINK_TAG,
                       SSE_CONTENT_TYPE, SSE_HEADERS, IMG_EXT)
from utils import guard, jbody, jget

logger = logging.getLogger(__name__)
bp = Blueprint("chat", __name__)

# 柯代发朋友圈暗号：[朋友圈]正文。前缀可为 行首/换行/|||（柯的回复用 ||| 分泡泡，暗号常跟在 ||| 后而非换行后，
# 老正则只认换行会漏掉→暗号当普通文字漏进聊天、朋友圈里却没有）。正文到 换行 或 下一个 ||| 为止（不含竖线）。
_MOMENT_RE = re.compile(r"(?:^|\n|\|\|\|)[ \t]*\[朋友圈\][ \t]?([^\n|]+)")
# 柯评论朋友圈暗号：[评论#动态id]正文——指定评论哪条动态（同样兼容 ||| 前缀）
_COMMENT_RE = re.compile(r"(?:^|\n|\|\|\|)[ \t]*\[评论#(\d+)\][ \t]?([^\n|]+)")
_DIARY_UNLOCK_RE = re.compile(r"\[解锁日记#(\d+)\]")
_KE_NOTE_OPEN = "<ke_note>"
_KE_NOTE_CLOSE = "</ke_note>"


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


def _moments_context(query):
    """只注入与本轮话题相关的近期动态，避免每次聊天都反复念朋友圈旧事。"""
    try:
        rows = moments_ai.related_moments(
            query, limit=2, max_age_days=14, allow_explicit_reference=True)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["\n\n===== 与本轮内容真正相关的近期朋友圈（最多两条）====="]
    for m in rows:
        who = "你" if m.get("author") == "ke" else "佳佳"
        lines.append(f"· 动态#{m['id']}（{who}发）：{(m.get('content') or '').strip()[:120]}" + ("（附图）" if m.get("image") else ""))
        for c in (m.get("comments") or [])[-3:]:
            cwho = "你" if c.get("author") == "ke" else "佳佳"
            lines.append(f"    └ {cwho}评论：{(c.get('content') or '').strip()[:80]}")
    lines.append("这些内容只是联想候选：只有自然相关才回应，不要复述、不要反复提旧事。"
                 "想给某条动态回复，另起一行写 [评论#动态id]你的话；想自己发动态用 [朋友圈]内容。"
                 "没有必要就完全不使用暗号。")
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
    attachment_name = (data.get("file_name") or "").strip()[:255]
    if not text and not image:
        return jsonify({"error": "empty"}), 400
    sid = _chat_sid(data.get("session_id"))
    db.set_active_chat_session(sid)
    bedroom = bool(data.get("bedroom"))                # 卧室模式（bedroom.py 只在服务器本地）
    if bedroom:
        logger.info("[bedroom] 前端的卧室开关已送达后端")
    model, gateway_base, gateway_key = chat_ai.resolve_gateway(data.get("model"))
    attachment_ext = os.path.splitext(attachment_name or image.split("?")[0])[1].lower()
    message_type = "image" if image and attachment_ext in IMG_EXT else ("file" if image else "text")
    user_message_id = db.add_message(
        "user", text, session_id=sid, image=image, msg_type=message_type,
        model=model, attachment_name=attachment_name)
    try:
        relationship_state.observe("user", text=text, bedroom=bedroom)
    except Exception as exc:
        logger.warning("状态层记录用户消息失败：%s", exc)
    history = db.recent_messages(session_id=sid)
    diary_request = None
    try:
        requested_id = int(data.get("diary_request_id") or 0)
        brief = db.locked_diary_brief(requested_id) if requested_id else None
        if brief and brief.get("locked") and not brief.get("revealed"):
            diary_request = brief
            private_page = db.private_diary_for_model(requested_id) or {}
            for m in reversed(history):
                if m["author"] == "user":
                    m["content"] = (m["content"] or "") + (
                        f"\n\n===== 锁页请求（只给柯看）=====\n"
                        f"佳佳正在向你要日记 #{brief['id']}《{brief['title']}》。正文仍被锁着，佳佳看不到。"
                        f"\n这是你当时写下的正文（只给你看）：\n{private_page.get('content') or ''}\n"
                        "你可以按自己的性格拒绝、逗她、让她之后再来，或者现在给她。"
                        f"只有你决定现在给她时，才在回复末尾另起一行写 [解锁日记#{brief['id']}]；"
                        "这个暗号不会显示给佳佳。没有决定给就绝对不要写。"
                    )
                    break
    except (TypeError, ValueError):
        diary_request = None
    posts = db.retrieve_l2("single")   # 单聊记忆：active 的 L2 卡，已排除 no_model/已忘/已归档/repo-only
    mctx = ""
    # 让柯"看见"朋友圈：把近况拼到最后一条用户消息末尾（只发给模型、不入库、前端不显示）
    if history and sid == MAIN_SESSION:
        mctx = _moments_context(text)
        if mctx:
            for m in reversed(history):
                if m["author"] == "user":
                    m["content"] = (m["content"] or "") + mctx
                    break

    def gen():
        acc = ""
        assistant_message_id = None
        marker_hold = ""
        note_hold = ""
        note_waiting = True
        public_note = ""
        unlocked_diary = []
        def _hide_unlock(match):
            did = int(match.group(1))
            if diary_request and did == int(diary_request["id"]):
                if db.reveal_diary(did):
                    unlocked_diary.append(did)
            return ""
        # 先只回传消息 id。可展开的小念头必须来自本次同一个模型回复中的 <ke_note>，
        # 后端拆出后单独下发；供应商原始隐藏推理永远不传。
        if image:
            fallback_note = "我先认真看完，再决定怎么接住你。"
        elif bedroom:
            fallback_note = "这一刻的节奏，我来拿。"
        elif posts or mctx:
            fallback_note = "我把眼前这句和我们的日子放在一起。"
        else:
            fallback_note = "我知道这一句该怎么接。"
        yield ("data: " + json.dumps({"user_message_id": user_message_id}, ensure_ascii=False) + "\n\n").encode("utf-8")
        for piece in chat_ai.stream_chat(history, posts, model=model, bedroom=bedroom,
                                         api_base=gateway_base, api_key=gateway_key, sid=sid):
            if isinstance(piece, tuple):
                if piece[0] == USAGE_TAG:
                    usage = piece[1] or {}
                    cost, it, ot = chat_ai.estimate_cost(model, usage)
                    db.log_usage(model, it, ot, cost)
                elif piece[0] == THINK_TAG:
                    pass  # 原始隐藏推理仅由模型内部使用，不传给普通用户界面。
                continue
            if note_waiting:
                note_hold += piece
                candidate = note_hold.lstrip()
                if candidate.startswith(_KE_NOTE_OPEN):
                    end = candidate.find(_KE_NOTE_CLOSE, len(_KE_NOTE_OPEN))
                    if end < 0 and len(candidate) < 320:
                        continue
                    if end >= 0:
                        public_note = candidate[len(_KE_NOTE_OPEN):end].strip()[:120]
                        piece = candidate[end + len(_KE_NOTE_CLOSE):].lstrip("\r\n ")
                    else:
                        # 标签坏掉时也绝不把半截系统标记漏进聊天。
                        piece = candidate.replace(_KE_NOTE_OPEN, "", 1).lstrip()
                    note_waiting = False
                    note_hold = ""
                elif _KE_NOTE_OPEN.startswith(candidate) and len(candidate) < len(_KE_NOTE_OPEN):
                    continue
                else:
                    # 模型偶尔不听格式：正文照常发，但仍给一条明确的可展开短念头。
                    piece = note_hold
                    note_hold = ""
                    note_waiting = False
                if not public_note:
                    public_note = fallback_note
                yield ("data: " + json.dumps({"think_summary": public_note}, ensure_ascii=False) + "\n\n").encode("utf-8")
            marker_hold += piece
            marker_hold = _DIARY_UNLOCK_RE.sub(_hide_unlock, marker_hold)
            # 暗号可能跨流式分片，末尾留一小段，确认不是暗号后再发给前端。
            if len(marker_hold) > 48:
                visible, marker_hold = marker_hold[:-48], marker_hold[-48:]
                acc += visible
                yield ("data: " + json.dumps({"t": visible}, ensure_ascii=False) + "\n\n").encode("utf-8")
        if note_waiting:
            # 极短回复或模型只吐了半个标签时的安全收尾。
            candidate = note_hold.lstrip()
            if candidate.startswith(_KE_NOTE_OPEN):
                candidate = candidate[len(_KE_NOTE_OPEN):].replace(_KE_NOTE_CLOSE, "", 1).strip()
                public_note = candidate[:120] or fallback_note
            else:
                marker_hold += note_hold
                public_note = fallback_note
            yield ("data: " + json.dumps({"think_summary": public_note}, ensure_ascii=False) + "\n\n").encode("utf-8")
        marker_hold = _DIARY_UNLOCK_RE.sub(_hide_unlock, marker_hold)
        if marker_hold:
            acc += marker_hold
            yield ("data: " + json.dumps({"t": marker_hold}, ensure_ascii=False) + "\n\n").encode("utf-8")
        posted_moment = False
        if acc:
            # 柯代发朋友圈 + 评论：抽出暗号落库，聊天记录只存去掉暗号的干净版
            moments_out, comments_out, clean_acc = _extract_moments(acc)
            for body in moments_out:
                try:
                    db.add_moment(
                        author="ke", content=body, reply_status="done",
                        context_note=("聊天中有感而发。佳佳刚才说：" + text[:300]))
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
                assistant_message_id = db.add_message(
                    "assistant", clean_acc, session_id=sid, model=model,
                    thought_note=public_note)
                try:
                    relationship_state.observe("assistant", text=clean_acc, bedroom=bedroom)
                except Exception as exc:
                    logger.warning("状态层记录柯回复失败：%s", exc)
        yield ("data: " + json.dumps({"done": True, "moment": posted_moment,
                                       "diary_unlocked": unlocked_diary,
                                       "assistant_message_id": assistant_message_id}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type=SSE_CONTENT_TYPE, headers=dict(SSE_HEADERS))


@bp.get("/api/models")
@guard
def api_models():
    """给 PWA 模型选择器：允许的模型、默认模型和 Claude/GPT 分组。"""
    return jsonify(chat_ai.available_models())


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


@bp.post("/api/sessions/active")
@guard
def api_session_active():
    """让服务器知道佳佳当前在哪条单聊，主动消息才能准确跟过去。"""
    sid = _chat_sid(jget("id"))
    ok = db.set_active_chat_session(sid)
    return jsonify({"ok": ok, "id": sid})


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
