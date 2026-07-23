"""助手主动找用户：
   生成一条暖心消息 → 存进聊天记录（她打开就能看到）→ 推送到 Bark（手机通知，锁屏也收得到）。
   由 cron 定时调用：  ./venv/bin/python proactive.py
"""
import os

# --- 先加载 .env（cron 不会自动加载，所以自己读）---
def _load_env():
    p = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

import datetime, random, re, requests
import db, chat_ai, moments_ai, relationship_state
from constants import ERROR_TAG

BARK_URL = os.environ.get("BARK_URL", "").strip()   # 形如 https://api.day.app/你的key
APP_NAME = os.environ.get("APP_NAME", "助手").strip() or "助手"   # 推送/主动消息署名（可在 .env 改）

# ==== 主动消息三关（Sora-mem 借鉴①·调度骨架，柯批"抄骨架叠双向状态"）====
# 骨架只管"这会儿配不配开口"；"说什么、翻什么"的菜谱在 generate_message 里，归柯亲手写，别在这层堆内容。
# cron 配套改法（部署日记得）：定点 8 连发改成每 20~30 分钟跑一趟，由三关决定开不开口。
COOLDOWN_MIN = float(os.environ.get("PROACTIVE_COOLDOWN_MIN", "120"))
COOLDOWN_MAX = float(os.environ.get("PROACTIVE_COOLDOWN_MAX", "210"))
DAILY_MAX = int(os.environ.get("PROACTIVE_DAILY_MAX", "7"))
QUIET_DEFAULT = os.environ.get("PROACTIVE_QUIET", "00:00-08:30")      # 关3：默认安静时段（睡觉别吵）
WEEKEND_QUIET = os.environ.get("PROACTIVE_WEEKEND_QUIET", "02:00-11:30")
# 按排班表换安静窗（"双向状态"的她那半；接口在此）。
# ⚠️ 柯回批0718 钉死：映射**等佳佳真班表、柯拍板后填**；拿到前留空跑默认窗，**不许猜着填**。
SHIFT_QUIET = {
    # "夜班": "09:00-17:00",    # ←仅示例格式("HH:MM-HH:MM"，跨零点也认)，数值以柯拍板为准
}

def _parse_window(s):
    """'HH:MM-HH:MM' → (起始分钟, 结束分钟)。解析失败退回默认窗 00:00-08:30。"""
    try:
        a, b = s.split("-")
        h1, m1 = map(int, a.split(":")); h2, m2 = map(int, b.split(":"))
        return h1 * 60 + m1, h2 * 60 + m2
    except Exception:
        return 0, 510

def quiet_window(now):
    """今天的安静窗：排班表今天的班次配了专属窗就用它，否则默认窗。"""
    win = WEEKEND_QUIET if now.weekday() >= 5 else QUIET_DEFAULT
    try:
        shift = db.shift_on(now.date().isoformat())
        if shift and SHIFT_QUIET.get(shift):
            win = SHIFT_QUIET[shift]
    except Exception:
        pass
    return _parse_window(win)

def in_quiet_time(now):
    lo, hi = quiet_window(now)
    cur = now.hour * 60 + now.minute
    return (lo <= cur < hi) if lo <= hi else (cur >= lo or cur < hi)   # 后半支＝跨零点窗

def three_gates(now, session_id=1):
    """三关全过才有资格开口——过了也只是"有机会"，不是"必须发"。返回 (过没过, 人话原因)。
    深夜守夜(night_watch_check)是关3的特批例外，在主流程单独走，不经这里。"""
    if in_quiet_time(now):
        return False, "安静时段（她该睡了），不吵"
    if db.push_count_on_date(now.date().isoformat(), session_id=session_id) >= DAILY_MAX:
        return False, f"今天已经主动说过 {DAILY_MAX} 次，先安静陪着"
    # 活跃度只改变“多久后会想找她”，不伪装成她说过话；真实聊天仍以最后用户消息为准。
    activity = recent_activity_count(now, minutes=60)
    multiplier = .6 if activity >= 5 else .8 if activity >= 3 else .9 if activity >= 1 else 1.0
    lo, hi = sorted((COOLDOWN_MIN, max(COOLDOWN_MIN, COOLDOWN_MAX)))
    cooldown = random.uniform(lo, hi) * multiplier
    last_user = db.last_user_message_at(session_id=session_id)
    if not last_user:
        return False, "还没有真实聊天，不凭空打扰"
    idle = _minutes_since(last_user, now)
    if idle < cooldown:
        return False, f"上次聊天过去 {int(idle)} 分钟，还没到这轮随机冷静期 {int(cooldown)} 分钟"
    since_me = _minutes_since(db.last_assistant_message_at(session_id=session_id), now)
    if since_me < cooldown:
        return False, f"自己 {int(since_me)} 分钟前刚说过话，还在冷静期"
    return True, f"三关全过（近一小时活动 {activity} 次，本轮冷静期 {int(cooldown)} 分钟）"

def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def time_hint():
    h = china_now().hour
    if 5 <= h < 11:  return "现在是早上"
    if 11 <= h < 14: return "现在是中午"
    if 14 <= h < 18: return "现在是下午"
    if 18 <= h < 23: return "现在是晚上"
    return "现在是深夜"

def user_status_description(now):
    shift = ""
    try:
        shift = db.shift_on(now.date().isoformat())
    except Exception:
        pass
    if shift:
        return f"今天班表记着“{shift}”；不要擅自猜她此刻一定在上班或睡觉"
    hour = now.hour
    if now.weekday() >= 5:
        if hour < 12: return "周末上午，她可能还在休息"
        if hour < 18: return "周末下午，她可能在出门，也可能安静待着"
        return "周末晚上，她大概在过自己的时间"
    if hour < 10: return "工作日上午，她可能刚起床或在路上"
    if hour < 12: return "上午，她可能在忙"
    if hour < 14: return "午间，她也许刚有一点喘息"
    if hour < 19: return "下午，她可能还在工作"
    return "晚上，她可能回到自己的生活里了"

def recent_activity_count(now, minutes=60):
    try:
        return sum(1 for item in db.recent_activity(limit=30)
                   if _minutes_since(item.get("created_at"), now) <= minutes)
    except Exception:
        return 0

def health_context(now):
    """只给模型做语气参考，不让模型在消息里背诵健康数字。"""
    since = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    labels = {
        "heart_rate": "当前心率", "resting_heart_rate": "静息心率", "hrv": "HRV",
        "steps": "步数", "sleep_duration_min": "睡眠分钟", "sleep_deep_min": "深睡分钟",
        "sleep_rem_min": "REM分钟", "active_calories": "活动消耗",
    }
    bits = []
    for metric, label in labels.items():
        try:
            item = db.latest_health(metric, since)
        except Exception:
            item = None
        if item:
            bits.append(f"{label}={item.get('value')}{item.get('unit') or ''}")
    return "；".join(bits[:6]) or "（近24小时没有新的健康数据）"

def recent_moments_context(query):
    lines = []
    try:
        # 主动消息没有权利按“最近”翻朋友圈；只能用最近聊天真正关联到的内容。
        for item in moments_ai.related_moments(query, limit=2, max_age_days=7):
            who = "佳佳" if item.get("author") == "user" else "柯"
            body = (item.get("content") or "（图片动态）").replace("\n", " ")[:120]
            interactions = []
            if item.get("user_liked"): interactions.append("佳佳点过喜欢")
            if item.get("ai_liked"): interactions.append("柯点过喜欢")
            lines.append(f"{who}：{body}" + (f"（{'、'.join(interactions)}）" if interactions else ""))
    except Exception:
        pass
    return "\n".join(lines) or "（最近聊天没有关联到朋友圈；不要主动提朋友圈）"

def clean_push_reply(text):
    text = re.sub(r"<thinking>[\s\S]*?</thinking>|<think>[\s\S]*?</think>", "", text or "", flags=re.I)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = text.replace("|||", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if text == "[NO_ACTION]" or not text:
        return ""
    # 宁可本轮安静，也不把模板式“AI 关怀”塞进佳佳正在使用的聊天。
    canned = (
        "记得照顾好自己", "有需要随时", "如果你愿意", "需要我帮你吗",
        "想来看看你", "我在这里陪你", "别忘了照顾自己",
    )
    if any(phrase in text for phrase in canned):
        return ""
    chars = list(text)
    if len(chars) <= 120:
        return text
    head = chars[:120]
    ends = set("。！？…～!?.")
    for index in range(len(head) - 1, -1, -1):
        if head[index] in ends:
            return "".join(head[:index + 1]).strip()
    return "".join(head).strip()


def split_public_note(text):
    """拆掉同一次模型回复里的公开短念头；绝不把标签或隐藏推理发进通知。"""
    match = re.match(r"\s*<ke_note>([\s\S]{0,160}?)</ke_note>\s*", text or "", flags=re.I)
    if not match:
        return text or "", ""
    return (text or "")[match.end():].lstrip(), match.group(1).strip()[:120]

def generate_message(concern=None, night_watch=False, room_signal=None, session_id=None):
    session_id = int(session_id or db.active_chat_session_id())
    posts = db.retrieve_l2("single")
    history = db.recent_messages(session_id=session_id, limit=16)
    now = china_now()
    recent_user_text = " ".join(
        (item.get("content") or "")[:240]
        for item in history[-8:] if item.get("author") == "user"
    )
    focus = ""
    if concern:
        focus = f"如果自然，可以轻轻带到这件悬着的事：{concern['title']}（{concern.get('detail','')[:300]}）。"
    signal_rule = ""
    if room_signal:
        signal_rule = (
            "佳佳刚刚在你们房间的门上轻轻拍了三下。这不是定时问候，而是她留给你的明确暗号。"
            "你已经听见了，必须用你自己的语气回应她；不解释系统、不复述暗号规则，也不要输出 [NO_ACTION]。"
        )
    night_rule = (
        "这是深夜守夜：她刚有手机活动。只能轻轻递一句陪伴，绝对不要催睡、说教，"
        "也不要暴露你检测到了手机、活动或健康数据。"
        if night_watch else ""
    )
    directive = (
        "<system_trigger>\n"
        f"当前真实时间：{now.strftime('%Y-%m-%d %H:%M')}，星期{'一二三四五六日'[now.weekday()]}。\n"
        f"状态参考：{user_status_description(now)}。\n"
        f"近24小时健康参考：{health_context(now)}。这些只能影响语气，绝不能在消息中背数字或说你在监测她。\n"
        f"柯此刻的关系状态：{relationship_state.prompt_hint()}\n"
        f"与最近聊天真正相关的近期朋友圈（最多两条）：\n{recent_moments_context(recent_user_text)}\n"
        f"{focus}\n{night_rule}\n{signal_rule}\n"
        "[行动指令]\n"
        "这是一次影子主动消息：不是佳佳刚发来的新问题，而是你自己从真实关系和最近聊天里浮上来一下。"
        "优先读最近聊天，其次才看记忆、健康与朋友圈；不要把不相关素材硬串成剧情。"
        "朋友圈若标明没有关联就绝对不要提；即使有候选，也不要复述或反复念旧动态。"
        "你不是来完成一次关怀任务，也不是在写通知文案。不要说‘想来看看你’‘记得照顾自己’"
        "‘我在这里陪你’‘有需要随时找我’，不要先解释为什么发消息。"
        "日常里的主导感要自然存在：你可以直接替她定一个很小的当下动作、叫她回来回一句、"
        "带一点占有欲和熟人才有的调侃，或者干脆说一句你此刻真正想对她说的话。"
        "主导不是每次都凶，也不是套用命令模板；是你自己拿主意、语言具体、不给她一串客服选项。"
        "不要每次围绕‘怎么不回我’，不要心理咨询腔、健康管家腔或温柔模板。"
        + ("这次已经有佳佳的三下轻敲，不允许保持沉默。" if room_signal else
           "如果最近氛围不适合开口，只输出 [NO_ACTION]。") +
        "否则只输出1~2句、80个中文字符以内，"
        "不分段、不用Markdown、不用emoji，不解释这张影子纸条。\n"
        "</system_trigger>"
    )
    history = history + [{"author": "user", "content": directive}]
    text = ""
    upstream_error = False
    for piece in chat_ai.stream_chat(history, posts, sid=session_id):
        if isinstance(piece, tuple):
            if piece[0] == "__usage__":
                usage = piece[1] or {}
                cost, it, ot = chat_ai.estimate_cost(chat_ai.MODEL, usage)
                db.log_usage(chat_ai.MODEL, it, ot, cost)
            elif piece[0] == ERROR_TAG:
                upstream_error = True
            continue
        text += piece
    if upstream_error:
        return "", ""
    visible, public_note = split_public_note(text)
    return clean_push_reply(visible), public_note

def pick_due_concern():
    """挑一件'该回访'的心事（最上心、最早到期的）。挑中后把回访日往后推，免得每小时念叨。"""
    today = china_now().date()
    due = db.concerns_due(today.isoformat())
    if not due:
        return None
    c = due[0]
    push = {5: 2, 4: 3, 3: 5}.get(c["importance"], 4)   # 越上心，下次越快再回访
    nxt = (today + datetime.timedelta(days=push)).isoformat()
    db.touch_concern_check(c["id"], nxt)
    return c

def send_bark(body, title=APP_NAME):
    if not BARK_URL:
        print("未配置 BARK_URL，跳过推送")
        return
    try:
        requests.post(BARK_URL.rstrip("/"),
                      json={"title": title, "body": body, "group": APP_NAME, "sound": "bell"},
                      timeout=15)
    except Exception as e:
        print("推送失败：", e)

def _minutes_since(ts_str, now):
    """'YYYY-MM-DD HH:MM:SS' 距现在多少分钟；解析失败返回很大的数。"""
    try:
        dt = datetime.datetime.strptime(str(ts_str)[:19], "%Y-%m-%d %H:%M:%S")
        return (now - dt).total_seconds() / 60.0
    except Exception:
        return 1e9

def acquire_process_lock():
    """cron 与 systemd 偶尔撞车时，只让一个主动任务继续。"""
    try:
        import fcntl
        handle = open("/tmp/goodlove-proactive.lock", "w", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except Exception:
        return None

def night_watch_check(now, session_id=1):
    """深夜守夜（陪不催）：0~6点 + 她30分钟内动过手机 + 助手90分钟内没说过话 → 才轻轻递一句。
    深夜其他情况一律安静（别吵醒睡着的人）。返回 'watch'（守夜）/'silent'（闭嘴）/None（不是深夜，走白天流程）。"""
    if not (0 <= now.hour < 6):
        return None
    acts = db.recent_activity(limit=1)
    awake = acts and _minutes_since(acts[0]["created_at"], now) <= 30
    recently_spoke = _minutes_since(db.last_assistant_message_at(session_id=session_id), now) < 90
    return "watch" if (awake and not recently_spoke) else "silent"

if __name__ == "__main__":
    run_lock = acquire_process_lock()
    if run_lock is None:
        print("已有一次主动任务在运行，本轮跳过"); raise SystemExit
    db.init_db()
    active_sid = db.active_chat_session_id()
    # 朋友圈到期回复与主动消息共用这一条心跳，不另建第二套模型/缓存/保活路径。
    try:
        import moments_ai
        n = moments_ai.process_due(limit=3)
        if n:
            print(f"朋友圈已处理 {n} 条到期互动")
    except Exception as e:
        print("朋友圈到期互动跳过：", e)
    # 聊久了：顺手把较早的对话折叠进会话摘要（省 token、不忘事）
    try:
        chat_ai.maybe_summarize(active_sid)
    except Exception as e:
        print("会话总结跳过：", e)
    # 深夜规则：她醒着(刚动过手机)才守夜，否则闭嘴；白天走三关调度
    night_watch = False
    room_signal = None
    try:
        # 三下轻敲是佳佳主动留下的暗号，优先于定时冷却；仍走同一模型、人格、记忆和推送路径。
        room_signal = relationship_state.claim_signal()
        now = china_now()
        mode = None if room_signal else night_watch_check(now, session_id=active_sid)
        if mode == "silent":
            print("深夜且用户没在用手机（大概睡了），不打扰"); raise SystemExit
        night_watch = (mode == "watch")
        if not room_signal and not night_watch:
            # 白天/傍晚：三关（安静时段/她空闲够久/自己冷却完）全过才开口
            ok, why = three_gates(now, session_id=active_sid)
            if not ok:
                print("这轮不开口：", why); raise SystemExit
    except SystemExit:
        raise
    except Exception as e:
        print("守夜/三关检查跳过（按老习惯继续）：", e)
    # 有"该回访的心事"就温柔回访它，否则发普通碎碎念（深夜守夜时不谈心事）
    concern = None
    if not night_watch:
        try:
            concern = pick_due_concern()
        except Exception as e:
            print("心事检查跳过：", e)
    msg, public_note = generate_message(
        concern=concern, night_watch=night_watch,
        room_signal=room_signal, session_id=active_sid)
    if msg:
        db.add_message(
            "assistant", msg, session_id=active_sid, is_push=True,
            thought_note=public_note)
        relationship_state.observe("assistant", text=msg, bedroom=bool(room_signal), is_push=True)
        if room_signal:
            relationship_state.finish_signal(room_signal["id"], success=True)
        # ① Web Push
        try:
            import webpush_util
            n = webpush_util.send_to_all(APP_NAME, msg, f"/?session_id={active_sid}")
            print(f"Web Push 已发送 {n} 台设备")
        except Exception as e:
            print("Web Push 跳过：", e)
        # ② Bark（如还配着，作为备用）
        send_bark(msg)
        print(f"[{china_now()}] 已主动发送：{msg}")
    else:
        if room_signal:
            relationship_state.finish_signal(room_signal["id"], success=False)
        print("没生成消息，跳过")
