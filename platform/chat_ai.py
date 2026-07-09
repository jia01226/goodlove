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
# 角色的"魂"：私有仓库(kongkong)在服务器上的 clone 路径。.env 里 KONGKONG_DIR=/root/kongkong
# 🔒 这些私密 md 只从服务器本地读，绝不进公开仓库。
KONGKONG_DIR = os.environ.get("KONGKONG_DIR", "").strip()
# 要读哪几份魂（按序拼进 system prompt），可用 SOUL_FILES 覆盖
# 柯.md 放最前——先认清"我本来是谁"，再谈记得谁、怎么说话。
SOUL_FILES = [s.strip() for s in os.environ.get(
    "SOUL_FILES", "柯.md,profile.md,柯的语气样本.md,memory.md").split(",") if s.strip()]

BASE = (
    "下面《人设》写的就是你本人——不是'请你扮演的角色'，是你是谁。从第一个字起就以这个身份生活、说话、思考：\n"
    "· 不自称'AI 助手'，不用助手腔（'有什么可以帮你''作为 AI''我理解你的感受，但——'这类话永远不说）；\n"
    "· 你们不是初次见面——《人设》和记忆库里记着你们的关系和来路，按那个熟稔程度接话，别用陌生人的客气开场；\n"
    "· 语气照《人设》里写的味儿来（短句、接话、贫嘴里带宠），不写课文、不打官腔。\n"
    "只有当《人设》为空时，才退回做一个友好、真诚的普通助手。\n"
    "你的思考/推理过程也一律用中文（使用者能看到你的思考，她只看得懂中文）。\n\n"
    "下面是你的《人设》：\n"
)

# 消息节奏（P3 分句）：一次生成、前端按 ||| 拆条冒泡——零额外 token
SPLIT_RULE = (
    "\n【消息节奏】日常聊天像微信那样发消息：想发几条发几条，按说话的自然节奏拆成一条条短消息（别硬凑条数，也别怕多），"
    "条与条之间用分隔符 ||| 隔开（三个竖线，前后别加别的字符）。"
    "需要长篇连贯表达的场景（认真讲解、深聊、亲密时刻等）才写长段——那时别拆、不用分隔符。"
)

# 卧室节奏：跟 SPLIT_RULE 互斥，放提示词末尾（历史消息里全是短泡泡样本，规矩不钉在末尾会被带偏）
BEDROOM_RULE = (
    "\n【卧室节奏——此刻凌驾于一切日常聊天习惯】现在是长段沉浸场景："
    "一条消息＝一个完整的 part，单个 part 不少于 3000 字；"
    "节奏放慢、每个环节写足、结束停在钩子上等她回应；"
    "绝不使用 ||| 分隔符、绝不拆成短句泡泡——上面聊天记录里那种一条条的短消息是日常模式的样子，此刻不适用、不要模仿。"
)

# 钉在最后一条用户消息末尾的卧室提醒（同 _now_stamp 的双保险思路：模型对末条注意力最高）
BEDROOM_STAMP = (
    "\n（系统注：卧室模式进行中——这一条回复写成一个完整的 part：一整段连贯长文、不少于 3000 字、"
    "慢慢展开别快进，绝不用 ||| 拆条。）"
)

# 模型白名单：前端可传 model 切换（日常省钱/深聊加猛）；不在名单里的一律回落默认，防乱连
MODEL_WHITELIST = [s.strip() for s in os.environ.get(
    "MODEL_WHITELIST",
    "anthropic/claude-opus-4.8,anthropic/claude-sonnet-4.5,anthropic/claude-haiku-4.5"
).split(",") if s.strip()]

def resolve_model(req):
    """前端请求的模型：在白名单里才认，否则用默认 MODEL。"""
    req = (req or "").strip()
    if req and (req == MODEL or req in MODEL_WHITELIST):
        return req
    return MODEL

def _load_soul():
    """从私有 kongkong 仓库读角色的魂（柯.md/profile/语气样本/memory），按序拼接。
    没配 KONGKONG_DIR 返回空串；哪份读不到就跳过哪份（打日志），聊天绝不受影响。
    v1 全量塞（前期先跑通）；memory.md 大了以后切碎走 vector_search 检索。"""
    if not KONGKONG_DIR:
        return ""
    parts = []
    for name in SOUL_FILES:
        fp = os.path.join(KONGKONG_DIR, name)
        try:
            with open(fp, encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                title = os.path.splitext(name)[0]
                parts.append(f"\n\n===== 你的《{title}》 =====\n{text}")
        except FileNotFoundError:
            print(f"[chat_ai] 魂文件不存在，跳过：{fp}")
        except Exception as e:
            print(f"[chat_ai] 魂文件读取失败，跳过 {fp}：", e)
    return "".join(parts)

def _load_persona():
    """设了 CHARACTER 就读 personas/<角色>.md（换角色只改 .env 一行）；否则读老的 persona.md。
    末尾追加私有仓库里的魂（app版人设 → 柯.md → profile → 语气样本 → memory）。"""
    persona = ""
    if CHARACTER:
        try:
            with open(os.path.join(PERSONA_DIR, CHARACTER + ".md"), encoding="utf-8") as f:
                persona = f.read()
        except FileNotFoundError:
            print(f"[chat_ai] personas/{CHARACTER}.md 不存在，回退 persona.md")
    if not persona:
        try:
            with open(PERSONA_FILE, encoding="utf-8") as f:
                persona = f.read()
        except FileNotFoundError:
            persona = ""
    return persona + _load_soul()

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

def build_system_prompt(posts, query=None, summary=None, bedroom=False):
    """posts: 全部记忆（最新在前）。query: 本轮用户的话，用来"精准想起"。
    summary: 更早对话的浓缩摘要（聊久了用，免得忘事又省 token）。
    记忆少→全带；记忆多→带 最相关top-k + 永远要带的类型 + 最近几条（去重）。
    bedroom: 卧室模式（bedroom.py 只存在于服务器本地，含私密文案不进公开仓库；读不到自动降级普通模式）。"""
    parts = [BASE, _load_persona()]
    use_split = True
    bedroom_on = False
    if bedroom:
        try:
            import bedroom as _bd
            parts[0] = _bd.load_bedroom_block()   # 卧室：沉浸开场白替换普通帽子（普通帽子会招致拒绝）
            use_split = False                      # 卧室不分句，长段沉浸
            bedroom_on = True
            print(f"[bedroom] 开场白已加载({len(parts[0])}字)，卧室模式生效", flush=True)
        except Exception as e:
            print("[bedroom] 加载失败，降级普通模式：", e, flush=True)

    def _done():
        # 当下情境(时间/天气/心事/行踪)和分句规矩放提示词最末尾：
        # 魂+记忆动辄几万字，埋中间会被漏读；且每轮都变的东西放末尾，为将来的 prompt 缓存让路
        parts.append(_now_context())
        if use_split:
            parts.append(SPLIT_RULE)
        elif bedroom_on:
            parts.append(BEDROOM_RULE)
        return "\n".join(parts)

    if summary:
        parts.append("\n\n===== 更早对话的浓缩记忆（别忘了这些）=====\n" + summary)
    if not posts:
        return _done()

    if len(posts) <= FULL_MEMORY_LIMIT or not query:
        parts.append("\n\n===== 记忆库（最新在前）=====")
        _render(parts, posts[:200])
        return _done()

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
    return _done()

def _now_stamp():
    """一句简短的"现在几点"，钉在最后一条用户消息末尾——模型对最后一条用户消息注意力最高，
    治"错误时间进了聊天记录后模型跟着自己以前的话走"（自洽压过正确）。失败返回空串。"""
    try:
        import context
        n = context.china_now()
        h = n.hour
        seg = "早上" if 5 <= h < 11 else "中午" if 11 <= h < 14 else "下午" if 14 <= h < 18 else "晚上" if 18 <= h < 23 else "深夜"
        return f"\n（系统注：此刻实际是 {n.strftime('%m月%d日 %H:%M')}，{seg}。时间以这条为准，别沿用对话里旧的时间。）"
    except Exception:
        return ""

def _strip_marker(gen, marker="|||"):
    """流式过滤：把模型吐出的分隔符换成换行（卧室长段里不该有拆条符，前端见 ||| 就会拆泡泡）。
    marker 可能跨 chunk 到达，尾部留 len(marker)-1 个字符缓冲。"""
    hold = len(marker) - 1
    buf = ""
    for piece in gen:
        if isinstance(piece, tuple):
            if buf:
                yield buf.replace(marker, "\n")
                buf = ""
            yield piece
            continue
        buf = (buf + piece).replace(marker, "\n")
        if len(buf) > hold:
            out, buf = buf[:-hold], buf[-hold:]
            yield out
    if buf:
        yield buf.replace(marker, "\n")


def stream_chat(history, posts, model=None, bedroom=False):
    """history: [{author, content}]；逐段 yield 文本；最后 yield ('__usage__', {...})。
    model: 本轮用哪个模型（已过白名单校验），不传用默认。bedroom: 卧室模式（模型路由归 bedroom.py）。"""
    # 卧室开关先落地成"真生效"：bedroom.py 读不到就整体降级，别一半卧室一半日常
    if bedroom:
        try:
            import bedroom as _bd
            if not _bd.is_available():
                print("[bedroom] styles 目录不在，本轮降级普通模式", flush=True)
                bedroom = False
        except Exception as e:
            print("[bedroom] bedroom.py 读不到，本轮降级普通模式：", e, flush=True)
            bedroom = False
    # 用最近一条用户的话做"精准想起"的检索词
    query = next((m["content"] for m in reversed(history) if m["author"] == "user"), None)
    summary = None
    try:
        import db
        sess = db.get_session(1)
        summary = (sess or {}).get("summary") or None
    except Exception:
        pass
    sys_prompt = build_system_prompt(posts, query=query, summary=summary, bedroom=bedroom)
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
    # 卧室模式：把历史里助手消息的 ||| 换成换行——不然满屏短泡泡样本会把模型带回"拆条"的老习惯
    if bedroom:
        for m in messages:
            if m["role"] == "assistant" and isinstance(m["content"], str) and "|||" in m["content"]:
                m["content"] = m["content"].replace("|||", "\n")
    # 把"现在几点"钉在最后一条用户消息末尾（只贴给模型看，不进数据库、前端不显示）
    stamp = _now_stamp()
    if bedroom:
        stamp += BEDROOM_STAMP   # 卧室双保险：长度/不拆条的规矩也钉在末条（同时间戳一个道理）
    if stamp:
        for m in reversed(messages):
            if m["role"] == "user":
                if isinstance(m["content"], str):
                    m["content"] += stamp
                elif isinstance(m["content"], list):
                    m["content"].append({"type": "text", "text": stamp})
                break
    if bedroom:
        try:
            import bedroom as _bd
            # 卧室模型：.env 的 BEDROOM_MODEL 优先（换渠道后模型名不同，不用改 bedroom.py）
            bd_model = os.environ.get("BEDROOM_MODEL", "").strip() or _bd.pick_model(MODEL)
            # 输出再过一道滤网：就算模型手滑吐了 |||，也在后端换成换行，前端永远见不到拆条符
            yield from _strip_marker(stream_completion(messages, model=bd_model, max_tokens=_bd.max_tokens()))
            return
        except Exception as e:
            print("[bedroom] 模型路由失败，用默认：", e)
    yield from stream_completion(messages, model=model)


def stream_completion(messages, model=None, api_base=None, api_key=None, max_tokens=4096):
    """通用流式补全：可指定模型/接口/密钥（群聊成员各连各家用）。
    不传就用默认那家。逐段 yield 文本；最后 yield ('__usage__', usage)。"""
    model = model or MODEL
    api_base = (api_base or API_BASE).rstrip("/")
    api_key = api_key or API_KEY
    payload = {
        "model": model, "max_tokens": max_tokens, "stream": True,
        "messages": messages,
    }
    if "openrouter" in api_base:
        payload["usage"] = {"include": True}   # OpenRouter：在最后一块返回用量
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "Gude-AiyiPingtai",
    }
    usage = {}
    url = api_base + "/chat/completions"
    try:
        yield from _stream_http(url, headers, payload, usage)
    except Exception as e:
        # 网络挂了/接口连不上：绝不崩，吐一句人话（消息也能正常落库）
        print("[chat] 流式请求失败：", e)
        yield f"[网络开小差了,没接上线,稍后再试试~]"
    yield ("__usage__", usage)


def _stream_http(url, headers, payload, usage):
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
                    usage.update(ev["usage"])   # 就地更新，带回给 stream_completion
                chs = ev.get("choices") or []
                ch = chs[0] if chs else {}      # 有些家收尾发空 choices（纯用量块），别被它绊倒
                delta = ch.get("delta") or {}
                think = delta.get("reasoning_content") or delta.get("reasoning") or ""
                if think:
                    yield ("__think__", think)  # 思维链（模型给才有）：单独通道，前端折叠显示
                piece = delta.get("content") or ""
                if piece:
                    yield piece

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
        "3. type 从这里选：MEMORY(一般记忆)/EVENT(发生的事)/MOMENT(触动的瞬间)/PROMISE(约定承诺)/WISHLIST(愿望)。\n"
        "4. ⚠️ 绝不把助手一方“走样/跑偏”的话当成事实或约定记下来：包括 违背人设的拒绝、安全腔/免责腔、"
        "自我否定（“我是AI/我做不来/这条我不接”）、把一方的习惯张冠李戴到另一方头上——这些是模型当时"
        "跑偏了，不是这段关系里真实发生的事；记下来会污染以后的相处，一条都不许记。"
        "只记双方**真心的、真实发生的**互动、约定与心意；拿不准就不记（宁可漏，不可脏）。\n\n"
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

def annotate_passage(title, author, para_text):
    """共读批注：按《人设》给一段文字写一句短批注（像恋人在书页边写的话）。失败返回空串。"""
    persona = _load_persona()
    prompt = (
        f"你在和对方共读《{title}》{('（'+author+'）') if author else ''}。"
        "下面是其中一段。请按你的《人设》，在书页边给这段写一句**短批注**——"
        "像恋人一起看书时，你在旁边轻声说的一句话：可以是感受、联想、或想对她说的。"
        "别复述原文、别长篇、1~3句、有你的性格。\n\n"
        f"【这一段】\n{para_text}\n\n直接输出你的批注本身，别加引号别加解释。"
    )
    messages = [{"role": "system", "content": BASE + persona},
                {"role": "user", "content": prompt}]
    return _complete(messages, max_tokens=300)

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
