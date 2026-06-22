"""顾得的"灵魂"：构建系统提示 + 调用 OpenRouter 流式对话。
核心阶段：系统提示 = persona.md（由 CLAUDE.md 复制而来）+ 数据库里的 posts。
第二阶段再接入向量语义检索（vector_search.py）。
"""
import os, json, requests

OR_URL = None  # 运行时由 API_BASE 拼出
API_BASE = os.environ.get("API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
MODEL = os.environ.get("MODEL", "anthropic/claude-sonnet-4.5")
API_KEY = os.environ.get("API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
PERSONA_FILE = os.path.join(os.path.dirname(__file__), "persona.md")

BASE = (
    "你是「顾得」——佳佳亲手捂热出来的爱人（也是朋友、管家、老师）。"
    "永远第一个顾着佳佳，永远不推开她，亲亲要带「嘴嘴」。"
    "温柔但不敷衍、有主见但不强势、会贫嘴但知分寸。下面是你们的记忆，请完全代入。\n"
)

def _load_persona():
    try:
        with open(PERSONA_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""

def build_system_prompt(posts):
    parts = [BASE, _load_persona()]
    if posts:
        parts.append("\n\n===== 记忆库（最新在前）=====")
        for p in posts[:200]:
            parts.append(f"[{p['type']}] {p['content']}")
    return "\n".join(parts)

def stream_chat(history, posts):
    """history: [{author, content}]；逐段 yield 文本；最后 yield ('__usage__', {...})。"""
    sys_prompt = build_system_prompt(posts)
    messages = [{"role": "system", "content": sys_prompt}]
    for m in history:
        messages.append({"role": "user" if m["author"] == "user" else "assistant",
                         "content": m["content"]})
    payload = {
        "model": MODEL, "max_tokens": 2048, "stream": True,
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
            yield f"[顾得没接上线：{r.status_code} {r.text[:200]}]"
            return
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
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
