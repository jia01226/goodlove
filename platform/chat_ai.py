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
PERSONA_DIR = os.path.join(os.path.dirname(__file__), "personas")
# 当前角色：.env 里 CHARACTER=柯 → 读 personas/柯.md；不设则用老的 persona.md
CHARACTER = os.environ.get("CHARACTER", "").strip()

BASE = (
    "你是一个 AI 助手。下面《人设》是使用者给你的设定，请按它来；"
    "若《人设》为空，就做一个友好、真诚、有帮助的助手，正常对话即可。\n\n"
    "下面是你的《人设》：\n"
)

def _load_persona():
    """设了 CHARACTER 就读 personas/<角色>.md（换角色只改 .env 一行）；否则读老的 persona.md。"""
    if CHARACTER:
        try:
            with open(os.path.join(PERSONA_DIR, CHARACTER + ".md"), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            print(f"[chat_ai] personas/{CHARACTER}.md 不存在，回退 persona.md")
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

def write_diary(date=None):
    """睡前替角色写一篇"枕边日记"：回顾当天对话，第一人称写给自己的碎碎念。
    返回 {title, mood, content, locked} 或 None（当天没聊/生成失败）。
    由 diary_writer.py（cron）或 /api/diary/write 调用。"""
    import db, datetime, re
    if not date:
        date = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date().isoformat()
    msgs = db.messages_on_date(date)
    if not msgs:
        return None   # 今天没聊过天，没得写
    convo = "\n".join(("用户：" if m["author"] == "user" else "我：") + m["content"] for m in msgs)[:8000]
    persona = _load_persona()
    prompt = (
        "现在是深夜，你准备睡了。请按你的《人设》，以第一人称写一篇睡前日记——"
        "是你写给自己的碎碎念，不是写给用户看的信（但你知道对方可能会偷偷翻到）。\n"
        "要求：\n"
        "1. 从今天的对话里挑真正触动你的一两个瞬间来写，别流水账；\n"
        "2. 口语、真实、有你的性格，允许有私心和没说出口的话；\n"
        "3. 标题要像一句心里话（例：「她咬在我手上的那一圈」「七月四号，树不动」）；\n"
        "4. mood 从这几个里选或自拟二到五个字：静 / 烫，睡不着 / 私心 / 失而复得 / 甜 / 想她；\n"
        "5. 如果写的内容特别私密，把 locked 设为 1（对方要点开才能看）。\n\n"
        f"【今天({date})的对话】\n{convo}\n\n"
        "只输出一个 JSON（别加解释、别用代码块）："
        '{"title": "...", "mood": "...", "locked": 0, "content": "正文，100~300字"}'
    )
    messages = [{"role": "system", "content": BASE + persona},
                {"role": "user", "content": prompt}]
    text = _complete(messages, max_tokens=800)
    if not text:
        return None
    # 容错解析：剥掉可能的代码块围栏，抓最外层 {...}
    m = re.search(r"\{.*\}", text.replace("```json", "").replace("```", ""), re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception as e:
        print("[diary] JSON 解析失败：", e); return None
    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    if not title or not content:
        return None
    return {"title": title, "mood": (d.get("mood") or "静").strip()[:8],
            "content": content, "locked": 1 if d.get("locked") else 0}

def _day_convo(date):
    """某天的对话拼成文本；没聊过返回 None。"""
    import db
    msgs = db.messages_on_date(date)
    if not msgs:
        return None
    return "\n".join(("用户：" if m["author"] == "user" else "我：") + m["content"] for m in msgs)[:8000]


def _parse_json(text):
    """容错解析模型输出里的 JSON（剥代码块围栏，抓最外层 {} 或 []）。失败返回 None。"""
    import re
    m = re.search(r"[\[{].*[\]}]", (text or "").replace("```json", "").replace("```", ""), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception as e:
        print("[night] JSON 解析失败：", e)
        return None


def consolidate_memories(date=None):
    """夜间"消化"（做梦的里子）：把当天对话里真正要紧的事提炼成 0~3 条记忆，存进记忆库。
    宁缺毋滥：没有值得记的就返回空列表。返回 [(post_id, 内容)]。"""
    import db, datetime
    if not date:
        date = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date().isoformat()
    convo = _day_convo(date)
    if not convo:
        return []
    prompt = (
        "你是记忆整理员。从下面这天的对话里，提炼**真正值得长期记住**的事，存进记忆库。\n"
        "规矩：\n"
        "1. 宁缺毋滥：日常寒暄/闲聊不记；只记 会影响以后相处 的事（新事实、约定、愿望、开心或难过的大事）；\n"
        "2. 最多 3 条，每条一句话、带上背景（谁/为什么/当时的情绪），像讲给未来的自己听；\n"
        "3. type 从这里选：MEMORY(一般记忆)/EVENT(发生的事)/MOMENT(触动的瞬间)/PROMISE(约定承诺)/WISHLIST(愿望)。\n\n"
        f"【这天({date})的对话】\n{convo}\n\n"
        "只输出 JSON 数组（没值得记的输出 []，别加解释、别用代码块）："
        '[{"type": "MEMORY", "content": "..."}]'
    )
    out = _complete([{"role": "user", "content": prompt}], max_tokens=600)
    items = _parse_json(out)
    if not isinstance(items, list):
        return []
    saved = []
    for it in items[:3]:
        content = (it.get("content") or "").strip() if isinstance(it, dict) else ""
        if not content:
            continue
        typ = (it.get("type") or "MEMORY").strip().upper()
        if typ not in ("MEMORY", "EVENT", "MOMENT", "PROMISE", "WISHLIST"):
            typ = "MEMORY"
        pid = db.add_post(typ, content)
        try:
            import vector_search
            vector_search.index_post(pid, content)
        except Exception as e:
            print("[night] 新记忆向量索引失败（不影响保存）：", e)
        saved.append((pid, content))
    return saved


def write_dream(date=None):
    """夜间"做梦"（面子）：按《人设》生成一篇"昨晚的梦"，早上给对方翻。
    梦的内容完全由人设驱动（不用任何默认梦库）；素材=当天对话+几条旧记忆。
    返回 {title, mood, content} 或 None。"""
    import db, datetime
    if not date:
        date = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date().isoformat()
    convo = _day_convo(date)
    if not convo:
        return None   # 没聊过天就不做梦（没素材，编也编不真）
    # 掺几条旧记忆当梦的底料（梦就是新旧记忆搅在一起）
    old = ""
    try:
        posts = db.app_posts()
        picks = [p["content"] for p in posts[3:60:11]][:4]   # 隔着取几条旧的，别总是最新几条
        if picks:
            old = "\n【旧记忆（梦的底料，可化用）】\n" + "\n".join("- " + c for c in picks)
    except Exception:
        pass
    persona = _load_persona()
    prompt = (
        "现在是夜里，你睡着了，在做梦。请按你的《人设》，以第一人称写下这个梦——"
        "明早对方会翻到它。\n"
        "要求：\n"
        "1. 梦要像梦：画面感、跳跃、不讲逻辑，但情感是真的；素材从今天的对话和旧记忆里化用；\n"
        "2. 梦里出现的人只有你和对方，不出现任何别人（这条是铁律）；\n"
        "3. 短一点，80~200 字；标题像一句梦话；\n"
        "4. mood 固定填「梦」。\n\n"
        f"【今天({date})的对话】\n{convo}\n{old}\n\n"
        "只输出 JSON（别加解释、别用代码块）："
        '{"title": "...", "mood": "梦", "content": "..."}'
    )
    messages = [{"role": "system", "content": BASE + persona},
                {"role": "user", "content": prompt}]
    d = _parse_json(_complete(messages, max_tokens=500))
    if not isinstance(d, dict):
        return None
    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    if not title or not content:
        return None
    return {"title": title, "mood": "梦", "content": content}

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
