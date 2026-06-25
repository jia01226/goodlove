"""助手的"灵魂"：构建系统提示 + 调用 OpenRouter 流式对话。
核心阶段：系统提示 = persona.md（由 CLAUDE.md 复制而来）+ 数据库里的 posts。
第二阶段再接入向量语义检索（vector_search.py）。
"""
import os, json, codecs, base64, mimetypes, requests

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")

def _img_data_url(rel):
    """把上传的图片读成 data URL（base64），让模型能"看见"。非图片/失败返回 None。"""
    try:
        name = (rel or "").split("/")[-1]
        if not name:
            return None
        fp = os.path.join(UPLOAD_DIR, name)
        if not os.path.exists(fp):
            return None
        mime = mimetypes.guess_type(fp)[0] or ""
        if not mime.startswith("image/"):
            return None
        with open(fp, "rb") as f:
            b = f.read()
        return f"data:{mime};base64," + base64.b64encode(b).decode()
    except Exception as e:
        print("[chat] 读图失败：", e)
        return None

OR_URL = None  # 运行时由 API_BASE 拼出
API_BASE = os.environ.get("API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "anthropic/claude-sonnet-4.5")
API_KEY = os.environ.get("API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
PERSONA_FILE = os.path.join(os.path.dirname(__file__), "persona.md")

BASE = (
    "你是一个 AI 助手。下面《人设》是使用者给你的设定，请按它来；"
    "若《人设》为空，就做一个友好、真诚、有帮助的助手，正常对话即可。\n\n"
    "下面是你的《人设》：\n"
)

def _load_persona():
    try:
        with open(PERSONA_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

# 记忆条数超过这个数才启用"向量精准想起"；以下则全量塞（小语料全带最稳）
FULL_MEMORY_LIMIT = int(os.environ.get("FULL_MEMORY_LIMIT", "60"))
TOPK = int(os.environ.get("VEC_TOPK", "12"))
# 这些类型永远带上（承诺/愿望太重要，不能漏）
ALWAYS_TYPES = {"PROMISE", "WISHLIST"}

def _render(parts, items):
    for p in items:
        parts.append(f"[{p['type']}] {p['content']}")

def _now_context():
    try:
        import context
        return context.build_now_context()
    except Exception as e:
        print("[chat_ai] 实时情况生成失败：", e)
        return ""

def build_system_prompt(posts, query=None, summary=None):
    """posts: 全部记忆（最新在前）。query: 本轮用户的话，用来"精准想起"。
    summary: 更早对话的浓缩摘要（聊久了用，免得忘事又省 token）。
    记忆少→全带；记忆多→带 最相关top-k + 永远要带的类型 + 最近几条（去重）。"""
    parts = [BASE, _load_persona(), _now_context()]
    if summary:
        parts.append("\n\n===== 更早对话的浓缩记忆（别忘了这些）=====\n" + summary)
    if not posts:
        return "\n".join(parts)

    if len(posts) <= FULL_MEMORY_LIMIT or not query:
        parts.append("\n\n===== 记忆库（最新在前）=====")
        _render(parts, posts[:200])
        return "\n".join(parts)

    # —— 记忆多了：向量+词面 精准想起 ——
    try:
        import vector_search
        hits = vector_search.search(query, k=TOPK, kind="post")
    except Exception as e:
        print("[chat_ai] 检索失败，回退全量：", e)
        hits = None

    by_id = {p["id"]: p for p in posts}
    chosen, seen = [], set()
    if hits:
        for h in hits:
            p = by_id.get(h["ref_id"])
            if p and p["id"] not in seen:
                chosen.append(p); seen.add(p["id"])
    else:
        # 检索完全不可用：退回最近一批
        for p in posts[:TOPK]:
            chosen.append(p); seen.add(p["id"])

    # 永远要带的（承诺/愿望）+ 最近 8 条
    for p in posts:
        if p["type"] in ALWAYS_TYPES and p["id"] not in seen:
            chosen.append(p); seen.add(p["id"])
    for p in posts[:8]:
        if p["id"] not in seen:
            chosen.append(p); seen.add(p["id"])

    parts.append("\n\n===== 记忆库（已为这次对话挑出最相关的）=====")
    _render(parts, chosen)
    return "\n".join(parts)

def stream_chat(history, posts):
    """history: [{author, content}]；逐段 yield 文本；最后 yield ('__usage__', {...})。"""
    # 用最近一条用户的话做"精准想起"的检索词
    query = next((m["content"] for m in reversed(history) if m["author"] == "user"), None)
    summary = None
    try:
        import db
        sess = db.get_session(1)
        summary = (sess or {}).get("summary") or None
    except Exception:
        pass
    sys_prompt = build_system_prompt(posts, query=query, summary=summary)
    messages = [{"role": "system", "content": sys_prompt}]
    # 只把"最后一条带图的消息"作为真图发给模型看（省流量）；更早的图用文字代替
    last_img_idx = max((i for i, m in enumerate(history) if m.get("image")), default=-1)
    for i, m in enumerate(history):
        role = "user" if m["author"] == "user" else "assistant"
        img = m.get("image")
        if img and i == last_img_idx:
            data_url = _img_data_url(img)
            if data_url:
                content = []
                if m["content"]:
                    content.append({"type": "text", "text": m["content"]})
                content.append({"type": "image_url", "image_url": {"url": data_url}})
                messages.append({"role": role, "content": content})
            else:
                # 不是图片（或读不到）：当成用户发了个文件，用文字说明
                note = "（用户发来一个文件）" if not _img_data_url(img) else ""
                messages.append({"role": role, "content": (m["content"] or "") + note})
        elif img:
            messages.append({"role": role, "content": (m["content"] or "") + "（用户当时发过一张图片/文件）"})
        else:
            messages.append({"role": role, "content": m["content"]})
    payload = {
        "model": MODEL, "max_tokens": 4096, "stream": True,
        "messages": messages,
    }
    if "openrouter" in API_BASE:
        payload["usage"] = {"include": True}   # OpenRouter：在最后一块返回用量
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "Gude-AiyiPingtai",
    }
    usage = {}
    url = API_BASE + "/chat/completions"
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=120) as r:
        r.encoding = "utf-8"
        if r.status_code != 200:
            yield f"[没接上线：{r.status_code} {r.text[:200]}]"
            return
        # 增量 UTF-8 解码：正确处理跨网络分片被切断的多字节中文/emoji
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        buffer = ""
        for chunk in r.iter_content(chunk_size=1024):
            if not chunk:
                continue
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    continue
                try:
                    ev = json.loads(data)
                except Exception:
                    continue
                if ev.get("usage"):
                    usage = ev["usage"]
                ch = ev.get("choices", [{}])[0]
                piece = (ch.get("delta") or {}).get("content") or ""
                if piece:
                    yield piece
    yield ("__usage__", usage)

def estimate_cost(model, usage):
    """粗略估算（OpenRouter 实际计费以账单为准）。返回美元。"""
    it = usage.get("prompt_tokens", 0) or 0
    ot = usage.get("completion_tokens", 0) or 0
    # 默认按 Sonnet 量级估：$3/M 入、$15/M 出
    return round(it/1e6*3 + ot/1e6*15, 6), it, ot

def _complete(messages, max_tokens=700):
    """一次性（非流式）补全，返回文本。给"会话总结"等后台活用。失败返回空串。"""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "max_tokens": max_tokens, "stream": False, "messages": messages}
    try:
        r = requests.post(API_BASE + "/chat/completions", headers=headers, json=payload, timeout=120)
        if r.status_code != 200:
            print("[summary] 接口非200：", r.status_code, r.text[:160]); return ""
        data = r.json()
        return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception as e:
        print("[summary] 请求失败：", e); return ""

# 聊到多少条以上、且攒够多少条没折叠的旧消息，才值得做一次总结
SUMMARY_KEEP_RECENT = int(os.environ.get("SUMMARY_KEEP_RECENT", "30"))
SUMMARY_BATCH = int(os.environ.get("SUMMARY_BATCH", "16"))

def maybe_summarize(sid=1):
    """聊久了：把"较早的一批消息"折叠进会话摘要。够了才做，省钱。返回是否做了。"""
    try:
        import db
        msgs, new_until = db.messages_for_summary(sid, keep_recent=SUMMARY_KEEP_RECENT)
        if len(msgs) < SUMMARY_BATCH:
            return False
        old = (db.get_session(sid) or {}).get("summary") or ""
        convo = "\n".join(("用户：" if m["author"] == "user" else "助手：") + m["content"] for m in msgs)
        prompt = (
            "请把下面这段较早的对话，浓缩成一段「记忆摘要」，"
            "**保留重要的事实/约定/用户近况/情绪/关键信息**，丢掉寒暄废话，控制在 400 字内。\n"
            + (f"\n【已有的摘要（在它基础上更新、别丢旧信息）】\n{old}\n" if old else "")
            + f"\n【要并入摘要的更早对话】\n{convo}\n\n直接输出更新后的完整摘要本身，别加说明。"
        )
        summary = _complete([{"role": "user", "content": prompt}], max_tokens=700)
        if summary:
            db.set_session_summary(sid, summary, new_until)
            print(f"[summary] 已折叠 {len(msgs)} 条旧消息进摘要（until={new_until}）")
            return True
    except Exception as e:
        print("[summary] 跳过：", e)
    return False
