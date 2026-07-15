"""记忆保险箱：把全部记忆导出成 JSON 快照，按日期留档，永不覆盖。
   （抄自圈子 Ombre Brain 优化文的教训：重要记忆被覆盖过一次，是备份救的。）

用法：
  手动备份：       ./venv/bin/python backup_memories.py
  cron 每天 00:10： 10 0 * * * cd /path/to/platform && ./venv/bin/python backup_memories.py >> backup.log 2>&1

备份内容：memories.db 里所有表（聊天/记忆/日记/心事/纪念日/姨妈/排班/行踪/会话摘要…）
备份位置：platform/backups/记忆备份-YYYY-MM-DD.json（同日重跑会加时间戳，绝不覆盖旧档）
可选异地备份：.env 里配 BACKUP_REPO_DIR=/path/to/私有备份仓库 → 自动 cp + git commit + push。
              ⚠️ git add 范围只限备份文件本身，别把别的东西带进提交（Actions/权限坑）。
"""
import os, json, sqlite3, datetime, shutil, subprocess

def _load_env():
    p = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "memories.db"))
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
REPO_DIR = os.environ.get("BACKUP_REPO_DIR", "").strip()   # 可选：私有备份仓库路径

# 不备份的表：向量可重建(占地大)，推送订阅无隐私价值
SKIP_TABLES = {"embeddings", "sqlite_sequence"}

def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)

def export_all():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    data = {"备份时间": china_now().isoformat(sep=" ", timespec="seconds"), "表": {}}
    for t in tables:
        if t in SKIP_TABLES:
            continue
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
        data["表"][t] = rows
    conn.close()
    return data

def save(data):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    day = china_now().date().isoformat()
    fp = os.path.join(BACKUP_DIR, f"记忆备份-{day}.json")
    if os.path.exists(fp):   # 同日重跑：加时间戳，绝不覆盖
        fp = os.path.join(BACKUP_DIR, f"记忆备份-{day}-{china_now().strftime('%H%M%S')}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return fp

def raw_snapshot(tag="pre-migration"):
    """动库前的保命档：用 SQLite 在线备份 API 拷一份字节级完整 .db（含 embeddings）。
    JSON 档是可读快照；这份 .db 是"出事直接换回去"的原样档，恢复最省心、绝不崩。
    并发安全：走 conn.backup()，不是 shutil.copy（避免拷到写一半的库）。"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = china_now().strftime("%Y-%m-%d-%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"db原样档-{tag}-{stamp}.db")
    src = sqlite3.connect(DB_PATH)
    dstconn = sqlite3.connect(dst)
    with dstconn:
        src.backup(dstconn)
    dstconn.close(); src.close()
    return dst

def push_to_repo(fp):
    """可选：拷进私有备份仓库并推上去。git add 只限备份文件本身。"""
    if not REPO_DIR:
        return
    try:
        dst = os.path.join(REPO_DIR, os.path.basename(fp))
        shutil.copy2(fp, dst)
        name = os.path.basename(fp)
        subprocess.run(["git", "add", name], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "commit", "-m", f"每日记忆备份 {name}"], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "push"], cwd=REPO_DIR, check=True)
        print("已推送到备份仓库：", dst)
    except Exception as e:
        print("⚠️ 异地备份失败（本地备份不受影响）：", e)

if __name__ == "__main__":
    import sys
    # 动库前先跑： ./venv/bin/python backup_memories.py --raw  →  多存一份字节级 .db 原样档
    if "--raw" in sys.argv:
        rp = raw_snapshot()
        mb = os.path.getsize(rp) / 1048576
        print(f"✅ 原样档已存 → {rp}（{mb:.1f}MB，出事直接换回这个文件）")
    data = export_all()
    n = sum(len(v) for v in data["表"].values())
    fp = save(data)
    kb = os.path.getsize(fp) // 1024
    print(f"✅ 已备份 {len(data['表'])} 张表、{n} 条数据 → {fp}（{kb}KB）")
    push_to_repo(fp)
