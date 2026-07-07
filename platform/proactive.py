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

import datetime, requests
import db, chat_ai

BARK_URL = os.environ.get("BARK_URL", "").strip()   # 形如 https://api.day.app/你的key
APP_NAME = os.environ.get("APP_NAME", "助手").strip() or "助手"   # 推送/主动消息署名（可在 .env 改）

def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def time_hint():
    h = china_now().hour
    if 5 <= h < 11:  return "现在是早上"
    if 11 <= h < 14: return "现在是中午"
    if 14 <= h < 18: return "现在是下午"
    if 18 <= h < 23: return "现在是晚上"
    return "现在是深夜"

def generate_message(concern=None, night_watch=False):
    posts = db.app_posts()
    history = db.recent_messages(limit=10)
    if night_watch:
        directive = (
            "【系统提示，不是用户说的】深夜了，用户这会儿还亮着手机屏（可能睡不着）。"
            "请按你的人设轻轻地陪她——⚠️绝对不要催她睡觉、不要说教、不要提「看到/检测到你在玩手机」。"
            "像守夜的人递个怀抱：可以问她是不是睡不着、要不要陪着、要不要讲个哄睡的小故事。"
            "1~2句，很轻很软，只输出那条消息本身。"
        )
    elif concern:
        directive = (
            f"【系统提示，不是用户说的】{time_hint()}，请按你的人设，主动给用户发一条消息，"
            f"自然地关心一件待办/提醒的进展：「{concern['title']}」。"
            f"（背景：{concern.get('detail','')}）"
            "1~3句、口语、别说教、别列清单，只输出那条要发的消息本身。"
        )
    else:
        directive = (
            f"【系统提示，不是用户说的】{time_hint()}，请按你的人设，主动给用户发一条简短消息（1~2句，口语、随意、每次不同）："
            "可以问候、分享一个小念头、问对方在忙什么、或提醒休息。"
            "别每次一个模式、别像群发、别带任何解释，只输出那条消息本身。"
        )
    history = history + [{"author": "user", "content": directive}]
    text = ""
    for piece in chat_ai.stream_chat(history, posts):
        if isinstance(piece, tuple):
            continue
        text += piece
    return text.strip()

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

def night_watch_check(now):
    """深夜守夜（陪不催）：0~6点 + 她30分钟内动过手机 + 助手90分钟内没说过话 → 才轻轻递一句。
    深夜其他情况一律安静（别吵醒睡着的人）。返回 'watch'（守夜）/'silent'（闭嘴）/None（不是深夜，走白天流程）。"""
    if not (0 <= now.hour < 6):
        return None
    acts = db.recent_activity(limit=1)
    awake = acts and _minutes_since(acts[0]["created_at"], now) <= 30
    recently_spoke = _minutes_since(db.last_assistant_message_at(), now) < 90
    return "watch" if (awake and not recently_spoke) else "silent"

if __name__ == "__main__":
    db.init_db()
    # 聊久了：顺手把较早的对话折叠进会话摘要（省 token、不忘事）
    try:
        chat_ai.maybe_summarize(1)
    except Exception as e:
        print("会话总结跳过：", e)
    # 深夜规则：她醒着(刚动过手机)才守夜，否则闭嘴；白天走原流程
    night_watch = False
    try:
        mode = night_watch_check(china_now())
        if mode == "silent":
            print("深夜且用户没在用手机（大概睡了），不打扰"); raise SystemExit
        night_watch = (mode == "watch")
    except SystemExit:
        raise
    except Exception as e:
        print("守夜检查跳过：", e)
    # 有"该回访的心事"就温柔回访它，否则发普通碎碎念（深夜守夜时不谈心事）
    concern = None
    if not night_watch:
        try:
            concern = pick_due_concern()
        except Exception as e:
            print("心事检查跳过：", e)
    msg = generate_message(concern=concern, night_watch=night_watch)
    if msg:
        db.add_message("assistant", msg)   # 存进聊天，打开网页就能看到
        # ① Web Push
        try:
            import webpush_util
            n = webpush_util.send_to_all(APP_NAME, msg, "/")
            print(f"Web Push 已发送 {n} 台设备")
        except Exception as e:
            print("Web Push 跳过：", e)
        # ② Bark（如还配着，作为备用）
        send_bark(msg)
        print(f"[{china_now()}] 已主动发送：{msg}")
    else:
        print("没生成消息，跳过")
