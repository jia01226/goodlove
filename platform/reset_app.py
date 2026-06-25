"""把 app 清成一张干净的白纸：
   删除所有对话、记忆、个人数据、纪念日、待办、行踪、摘要，并清空人设(persona.md)。
   —— 功能/代码全部保留，推送订阅也保留(这样推送还能用)。
   用法（在服务器 platform/ 目录）：  ./venv/bin/python reset_app.py
"""
import os
import db

KEEP = {"push_subscriptions"}   # 保留：推送订阅（删了就得重新开启推送）
WIPE = ["chat_messages", "posts", "embeddings", "concerns",
        "anniversaries", "period_logs", "shifts", "activity", "gateway_usage"]

def wipe():
    db.init_db()
    conn = db.get_db()
    for t in WIPE:
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception as e:
            print("跳过", t, e)
    # 会话清空摘要、改回中性名字
    try:
        conn.execute("UPDATE chat_sessions SET summary='', summarized_until=0, name='对话'")
    except Exception as e:
        print("会话重置跳过：", e)
    conn.commit(); conn.close()
    # 清空人设
    p = os.path.join(os.path.dirname(__file__), "persona.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# 人设（请在这里写这个 AI 的设定）\n\n"
                "（暂未设置。把你想要的角色设定写在这里，保存后重启即可。）\n")
    print("✅ 已清空：所有对话/记忆/个人数据 + 人设。功能和推送订阅保留。")
    print("   想设新角色：编辑 persona.md，然后 systemctl restart gude")

if __name__ == "__main__":
    wipe()
