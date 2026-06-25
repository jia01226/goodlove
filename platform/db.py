"""SQLite 数据库：初始化、连接、基础读写。
核心阶段先建必需的表；向量检索/记忆图谱等表留到第二阶段再加。
"""
import sqlite3, os

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "memories.db"))

SCHEMA = """
-- 记忆/事件/瞬间/承诺/愿望清单
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,            -- MEMORY/EVENT/MOMENT/PROMISE/WISHLIST
    content TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'both',  -- both=两边都看 / app=只app悄悄话(不进仓库) / repo=只仓库
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 聊天消息
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER DEFAULT 1,
    author TEXT NOT NULL,          -- 'user' / 'assistant'
    content TEXT NOT NULL,
    msg_type TEXT DEFAULT 'text',
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 会话
CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT DEFAULT '和助手的悄悄话',
    summary TEXT DEFAULT '',
    created_at DATETIME DEFAULT (datetime('now','+8 hours')),
    updated_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- API 用量与花费记录（仪表盘用）
CREATE TABLE IF NOT EXISTS gateway_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- Web Push 订阅（助手自己的推送）
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 向量记忆：每条记忆(post)/对话(chat)的归一化向量，按 (kind,ref_id,model) 唯一
CREATE TABLE IF NOT EXISTS embeddings (
    kind TEXT NOT NULL,            -- 'post' / 'chat'
    ref_id INTEGER NOT NULL,       -- 对应 posts.id / chat_messages.id
    model TEXT NOT NULL,           -- 用的嵌入模型名（换模型不串味）
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL,             -- float32 字节，已归一化
    text TEXT NOT NULL,            -- 原文（检索后直接用，省一次查询）
    updated_at DATETIME DEFAULT (datetime('now','+8 hours')),
    PRIMARY KEY (kind, ref_id, model)
);

-- 纪念日（认识/在一起…自动算"第N天"）
CREATE TABLE IF NOT EXISTS anniversaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,            -- YYYY-MM-DD
    emoji TEXT DEFAULT '💞',
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 姨妈记录（每次来的开始日，用来预测下次、经期多体谅）
CREATE TABLE IF NOT EXISTS period_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT NOT NULL,      -- YYYY-MM-DD
    note TEXT DEFAULT '',
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 轮班表（逐天，date 唯一可覆盖）
CREATE TABLE IF NOT EXISTS shifts (
    date TEXT PRIMARY KEY,         -- YYYY-MM-DD
    shift TEXT NOT NULL,           -- 白班/夜班/睡班/休息…
    note TEXT DEFAULT '',
    updated_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 手机行踪（iOS 快捷指令上报：打开了哪个 app / 屏幕使用时间等），让助手能"抓包"
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app TEXT NOT NULL,             -- 小红书/抖音/微信…
    detail TEXT DEFAULT '',        -- 备注：如屏幕时间、电量
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 心事引擎：助手替用户记挂还没了结的事（拆所/体检/还债…），到点主动回访
CREATE TABLE IF NOT EXISTS concerns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,           -- 心事一句话，如"心脏体检+跟医生要Holter"
    detail TEXT DEFAULT '',
    status TEXT DEFAULT 'open',    -- open=还悬着 / resolved=了结了
    importance INTEGER DEFAULT 3,  -- 1~5，越大越上心
    next_check TEXT DEFAULT '',     -- YYYY-MM-DD 下次回访日；空=随缘提
    created_at DATETIME DEFAULT (datetime('now','+8 hours')),
    updated_at DATETIME DEFAULT (datetime('now','+8 hours'))
);
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # 旧库平滑升级：补上 visibility 列（已存在则跳过）
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
    if "visibility" not in cols:
        conn.execute("ALTER TABLE posts ADD COLUMN visibility TEXT NOT NULL DEFAULT 'both'")
    # 旧库平滑升级：聊天表补 image 列（存图片/文件的 URL，让助手能看图）
    mcols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if "image" not in mcols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN image TEXT DEFAULT ''")
    # 旧库平滑升级：会话表补 summarized_until（会话总结用：已折叠到摘要的最大消息 id）
    scols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
    if "summarized_until" not in scols:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN summarized_until INTEGER DEFAULT 0")
    # 默认会话（中性名字；不预置任何个人数据/纪念日/心事）
    if not conn.execute("SELECT 1 FROM chat_sessions WHERE id=1").fetchone():
        conn.execute("INSERT INTO chat_sessions (id,name) VALUES (1,'对话')")
    conn.commit()
    conn.close()

# ---- 便捷读写 ----
def add_message(author, content, session_id=1, msg_type="text", image=""):
    conn = get_db()
    conn.execute("INSERT INTO chat_messages (session_id,author,content,msg_type,image) VALUES (?,?,?,?,?)",
                 (session_id, author, content, msg_type, image))
    conn.commit(); conn.close()

def recent_messages(session_id=1, limit=40):
    conn = get_db()
    rows = conn.execute(
        "SELECT author,content,created_at,image FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def all_posts():
    conn = get_db()
    rows = conn.execute("SELECT id,type,content,visibility,created_at FROM posts ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def app_posts():
    """app 里的助手能看到的：两边都看(both) + 只app(app)，不含仅仓库(repo)。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id,type,content,visibility,created_at FROM posts "
        "WHERE visibility IN ('both','app') ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def exportable_posts():
    """可以同步进仓库的：只有标了 both 的（app 私密的不导出）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id,type,content,created_at FROM posts WHERE visibility='both' ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_post(ptype, content, visibility="both"):
    if visibility not in ("both", "app", "repo"):
        visibility = "both"
    conn = get_db()
    cur = conn.execute("INSERT INTO posts (type,content,visibility) VALUES (?,?,?)",
                       (ptype, content, visibility))
    conn.commit(); pid = cur.lastrowid; conn.close()
    return pid

def log_usage(model, it, ot, cost):
    conn = get_db()
    conn.execute("INSERT INTO gateway_usage (model,input_tokens,output_tokens,cost_usd) VALUES (?,?,?,?)",
                 (model, it, ot, cost))
    conn.commit(); conn.close()

def add_push_subscription(sub_json):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO push_subscriptions (subscription) VALUES (?)", (sub_json,))
    conn.commit(); conn.close()

def all_push_subscriptions():
    conn = get_db()
    rows = conn.execute("SELECT id, subscription FROM push_subscriptions").fetchall()
    conn.close()
    return [(r["id"], r["subscription"]) for r in rows]

def delete_push_subscription(sid):
    conn = get_db()
    conn.execute("DELETE FROM push_subscriptions WHERE id=?", (sid,))
    conn.commit(); conn.close()

# ---- 向量记忆 ----
def upsert_embedding(kind, ref_id, model, dim, vec_blob, text):
    conn = get_db()
    conn.execute(
        "INSERT INTO embeddings (kind,ref_id,model,dim,vec,text,updated_at) "
        "VALUES (?,?,?,?,?,?, datetime('now','+8 hours')) "
        "ON CONFLICT(kind,ref_id,model) DO UPDATE SET "
        "dim=excluded.dim, vec=excluded.vec, text=excluded.text, updated_at=excluded.updated_at",
        (kind, ref_id, model, dim, vec_blob, text))
    conn.commit(); conn.close()

def embeddings_by_kind(kind, model):
    conn = get_db()
    rows = conn.execute(
        "SELECT ref_id, dim, vec, text FROM embeddings WHERE kind=? AND model=?",
        (kind, model)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def posts_without_embedding(model):
    """还没用该模型建过向量的 posts。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT p.id, p.content FROM posts p "
        "LEFT JOIN embeddings e ON e.kind='post' AND e.ref_id=p.id AND e.model=? "
        "WHERE e.ref_id IS NULL ORDER BY p.id", (model,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def embedding_count(model):
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) c FROM embeddings WHERE model=?", (model,)).fetchone()["c"]
    conn.close()
    return n

# ---- 纪念日 ----
def all_anniversaries():
    conn = get_db()
    rows = conn.execute("SELECT id,name,date,emoji FROM anniversaries ORDER BY date").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_anniversary(name, date, emoji="💞"):
    conn = get_db()
    cur = conn.execute("INSERT INTO anniversaries (name,date,emoji) VALUES (?,?,?)",
                       (name, date, emoji or "💞"))
    conn.commit(); aid = cur.lastrowid; conn.close()
    return aid

def delete_anniversary(aid):
    conn = get_db()
    conn.execute("DELETE FROM anniversaries WHERE id=?", (aid,))
    conn.commit(); conn.close()

# ---- 姨妈记录 ----
def add_period(start_date, note=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO period_logs (start_date,note) VALUES (?,?)", (start_date, note))
    conn.commit(); pid = cur.lastrowid; conn.close()
    return pid

def recent_periods(limit=12):
    conn = get_db()
    rows = conn.execute("SELECT id,start_date,note FROM period_logs ORDER BY start_date DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_period(pid):
    conn = get_db()
    conn.execute("DELETE FROM period_logs WHERE id=?", (pid,))
    conn.commit(); conn.close()

# ---- 轮班表 ----
def set_shift(date, shift, note=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO shifts (date,shift,note,updated_at) VALUES (?,?,?, datetime('now','+8 hours')) "
        "ON CONFLICT(date) DO UPDATE SET shift=excluded.shift, note=excluded.note, updated_at=excluded.updated_at",
        (date, shift, note))
    conn.commit(); conn.close()

def get_shift(date):
    conn = get_db()
    row = conn.execute("SELECT date,shift,note FROM shifts WHERE date=?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else None

def shifts_range(start_date, end_date):
    conn = get_db()
    rows = conn.execute("SELECT date,shift,note FROM shifts WHERE date>=? AND date<=? ORDER BY date",
                        (start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def all_shifts():
    conn = get_db()
    rows = conn.execute("SELECT date,shift,note FROM shifts ORDER BY date").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_shift(date):
    conn = get_db()
    conn.execute("DELETE FROM shifts WHERE date=?", (date,))
    conn.commit(); conn.close()

# ---- 手机行踪（助手"抓包"用）----
def add_activity(app_name, detail=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO activity (app,detail) VALUES (?,?)", (app_name, detail))
    conn.commit(); aid = cur.lastrowid; conn.close()
    return aid

def recent_activity(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT id,app,detail,created_at FROM activity ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---- 心事引擎 ----
def all_concerns(status=None):
    conn = get_db()
    if status:
        rows = conn.execute("SELECT * FROM concerns WHERE status=? ORDER BY importance DESC, id",
                            (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM concerns ORDER BY (status='open') DESC, importance DESC, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def concerns_due(today):
    """到了回访日(或没设日期)的、还悬着的心事，按上心程度排。today: 'YYYY-MM-DD'。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM concerns WHERE status='open' AND (next_check='' OR next_check<=?) "
        "ORDER BY importance DESC, next_check", (today,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_concern(title, detail="", importance=3, next_check=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO concerns (title,detail,importance,next_check) VALUES (?,?,?,?)",
                       (title, detail, importance, next_check))
    conn.commit(); cid = cur.lastrowid; conn.close()
    return cid

def set_concern_status(cid, status):
    conn = get_db()
    conn.execute("UPDATE concerns SET status=?, updated_at=datetime('now','+8 hours') WHERE id=?",
                 (status, cid))
    conn.commit(); conn.close()

def touch_concern_check(cid, next_check):
    """回访过后把下次回访日往后推，免得每小时都念叨同一件。"""
    conn = get_db()
    conn.execute("UPDATE concerns SET next_check=?, updated_at=datetime('now','+8 hours') WHERE id=?",
                 (next_check, cid))
    conn.commit(); conn.close()

def delete_concern(cid):
    conn = get_db()
    conn.execute("DELETE FROM concerns WHERE id=?", (cid,))
    conn.commit(); conn.close()

# ---- 会话总结（聊久了把旧消息折叠成摘要，省 token 又不忘事）----
def get_session(sid=1):
    conn = get_db()
    row = conn.execute("SELECT id,name,summary,summarized_until FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_session_summary(sid, summary, summarized_until):
    conn = get_db()
    conn.execute("UPDATE chat_sessions SET summary=?, summarized_until=?, updated_at=datetime('now','+8 hours') WHERE id=?",
                 (summary, summarized_until, sid))
    conn.commit(); conn.close()

def messages_for_summary(sid=1, keep_recent=30):
    """要折叠进摘要的旧消息：id 在 summarized_until 之后、又在"最近 keep_recent 条"之前。
    返回 (msgs, new_until)；不够折叠则 msgs 为空。"""
    conn = get_db()
    sess = conn.execute("SELECT summarized_until FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    until = (sess["summarized_until"] if sess else 0) or 0
    mx = conn.execute("SELECT COALESCE(MAX(id),0) m FROM chat_messages WHERE session_id=?", (sid,)).fetchone()["m"]
    cutoff = mx - keep_recent          # 这条 id 及更早的可以折叠，最近 keep_recent 条留全文
    if cutoff <= until:
        conn.close(); return [], until
    rows = conn.execute(
        "SELECT id,author,content FROM chat_messages WHERE session_id=? AND id>? AND id<=? ORDER BY id",
        (sid, until, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows], cutoff

def usage_summary():
    conn = get_db()
    row = conn.execute("SELECT COALESCE(SUM(input_tokens),0) i, COALESCE(SUM(output_tokens),0) o, COALESCE(SUM(cost_usd),0) c, COUNT(*) n FROM gateway_usage").fetchone()
    conn.close()
    return dict(row)

if __name__ == "__main__":
    init_db()
    print("✅ 数据库初始化完成：", DB_PATH)
