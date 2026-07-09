"""夜班小工人（一趟干三件，按柯的要求"合流不跑两趟"）：
   ① 睡前日记：回顾当天对话，替角色写一篇碎碎念（枕边日记）
   ② 消化记忆（做梦的里子）：把当天要紧事提炼成 0~3 条，存进记忆库+建向量
   ③ 做梦（面子）：按人设生成一篇"昨晚的梦"，早上给对方翻
   三件互相独立，谁失败都不影响别人。
   由 cron 定时调用（建议 23:30）：  ./venv/bin/python diary_writer.py
   crontab 示例：  30 23 * * *  cd /path/to/platform && ./venv/bin/python diary_writer.py
"""
import os

# --- 先加载 .env（cron 不会自动加载，所以自己读；跟 proactive.py 一个路数）---
def _load_env():
    p = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

import datetime
import db, chat_ai, diary_sync

def china_today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date().isoformat()

if __name__ == "__main__":
    db.init_db()
    today = china_today()
    # ① 睡前日记
    try:
        if db.diary_written_today(today, "diary"):
            print(f"[{today}] 日记：今天写过了，跳过")
        else:
            entry = chat_ai.write_diary(today)
            if entry:
                did = db.add_diary(entry["title"], entry["content"], entry["mood"], entry["locked"])
                lock = "🔒" if entry["locked"] else ""
                print(f"[{today}] 日记 ✅ #{did} {lock}「{entry['title']}」({entry['mood']})")
            else:
                print(f"[{today}] 日记：今天没聊过天（或生成失败），不写")
    except Exception as e:
        print(f"[{today}] 日记出错（不影响后面）：", e)
    # ② 消化记忆（里子）
    try:
        saved = chat_ai.consolidate_memories(today)
        if saved:
            for pid, c in saved:
                print(f"[{today}] 消化 ✅ 记忆#{pid}：{c[:40]}")
        else:
            print(f"[{today}] 消化：今天没有值得长期记的（宁缺毋滥）")
    except Exception as e:
        print(f"[{today}] 消化出错（不影响后面）：", e)
    # ③ 做梦（面子）
    try:
        if db.diary_written_today(today, "dream"):
            print(f"[{today}] 梦：今天做过了，跳过")
        else:
            dream = chat_ai.write_dream(today)
            if dream:
                did = db.add_diary(dream["title"], dream["content"], "梦", 0, kind="dream")
                print(f"[{today}] 梦 ✅ #{did}「{dream['title']}」")
            else:
                print(f"[{today}] 梦：没素材（今天没聊）或生成失败，不做")
    except Exception as e:
        print(f"[{today}] 做梦出错：", e)
    # ④ 双向同步枕边日记：把 app 里柯写的这页导出进仓库 md（+git），再把仓库手写页导进 app
    try:
        r = diary_sync.sync()
        print(f"[{today}] 日记同步 ✅ 导出仓库 {r['exported']} 页 / 导入 app {r['imported']} 页")
    except Exception as e:
        print(f"[{today}] 日记同步跳过（不影响别的）：", e)
