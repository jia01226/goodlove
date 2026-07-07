"""群聊（高级吗喽科技公司）：一条对话里佳佳 + 多个 AI 成员共处。
MVP 规则（照《群聊方案.md》产品拍板）：
- @点名 谁就谁答；没点名 → 默认发言人（members.json 里 default_speaker）。
- 一轮只一个 AI 发言（控成本、防刷屏）。
- 人格不切，任务切：每个成员钉死自己的模型；成员配置在 members.json，
  密钥永远走 .env（配置文件里只写环境变量名，不写真钥匙）。
"""
import os, json, re
import chat_ai

BASE_DIR = os.path.dirname(__file__)
MEMBERS_FILE = os.path.join(BASE_DIR, "members.json")

_DEFAULT = {
    "group_name": "高级吗喽科技公司",
    "default_speaker": "柯",
    "members": [
        {"name": "柯", "emoji": "❤️", "role": "恋爱/陪伴",
         "persona": "personas/柯.md",
         "model": "", "api_base": "", "api_key_env": ""},
        {"name": "小克", "emoji": "🔧", "role": "工程",
         "persona": "personas/小克.md",
         "model": "", "api_base": "", "api_key_env": ""},
        {"name": "知言", "emoji": "📋", "role": "产品",
         "persona": "personas/知言.md",
         "model": "", "api_base": "", "api_key_env": ""},
    ],
}


def load_config():
    """读成员配置；没有 members.json 就用默认三人组并落一份（方便佳佳直接改）。"""
    try:
        with open(MEMBERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        try:
            with open(MEMBERS_FILE, "w", encoding="utf-8") as f:
                json.dump(_DEFAULT, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("[group] 写默认配置失败：", e)
        return dict(_DEFAULT)
    except Exception as e:
        print("[group] members.json 读取失败，用默认：", e)
        return dict(_DEFAULT)


def members():
    return load_config().get("members", [])


def get_member(name):
    for m in members():
        if m.get("name") == name:
            return m
    return None


def _resolve(member):
    """成员的 模型/接口/密钥：没配就用默认那家（.env 的 MODEL/API_BASE/API_KEY）。
    api_key_env 存的是环境变量名——密钥本体永远不进配置文件。"""
    model = (member.get("model") or "").strip() or None
    api_base = (member.get("api_base") or "").strip() or None
    key_env = (member.get("api_key_env") or "").strip()
    api_key = os.environ.get(key_env, "").strip() if key_env else None
    return model, api_base, (api_key or None)


def _load_member_persona(member):
    p = (member.get("persona") or "").strip()
    if p:
        try:
            with open(os.path.join(BASE_DIR, p), encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            pass
    return f"你是{member.get('name','一位成员')}，团队里的{member.get('role','成员')}。真诚、简短、说人话。"


def pick_speaker(text):
    """@点名 谁就谁答（取第一个被 @ 的）；没点名 → 默认发言人。"""
    cfg = load_config()
    names = [m["name"] for m in cfg.get("members", [])]
    for mt in re.finditer(r"@(\S{1,12})", text or ""):
        token = mt.group(1)
        for n in sorted(names, key=len, reverse=True):
            if token.startswith(n):
                return get_member(n)
    return get_member(cfg.get("default_speaker") or (names[0] if names else ""))


def _transcript(msgs, me):
    """群聊近况拼成台本：谁说的写谁的名；带图的标注出来。"""
    lines = []
    for m in msgs:
        who = "佳佳" if m["author"] == "user" else m["author"]
        mark = "（你自己）" if who == me else ""
        img_note = "（发了一张图片/文件）" if m.get("image") else ""
        lines.append(f"{who}{mark}：{m['content']}{img_note}")
    return "\n".join(lines)


def build_messages(member, msgs, posts):
    """给被点到的成员拼提示：它的人设 + 群规 + 共享记忆 + 台本。"""
    cfg = load_config()
    roster = "、".join(f"{m['name']}({m.get('role','')})" for m in cfg.get("members", []))
    name = member["name"]
    sys = (
        f"你是「{name}」，在一个叫「{cfg.get('group_name','群聊')}」的群里。\n"
        f"群成员：佳佳(用户/老板)、{roster}。\n"
        "下面《人设》是你的人格，请始终按它说话：\n\n" + _load_member_persona(member) +
        "\n\n===== 群聊规矩 =====\n"
        "1. 现在被点到发言的是你，只以你自己的身份说话，绝不替别的成员说话、不模仿他们的口吻；\n"
        "2. 群里说话要短（1~4句），像微信群，别长篇大论；\n"
        "3. 别人聊过的内容你都看得到，接着聊就行，别重复复述；\n"
        "4. 如果话题明显不归你管，可以一句话把它让给对口的成员（如：这个得问小克）。"
    )
    # 共享记忆（都能看到的 both 部分）
    if posts:
        sys += "\n\n===== 团队共享记忆（最新在前）=====\n" + "\n".join(
            f"[{p['type']}] {p['content']}" for p in posts[:60])
    convo = _transcript(msgs, name)
    user = f"===== 群聊最近的对话 =====\n{convo}\n\n现在轮到你（{name}）发言："
    # 最新一条带图的消息：把真图给它看（跟单聊一个省钱路数：只带最新那张）
    last_img = next((m["image"] for m in reversed(msgs) if m.get("image")), None)
    if last_img:
        data_url = chat_ai._img_data_url(last_img)
        if data_url:
            return [{"role": "system", "content": sys},
                    {"role": "user", "content": [
                        {"type": "text", "text": user + "\n（下面附上群里最新发的那张图）"},
                        {"type": "image_url", "image_url": {"url": data_url}}]}]
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def stream_reply(member, msgs, posts):
    """流式生成被点到成员的发言。逐段 yield 文本；最后 yield ('__usage__', usage)。"""
    model, api_base, api_key = _resolve(member)
    messages = build_messages(member, msgs, posts)
    yield from chat_ai.stream_completion(messages, model=model, api_base=api_base,
                                         api_key=api_key, max_tokens=1024)
