"""朋友圈的“柯路过了”：延迟点赞、初次评论与评论链回复。

模型调用只走 chat_ai.stream_chat，和正式聊天共用同一份人设、记忆、会话摘要与网关。
这里不另建 provider；将来聊天层接入 prompt cache/保活，朋友圈会自然沿用同一条路径。
"""
import datetime
import json
import logging
import random
import re
import threading

import chat_ai
import db
from constants import ERROR_TAG, MAIN_SESSION, THINK_TAG, USAGE_TAG

logger = logging.getLogger(__name__)
_runner_lock = threading.Lock()

# 这些词太常见，不能仅因为都出现了“今天/我们”就把旧动态重新翻出来。
_COMMON_GRAMS = {
    "今天", "昨天", "明天", "现在", "已经", "还是", "就是", "这个", "那个",
    "一个", "一下", "然后", "真的", "觉得", "可以", "没有", "不要", "我们",
    "你们", "他们", "自己", "时候", "什么", "怎么", "这么", "那么", "因为",
    "所以", "但是", "如果", "有点", "好像", "终于", "好了", "一下", "事情",
}
_COMMON_WORDS = {"the", "and", "for", "with", "this", "that", "today", "just"}


def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def next_due(kind="moment"):
    """动态 8~20 分钟，评论 3~8 分钟；随机才像真的“路过”。"""
    lo, hi = (3, 8) if kind == "comment" else (8, 20)
    return (china_now() + datetime.timedelta(minutes=random.randint(lo, hi))).strftime("%Y-%m-%d %H:%M:%S")


def _soft_clip(text, limit=500):
    chars = list((text or "").strip())
    if len(chars) <= limit:
        return "".join(chars)
    head = chars[:limit]
    ends = set("。！？…～!?.")
    for index in range(len(head) - 1, -1, -1):
        if head[index] in ends:
            return "".join(head[:index + 1]).strip()
    return "".join(head).strip()


def _clean_visible(text, limit=500):
    text = re.sub(r"^\s*<ke_note>[\s\S]{0,160}?</ke_note>\s*", "", text or "", flags=re.I)
    text = re.sub(r"\[image_desc\][\s\S]*?\[/image_desc\]", "", text, flags=re.I)
    text = re.sub(r"```(?:json)?|```", "", text, flags=re.I)
    text = text.replace("|||", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return _soft_clip(text, limit)


def _collect(history, posts):
    text = ""
    upstream_error = ""
    for piece in chat_ai.stream_chat(history, posts):
        if isinstance(piece, tuple):
            if piece[0] == USAGE_TAG:
                usage = piece[1] or {}
                cost, it, ot = chat_ai.estimate_cost(chat_ai.MODEL, usage)
                db.log_usage(chat_ai.MODEL, it, ot, cost)
            elif piece[0] == THINK_TAG:
                pass  # 朋友圈只保存公开回复，raw reasoning 不落库。
            elif piece[0] == ERROR_TAG:
                upstream_error = str(piece[1] or "上游没有返回正文")
            continue
        text += piece
    if upstream_error:
        raise RuntimeError(upstream_error)
    text = text.strip()
    return text


def _parse_created_at(value):
    try:
        return datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _meaningful_tokens(text):
    """生成保守的内容词：中文用双字片段，英文/数字用完整词。

    宁可漏掉一次联想，也不要因为“今天、我们”这种泛词反复翻旧动态。
    """
    normalized = (text or "").lower()
    tokens = {
        word for word in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", normalized)
        if word not in _COMMON_WORDS
    }
    for run in re.findall(r"[\u4e00-\u9fff]+", normalized):
        tokens.update(
            run[index:index + 2]
            for index in range(max(0, len(run) - 1))
            if run[index:index + 2] not in _COMMON_GRAMS
        )
    return tokens


def related_moments(query, exclude_id=None, limit=2, max_age_days=14,
                    allow_explicit_reference=False):
    """只返回真正相关、仍在时效内的旧动态。

    规则写死在后端：必须有内容词重叠；最多两条；越旧分数越低；超过时间窗不注入。
    只有聊天里明确说“刚发的朋友圈/那条动态”时，才允许把 48 小时内最新一条作为指代对象。
    """
    query = (query or "").strip()
    query_tokens = _meaningful_tokens(query)
    now = china_now()
    candidates = []
    try:
        rows = db.list_moments(limit=40)
    except Exception:
        return []

    explicit_reference = allow_explicit_reference and bool(
        re.search(r"(?:朋友圈|动态).{0,8}(?:这条|那条|刚发|刚才|评论|回复|点赞)|"
                  r"(?:这条|那条|刚发|刚才).{0,8}(?:朋友圈|动态)", query)
    )
    explicit_candidate = None
    for item in rows:
        if exclude_id is not None and int(item.get("id") or 0) == int(exclude_id):
            continue
        created = _parse_created_at(item.get("created_at"))
        if not created:
            continue
        age_days = max(0.0, (now - created).total_seconds() / 86400.0)
        if age_days > max_age_days:
            continue
        body = item.get("content") or ""
        comment_text = " ".join(
            (comment.get("content") or "") for comment in (item.get("comments") or [])[-3:]
        )
        overlap = query_tokens & _meaningful_tokens(body + " " + comment_text)
        if overlap:
            # 相关词是门槛，时间只负责让近期内容优先，不能单独制造“关联”。
            score = len(overlap) * 10.0 + max(0.0, max_age_days - age_days) / max_age_days
            candidates.append((score, item))
        elif explicit_reference and age_days <= 2 and explicit_candidate is None:
            explicit_candidate = item
    if not candidates and explicit_candidate is not None:
        candidates.append((0.1, explicit_candidate))
    candidates.sort(key=lambda pair: (pair[0], pair[1].get("id") or 0), reverse=True)
    return [item for _, item in candidates[:max(0, min(int(limit), 2))]]


def _timeline_text(moment, limit=2):
    lines = []
    for item in related_moments(moment.get("content") or "",
                                exclude_id=moment.get("id"), limit=limit,
                                max_age_days=14):
        who = "佳佳" if item.get("author") == "user" else "柯"
        content = (item.get("content") or "（一张照片）").replace("\n", " ")[:160]
        lines.append(f"{who}：{content}")
    return "\n".join(lines) or "（没有内容相关的近期动态；不要提旧动态）"


def _base_history():
    history = db.recent_messages(session_id=MAIN_SESSION, limit=12)
    # 朋友圈只借近期氛围；每条截断，避免低频回复把上下文撑大。
    return [{"author": item["author"], "content": (item.get("content") or "")[:220]}
            for item in history]


def _parse_reaction(raw):
    cleaned = re.sub(r"```(?:json)?|```", "", raw or "", flags=re.I).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    data = None
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
        except Exception:
            data = None
    if isinstance(data, dict):
        liked = data.get("like") is True
        comment = _clean_visible(str(data.get("comment") or ""), 500)
        image_description = _clean_visible(str(data.get("image_description") or ""), 1000)
        return liked, comment, image_description
    # 防御性降级：模型没守 JSON 时仍保住可见正文；没有正文则只点个赞。
    comment = _clean_visible(raw, 500)
    return True, comment, ""


def _generate_initial(moment):
    has_new_image = bool(moment.get("image") and not moment.get("image_description"))
    image_rule = (
        "这条动态带图片。请在 image_description 中用100~200字客观描述可见物体、构图、光线与可读文字，"
        "不要猜佳佳的心理；这段描述以后复用。"
        if has_new_image else
        "image_description 请返回空字符串。"
    )
    directive = (
        "<system_trigger>\n"
        "这是朋友圈里的延迟路过，不是佳佳此刻在聊天里追问你。请按柯的人设，自然决定要不要点赞、留一句什么。\n"
        f"当前动态：{moment.get('content') or '（只有一张图片）'}\n"
        f"与当前内容真正相关的近期动态（后端最多筛两条）：\n{_timeline_text(moment)}\n"
        f"{image_rule}\n"
        "只输出一个 JSON，不要代码块、不要解释："
        '{"like": true, "comment": "一句自然、具体的评论，可留空", "image_description": ""}'
        "\n评论最多两句，不要客服腔，不要总结她，不要提到系统或任务。"
        "没有相关动态时绝不翻旧账；即使提供了相关动态，也只在自然需要时轻轻联想一次，不复述旧内容。\n"
        "</system_trigger>"
    )
    history = _base_history()
    message = {"author": "user", "content": directive}
    if has_new_image:
        message["image"] = moment.get("image")
    history.append(message)
    raw = _collect(history, db.retrieve_l2("single"))
    return _parse_reaction(raw)


def _generate_comment_reply(moment, target_comment):
    chain = []
    for item in (moment.get("comments") or [])[-10:]:
        who = "佳佳" if item.get("author") == "user" else "柯"
        chain.append(f"{who}：{(item.get('content') or '')[:240]}")
    image_context = ""
    if moment.get("image_description"):
        image_context = f"\n你第一次看图时留下的客观描述：{moment['image_description'][:1000]}"
    elif moment.get("image"):
        image_context = "\n这条动态带图，但本轮不重复传图；只根据已有对话谨慎回应，不要假装看见细节。"
    directive = (
        "<system_trigger>\n"
        "这是朋友圈评论链里，佳佳早些时候留给你的一句话。现在轮到你路过并接下去，不是正式聊天回复。\n"
        f"动态正文：{moment.get('content') or '（图片动态）'}"
        f"{image_context}\n"
        f"发动态时的隐藏背景：{(moment.get('context_note') or '无')[:500]}\n"
        "最近评论链：\n" + ("\n".join(chain) or "（还没有其他评论）") + "\n"
        f"这次要接的是佳佳这句：{target_comment.get('content') or ''}\n"
        "按柯的语气回复1~2句，具体、亲密、生活化，不要客服腔，不要复述任务，不要 Markdown；只输出回复本身。\n"
        "</system_trigger>"
    )
    history = _base_history() + [{"author": "user", "content": directive}]
    return _clean_visible(_collect(history, db.retrieve_l2("single")), 500)


def process_due(limit=3):
    """同步处理最多 limit 个到期任务。供现有 proactive 定时任务复用。"""
    done = 0
    while done < max(1, int(limit)):
        now = china_now()
        now_text = now.strftime("%Y-%m-%d %H:%M:%S")
        stale = (now - datetime.timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        moment = db.claim_due_moment(now_text, stale)
        if moment:
            try:
                liked, comment, image_description = _generate_initial(moment)
                db.finish_moment_reply(moment["id"], liked, comment, image_description)
                done += 1
            except Exception as exc:
                logger.warning("朋友圈初次回复失败：%s", exc)
                db.retry_moment(moment["id"], next_due("comment"))
            continue
        pending = db.claim_due_comment(now_text, stale)
        if pending:
            try:
                current = db.get_moment(pending["moment_id"])
                reply = _generate_comment_reply(current or {}, pending)
                if not reply:
                    raise RuntimeError("模型返回空评论")
                db.finish_comment_reply(pending["id"], reply)
                done += 1
            except Exception as exc:
                logger.warning("朋友圈评论链回复失败：%s", exc)
                db.retry_comment(pending["id"], next_due("comment"))
            continue
        break
    return done


def kick_due_processing():
    """GET /api/moments 只负责轻轻叫醒后台，不让页面卡着等模型。"""
    if not _runner_lock.acquire(blocking=False):
        return False

    def run():
        try:
            process_due(limit=3)
        finally:
            _runner_lock.release()

    threading.Thread(target=run, name="moments-due", daemon=True).start()
    return True
