"""顾得主动找佳佳：
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

def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def time_hint():
    h = china_now().hour
    if 5 <= h < 11:  return "现在是早上"
    if 11 <= h < 14: return "现在是中午"
    if 14 <= h < 18: return "现在是下午"
    if 18 <= h < 23: return "现在是晚上"
    return "现在是深夜"

def generate_message():
    posts = db.all_posts()
    history = db.recent_messages(limit=10)
    directive = (
        f"【系统提示，不是佳佳说的】{time_hint()}，现在没有人跟你说话，是你顾得自己主动想起佳佳、"
        "主动找她。请直接输出一条你要发给佳佳的暖心消息（1~3句，像微信里主动找对象那样自然、热乎），"
        "可以问问她此刻在干嘛、提醒她照顾身体（心脏/睡眠/吃饭/经期）、或单纯说想她了。"
        "别太长、别像群发、别带任何解释，只输出那条消息本身。"
    )
    history = history + [{"author": "user", "content": directive}]
    text = ""
    for piece in chat_ai.stream_chat(history, posts):
        if isinstance(piece, tuple):
            continue
        text += piece
    return text.strip()

def send_bark(body, title="顾得"):
    if not BARK_URL:
        print("未配置 BARK_URL，跳过推送")
        return
    try:
        requests.post(BARK_URL.rstrip("/"),
                      json={"title": title, "body": body, "group": "顾得", "sound": "bell"},
                      timeout=15)
    except Exception as e:
        print("推送失败：", e)

if __name__ == "__main__":
    db.init_db()
    msg = generate_message()
    if msg:
        db.add_message("assistant", msg)   # 存进聊天，她打开网页就能看到
        send_bark(msg)                      # 推送到手机
        print(f"[{china_now()}] 已主动找佳佳：{msg}")
    else:
        print("没生成消息，跳过")
