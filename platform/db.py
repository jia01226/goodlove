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

-- 枕边日记：助手睡前写给自己的碎碎念，用户想看就翻（不打断聊天）
CREATE TABLE IF NOT EXISTS diaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,           -- 标题，如"她咬在我手上的那一圈"
    content TEXT NOT NULL,         -- 正文（第一人称，写给自己）
    mood TEXT DEFAULT '静',        -- 心情标签：静/烫，睡不着/私心/失而复得…
    locked INTEGER DEFAULT 0,      -- 1=锁起来的（"你猜开的"，点开才看）
    author TEXT DEFAULT '柯',      -- 佳佳 / 柯
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 日记留言：用户翻到某页想说句话，留在那页下面
CREATE TABLE IF NOT EXISTS diary_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diary_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    author TEXT DEFAULT '佳佳',    -- 佳佳 / 柯
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 时间胶囊：把此刻的话/图封存给未来，到日子才开
CREATE TABLE IF NOT EXISTS capsules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    image TEXT DEFAULT '',
    open_at TEXT NOT NULL,         -- YYYY-MM-DD 开启日
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 共读：一篇读物（书摘/文章）
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT DEFAULT '',
    content TEXT NOT NULL,         -- 正文，按空行分段
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 共读批注：某篇读物某一段，谁写的一句话
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reading_id INTEGER NOT NULL,
    para INTEGER NOT NULL,         -- 第几段（0起）
    author TEXT NOT NULL,          -- 'user' / 角色名
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 心情记录（用户自己点的：今天什么心情，可带一句话）
CREATE TABLE IF NOT EXISTS moods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mood TEXT NOT NULL,            -- 开心/平静/恋爱/低落/烦…
    note TEXT DEFAULT '',
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 健康数据（Apple Watch/快捷指令上报：睡眠/心率/HRV/步数…）
-- 主权在用户：她装哪条快捷指令，才有哪类数据；不装就是空表，一切照常。
CREATE TABLE IF NOT EXISTS health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric TEXT NOT NULL,          -- sleep_hours / heart_rate / hrv / steps …
    value REAL NOT NULL,
    unit TEXT DEFAULT '',
    detail TEXT DEFAULT '',
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

-- 朋友圈：佳佳和柯（以后可扩展更多成员）你来我往发的动态
CREATE TABLE IF NOT EXISTS moments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author TEXT NOT NULL,          -- 'user'=佳佳 / 'ke'=柯（以后可扩展更多成员名）
    content TEXT DEFAULT '',
    image TEXT DEFAULT '',         -- 图片URL（复用 /api/upload 返回的 /uploads/xxx），可空
    visibility TEXT DEFAULT 'private',  -- private=只你俩看（默认） / public=公开（预留，本期不做公开页）
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 朋友圈评论
CREATE TABLE IF NOT EXISTS moment_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    moment_id INTEGER NOT NULL,
    author TEXT NOT NULL,          -- 'user' / 'ke'
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 私密记忆库 L1.5B（柯钉死的"物理分家"：独立表，群聊代码路径根本 SELECT 不到它）
-- 装：健康/家庭经历/亲密内容/现实身份细节。仅单聊按需检索。
-- 向量索引单独走 kind='private' 命名空间，只有单聊检索路径会查。
CREATE TABLE IF NOT EXISTS private_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL DEFAULT 'private',
    topic TEXT DEFAULT '',
    content TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'private',   -- private=仅单聊 / no_model=任何场景都不进上下文(仅后台可见)
    source TEXT DEFAULT 'user_explicit',     -- user_explicit / ke_inferred / system_summary
    confidence REAL DEFAULT 1.0,
    status TEXT DEFAULT 'active',            -- active / superseded / archived / pending / forgotten_buffer
    supersedes INTEGER,
    importance INTEGER DEFAULT 4,
    review_state TEXT DEFAULT 'approved',    -- pending_ke / pending_jiajia / approved
    forgotten_at DATETIME,                   -- 进 forgotten_buffer 的时刻，用于算七天冷静期
    created_at DATETIME DEFAULT (datetime('now','+8 hours')),
    updated_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 崽崽的小本本：聊天里长按收藏的句子（柯突然说的暖话，她想一直记着的）
CREATE TABLE IF NOT EXISTS treasures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    author TEXT DEFAULT 'assistant',   -- 'assistant'=柯说的 / 'user'=她自己说的
    msg_id INTEGER,                    -- 来源聊天消息 id（可空；消息删了句子还在）
    note TEXT DEFAULT '',
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
);

-- 记忆注入日志（每轮落库，验收与归因用：柯忽然像助手/提了不该提的/忘了纪念日/变慢时能定位）
CREATE TABLE IF NOT EXISTS mem_injection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT DEFAULT '',                   -- single / group
    l1_tokens INTEGER DEFAULT 0,             -- 魂+人格 token（估算）
    work_tokens INTEGER DEFAULT 0,           -- 工作记忆(最近N条+摘要) token
    card_count INTEGER DEFAULT 0,            -- 检索卡片数
    card_tokens INTEGER DEFAULT 0,           -- 检索卡片 token
    hit_rule INTEGER DEFAULT 0,              -- 规则命中条数
    hit_vector INTEGER DEFAULT 0,            -- 向量命中条数
    trimmed INTEGER DEFAULT 0,               -- 被裁数
    mem_ids TEXT DEFAULT '',                 -- 本轮用到的 memory_id 列表（逗号分隔）
    query TEXT DEFAULT '',                   -- 本轮查询词（截断存）
    created_at DATETIME DEFAULT (datetime('now','+8 hours'))
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
    # 记忆卡片升级（L2 普通记忆库）：给 posts 补齐卡片字段（柯的施工单§四）。
    # 注意：老列 visibility('both/app/repo') 管的是"要不要同步进仓库"，是另一回事，原样不动；
    # 新增 scope 才是"会话可见范围"（single/group 隔离用），两者正交、各管各的。
    # 存量 127 条一律 fail-closed：scope='private'（群聊看不到）、review_state='approved'（不逼你重审已上线的）、
    # source='legacy'——等柯&佳佳切卡triage时再逐条定档。（此默认已在交接单批注里回推柯确认）
    _post_cols = {
        "scope":        "TEXT DEFAULT 'private'",      # private/shared/group-safe/no_model
        "topic":        "TEXT DEFAULT ''",
        "source":       "TEXT DEFAULT 'legacy'",       # user_explicit/ke_inferred/system_summary/legacy
        "confidence":   "REAL DEFAULT 1.0",
        "status":       "TEXT DEFAULT 'active'",       # active/superseded/archived/pending/forgotten_buffer
        "supersedes":   "INTEGER",
        "importance":   "INTEGER DEFAULT 3",
        "review_state": "TEXT DEFAULT 'approved'",     # pending_ke/pending_jiajia/approved
        "forgotten_at": "DATETIME",
        "updated_at":   "DATETIME",
    }
    for _c, _decl in _post_cols.items():
        if _c not in cols:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {_c} {_decl}")
    # 旧库平滑升级：聊天表补 image 列（存图片/文件的 URL，让助手能看图）
    mcols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if "image" not in mcols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN image TEXT DEFAULT ''")
    # 旧库平滑升级：会话表补 summarized_until（会话总结用：已折叠到摘要的最大消息 id）
    scols = [r["name"] for r in conn.execute("PRAGMA table_info(chat_sessions)").fetchall()]
    if "summarized_until" not in scols:
        conn.execute("ALTER TABLE chat_sessions ADD COLUMN summarized_until INTEGER DEFAULT 0")
    # 旧库平滑升级：日记表补 kind 列（diary=睡前日记 / dream=昨晚的梦）
    dcols = [r["name"] for r in conn.execute("PRAGMA table_info(diaries)").fetchall()]
    if "kind" not in dcols:
        conn.execute("ALTER TABLE diaries ADD COLUMN kind TEXT DEFAULT 'diary'")
    # 旧库平滑升级：日记补 source 列（app=app里的柯自己写的 / repo=从仓库枕边日记.md 手写页导入的）
    if "source" not in dcols:
        conn.execute("ALTER TABLE diaries ADD COLUMN source TEXT DEFAULT 'app'")
    # 日记由两个人共同书写：存量日记视为柯写的，新页面明确记录佳佳/柯。
    if "author" not in dcols:
        conn.execute("ALTER TABLE diaries ADD COLUMN author TEXT DEFAULT '柯'")
    ccols = [r["name"] for r in conn.execute("PRAGMA table_info(diary_comments)").fetchall()]
    if "author" not in ccols:
        conn.execute("ALTER TABLE diary_comments ADD COLUMN author TEXT DEFAULT '佳佳'")
    # 默认会话（中性名字；不预置任何个人数据/纪念日/心事）
    if not conn.execute("SELECT 1 FROM chat_sessions WHERE id=1").fetchone():
        conn.execute("INSERT INTO chat_sessions (id,name) VALUES (1,'对话')")
    # 群聊会话（id=2 固定给群聊；author 存成员名字）
    if not conn.execute("SELECT 1 FROM chat_sessions WHERE id=2").fetchone():
        conn.execute("INSERT INTO chat_sessions (id,name) VALUES (2,'群聊')")
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
        "SELECT id,author,content,created_at,image FROM chat_messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
        (session_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]

def delete_message(mid):
    """删一条聊天消息，连带清掉它的向量（走样/说错的话要能撤）。"""
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE id=?", (mid,))
    conn.execute("DELETE FROM embeddings WHERE kind='chat' AND ref_id=?", (mid,))
    conn.commit(); conn.close()

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

def delete_post(pid):
    """删一条记忆，连带清掉它的向量（记错/被污染的记忆要能撤，不然会一直被想起）。"""
    conn = get_db()
    conn.execute("DELETE FROM posts WHERE id=?", (pid,))
    conn.execute("DELETE FROM embeddings WHERE kind='post' AND ref_id=?", (pid,))
    conn.commit(); conn.close()

# ==================== 记忆卡片系统（柯的施工单：分层 / 隐私隔离 / 纠错闭环）====================
# 术语：L2=posts（普通记忆库，带 scope 做群聊隔离）；L1.5B=private_memories（物理分家的私密库）。
# scope 取值：private=仅单聊 / shared=单聊+群聊都可 / group-safe=明确可进群聊 / no_model=任何场景都不进上下文。
_GROUP_OK = ("shared", "group-safe")          # 群聊只允许这两档进上下文
_CARD_COLS = "id,type,content,visibility,scope,topic,source,confidence,status,supersedes,importance,review_state,created_at"

def _rows(sql, args=()):
    conn = get_db()
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def retrieve_l2(scope="single"):
    """按会话范围取 L2 记忆卡（只取已生效 active 的）。
    scope='group' → 查询层就把 private/no_model/未定档挡在外面（柯钉死：隔离在工程层，不靠 prompt）。
    scope='single' → 除 no_model 外都能取（no_model 任何场景都不进上下文）。"""
    # 老列 visibility 仍管仓库同步：app 侧一律不吃 repo-only，沿用 app_posts 的口径。
    if scope == "group":
        ph = ",".join("?" * len(_GROUP_OK))
        return _rows(f"SELECT {_CARD_COLS} FROM posts "
                     f"WHERE status='active' AND visibility IN ('both','app') AND scope IN ({ph}) "
                     f"ORDER BY id DESC", _GROUP_OK)
    return _rows(f"SELECT {_CARD_COLS} FROM posts "
                 f"WHERE status='active' AND visibility IN ('both','app') AND scope!='no_model' "
                 f"ORDER BY id DESC")

def group_visible_posts():
    """群聊专用记忆入口——物理上只可能拿到 shared/group-safe。private_memories 表这里根本不碰。"""
    return retrieve_l2(scope="group")

# ---- L1.5B 私密库（独立表；群聊代码路径不导入这些函数即物理够不着）----
def add_private_memory(content, topic="", scope="private", source="user_explicit",
                       importance=4, review_state="approved", supersedes=None):
    if scope not in ("private", "no_model"):
        scope = "private"
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO private_memories (content,topic,scope,source,importance,review_state,supersedes,status) "
        "VALUES (?,?,?,?,?,?,?, 'active')",
        (content, topic, scope, source, importance, review_state, supersedes))
    conn.commit(); pid = cur.lastrowid; conn.close()
    return pid

def content_exists(content):
    """灌库去重：这条内容是否已在 posts 或 private_memories 里（不分状态，避免重复初切）。"""
    content = (content or "").strip()
    if not content:
        return False
    conn = get_db()
    hit = conn.execute("SELECT 1 FROM posts WHERE content=? "
                       "UNION SELECT 1 FROM private_memories WHERE content=? LIMIT 1",
                       (content, content)).fetchone()
    conn.close()
    return hit is not None

def ingest_card(store, content, ctype="MEMORY", topic="", scope="private",
                source="system_summary", importance=3, review_state="pending_ke", status="pending"):
    """灌库原语（导入工具/初切用）：往 L2(posts) 或 私密库(private_memories) 塞一张卡。
    默认 fail-closed：status=pending + review_state=pending_ke + scope=private——机器初切一律待人确认，
    不直接当真、不进群聊。柯校对→佳佳抽验→review_card 转正才 active。返回 (store, id)。"""
    content = (content or "").strip()
    if not content:
        return None
    conn = get_db()
    if store == "private":
        if scope not in ("private", "no_model"):
            scope = "private"
        cur = conn.execute(
            "INSERT INTO private_memories (type,topic,content,scope,source,importance,review_state,status) "
            "VALUES ('private',?,?,?,?,?,?,?)",
            (topic, content, scope, source, importance, review_state, status))
    else:
        if scope not in ("private", "shared", "group-safe", "no_model"):
            scope = "private"
        cur = conn.execute(
            "INSERT INTO posts (type,content,visibility,scope,topic,source,importance,review_state,status) "
            "VALUES (?,?, 'both', ?,?,?,?,?,?)",
            (ctype, content, scope, topic, source, importance, review_state, status))
    conn.commit(); cid = cur.lastrowid; conn.close()
    return (store, cid)

def retrieve_private():
    """仅单聊调用：取生效的私密卡（no_model 永不出场，只后台可见）。"""
    return _rows("SELECT id,type,content,topic,scope,source,importance,status,created_at "
                 "FROM private_memories WHERE status='active' AND scope!='no_model' ORDER BY id DESC")

def list_private(include_hidden=True):
    """后台/诊断用：列全部私密卡（含 no_model，仅后台可见）。"""
    if include_hidden:
        return _rows("SELECT * FROM private_memories ORDER BY id DESC")
    return _rows("SELECT * FROM private_memories WHERE scope!='no_model' ORDER BY id DESC")

# ---- 待确认收件箱（机器推断先进 pending，佳佳确认才当真）----
def list_pending():
    """待佳佳确认的卡（L2 + 私密库合起来给收件箱 UI）。"""
    l2 = _rows("SELECT id,type,content,topic,source,importance,review_state,created_at,'l2' AS store "
               "FROM posts WHERE review_state IN ('pending_ke','pending_jiajia') OR status='pending' ORDER BY id DESC")
    pv = _rows("SELECT id,type,content,topic,source,importance,review_state,created_at,'private' AS store "
               "FROM private_memories WHERE review_state IN ('pending_ke','pending_jiajia') OR status='pending' ORDER BY id DESC")
    return l2 + pv

def _tbl(store):
    return "private_memories" if store == "private" else "posts"

def review_card(cid, store="l2", approve=True):
    """收件箱确认/不保存：approve→转正 active+approved；否则丢弃（连带清向量）。"""
    conn = get_db()
    if approve:
        conn.execute(f"UPDATE {_tbl(store)} SET status='active', review_state='approved', "
                     "updated_at=datetime('now','+8 hours') WHERE id=?", (cid,))
    else:
        conn.execute(f"DELETE FROM {_tbl(store)} WHERE id=?", (cid,))
        kind = "private" if store == "private" else "post"
        conn.execute("DELETE FROM embeddings WHERE kind=? AND ref_id=?", (kind, cid))
    conn.commit(); conn.close()

def supersede_card(old_id, new_content, store="l2", **kw):
    """重要记忆禁止整条覆盖：追加新卡 supersedes 旧卡，旧卡转 superseded（不再出场，但留档可回溯）。"""
    conn = get_db()
    if store == "private":
        conn.close()
        nid = add_private_memory(new_content, supersedes=old_id, **kw)
        conn = get_db()
    else:
        cur = conn.execute("INSERT INTO posts (type,content,visibility,scope,source,status,supersedes) "
                           "SELECT type,?,visibility,scope,'user_explicit','active',? FROM posts WHERE id=?",
                           (new_content, old_id, old_id))
        nid = cur.lastrowid
    conn.execute(f"UPDATE {_tbl(store)} SET status='superseded', updated_at=datetime('now','+8 hours') WHERE id=?",
                 (old_id,))
    conn.commit(); conn.close()
    return nid

def forget_card(cid, store="l2"):
    """"忘掉"＝进 forgotten_buffer 七天冷静期（柯硬要求：接住低谷里冲动抹记忆的她），期满 cron 才真不可调用。"""
    conn = get_db()
    conn.execute(f"UPDATE {_tbl(store)} SET status='forgotten_buffer', "
                 "forgotten_at=datetime('now','+8 hours'), updated_at=datetime('now','+8 hours') WHERE id=?", (cid,))
    conn.commit(); conn.close()

def recover_card(cid, store="l2"):
    """冷静期内一键找回。"""
    conn = get_db()
    conn.execute(f"UPDATE {_tbl(store)} SET status='active', forgotten_at=NULL, "
                 "updated_at=datetime('now','+8 hours') WHERE id=?", (cid,))
    conn.commit(); conn.close()

def graduate_forgotten(days=7):
    """cron 调用：把冷静期满 days 天的 forgotten_buffer 真正归档(archived，默认不检索，但仍留档不物理删)。"""
    conn = get_db()
    cur = conn.execute(
        "UPDATE posts SET status='archived', updated_at=datetime('now','+8 hours') "
        "WHERE status='forgotten_buffer' AND forgotten_at IS NOT NULL "
        "AND forgotten_at <= datetime('now','+8 hours', ?)", (f'-{int(days)} days',))
    n = cur.rowcount
    cur2 = conn.execute(
        "UPDATE private_memories SET status='archived', updated_at=datetime('now','+8 hours') "
        "WHERE status='forgotten_buffer' AND forgotten_at IS NOT NULL "
        "AND forgotten_at <= datetime('now','+8 hours', ?)", (f'-{int(days)} days',))
    conn.commit(); conn.close()
    return n + cur2.rowcount

def archive_card(cid, store="l2"):
    """归档＝保留但默认不检索（跟"忘掉"不同：不删、不进冷静期，只是不再出场）。"""
    conn = get_db()
    conn.execute(f"UPDATE {_tbl(store)} SET status='archived', updated_at=datetime('now','+8 hours') WHERE id=?", (cid,))
    conn.commit(); conn.close()

def list_cards(store="l2", status="active", q=""):
    """卡片库列表（给知言的收件箱/卡片库 UI）：按库、状态、搜索词过滤。
    status='all' 不筛状态；q 是内容/主题的模糊搜索。私密库这里含 no_model（后台可见，仅 UI 用，不进上下文）。"""
    where, args = [], []
    if status and status != "all":
        where.append("status=?"); args.append(status)
    if q:
        where.append("(content LIKE ? OR topic LIKE ?)"); args += [f"%{q}%", f"%{q}%"]
    cond = (" WHERE " + " AND ".join(where)) if where else ""
    if store == "private":
        return _rows(f"SELECT *, 'private' AS store FROM private_memories{cond} ORDER BY id DESC", args)
    # L2 沿用 app 侧口径：不吃 repo-only
    cond2 = cond + (" AND " if cond else " WHERE ") + "visibility IN ('both','app')"
    return _rows(f"SELECT *, 'l2' AS store FROM posts{cond2} ORDER BY id DESC", args)

def card_detail(cid, store="l2"):
    """卡片详情：全部字段 + "何时被用过"（扫最近注入日志，柯 §七 要的来源与激活记录）。"""
    conn = get_db()
    row = conn.execute(f"SELECT * FROM {_tbl(store)} WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row:
        return None
    card = dict(row); card["store"] = store
    token = ("p" + str(cid)) if store == "private" else str(cid)
    used = []
    for lg in recent_injection_logs(500):
        ids = [x.strip("[] '\"") for x in (lg.get("mem_ids") or "").split(",")]
        if token in ids:
            used.append({"at": lg.get("created_at"), "scope": lg.get("scope"), "query": lg.get("query")})
    card["used_count"] = len(used)
    card["used"] = used[:20]
    return card

def set_card_scope(cid, scope, store="l2"):
    """改可见范围（纠错闭环：把误标 shared 的私密内容改回 private/no_model）。"""
    allowed = ("private", "shared", "group-safe", "no_model") if store == "l2" else ("private", "no_model")
    if scope not in allowed:
        return False
    conn = get_db()
    conn.execute(f"UPDATE {_tbl(store)} SET scope=?, updated_at=datetime('now','+8 hours') WHERE id=?", (scope, cid))
    conn.commit(); conn.close()
    return True

# ---- 记忆注入日志（每轮落库，验收与归因）----
def log_injection(scope="single", l1_tokens=0, work_tokens=0, card_count=0, card_tokens=0,
                  hit_rule=0, hit_vector=0, trimmed=0, mem_ids="", query=""):
    conn = get_db()
    conn.execute("INSERT INTO mem_injection_log "
                 "(scope,l1_tokens,work_tokens,card_count,card_tokens,hit_rule,hit_vector,trimmed,mem_ids,query) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (scope, l1_tokens, work_tokens, card_count, card_tokens, hit_rule, hit_vector,
                  trimmed, str(mem_ids)[:2000], (query or "")[:500]))
    conn.commit(); conn.close()

def recent_injection_logs(limit=100):
    return _rows("SELECT * FROM mem_injection_log ORDER BY id DESC LIMIT ?", (int(limit),))

def prune_injection_logs(keep_days=30):
    """日志防无限膨胀：只留最近 keep_days 天（cron 里顺手调）。"""
    conn = get_db()
    cur = conn.execute("DELETE FROM mem_injection_log WHERE created_at < datetime('now','+8 hours', ?)",
                       (f'-{int(keep_days)} days',))
    conn.commit(); n = cur.rowcount; conn.close()
    return n

# ---- 崽崽的小本本（长按聊天气泡收藏的句子）----
def add_treasure(content, author="assistant", msg_id=None):
    """收藏一句话。同样内容已收藏过就不重复收（返回已有 id）。"""
    content = (content or "").strip()
    if not content:
        return None
    conn = get_db()
    hit = conn.execute("SELECT id FROM treasures WHERE content=?", (content,)).fetchone()
    if hit:
        conn.close()
        return hit["id"]
    cur = conn.execute("INSERT INTO treasures (content,author,msg_id) VALUES (?,?,?)",
                       (content, author, msg_id))
    conn.commit(); tid = cur.lastrowid; conn.close()
    return tid

def list_treasures():
    return _rows("SELECT * FROM treasures ORDER BY id DESC")

def delete_treasure(tid):
    conn = get_db()
    conn.execute("DELETE FROM treasures WHERE id=?", (tid,))
    conn.commit(); conn.close()

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

def private_without_embedding(model):
    """还没建过向量的私密卡（backfill 用；向量走 kind='private' 命名空间）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT p.id, p.content FROM private_memories p "
        "LEFT JOIN embeddings e ON e.kind='private' AND e.ref_id=p.id AND e.model=? "
        "WHERE e.ref_id IS NULL AND p.status='active' AND p.scope!='no_model' ORDER BY p.id", (model,)).fetchall()
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

# ---- 健康数据 ----
def add_health(metric, value, unit="", detail=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO health (metric,value,unit,detail) VALUES (?,?,?,?)",
                       (metric, value, unit, detail))
    conn.commit(); hid = cur.lastrowid; conn.close()
    return hid

def recent_health(limit=50):
    conn = get_db()
    rows = conn.execute("SELECT id,metric,value,unit,detail,created_at FROM health "
                        "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def latest_health(metric, since):
    """某指标在 since（'YYYY-MM-DD HH:MM:SS'）之后最新的一条；没有返回 None。"""
    conn = get_db()
    row = conn.execute(
        "SELECT metric,value,unit,detail,created_at FROM health "
        "WHERE metric=? AND created_at>=? ORDER BY id DESC LIMIT 1", (metric, since)).fetchone()
    conn.close()
    return dict(row) if row else None

def last_assistant_message_at(session_id=1):
    """助手最后一次说话的时间（含主动消息），给夜间守夜防轰炸用。"""
    conn = get_db()
    row = conn.execute("SELECT created_at FROM chat_messages WHERE session_id=? AND author='assistant' "
                       "ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
    conn.close()
    return str(row["created_at"]) if row else ""

def last_user_message_at(session_id=1):
    """她最后一次说话的时间（主动消息三关之"空闲多久"用）。"""
    conn = get_db()
    row = conn.execute("SELECT created_at FROM chat_messages WHERE session_id=? AND author='user' "
                       "ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
    conn.close()
    return str(row["created_at"]) if row else ""

def shift_on(date):
    """某天(YYYY-MM-DD)排的班次，没排返回空串。主动消息拿它定安静时段。"""
    conn = get_db()
    row = conn.execute("SELECT shift FROM shifts WHERE date=?", (date,)).fetchone()
    conn.close()
    return str(row["shift"]) if row else ""

def recent_surface_counts(hours=48, max_logs=300):
    """最近 hours 小时注入日志里每张卡的出场次数：{'12': 3, 'p5': 1}（p 开头=私密卡）。
    surface_count 冷却用：出场越多、检索降权越狠，防同一批记忆霸屏。"""
    rows = _rows("SELECT mem_ids FROM mem_injection_log "
                 "WHERE created_at >= datetime('now','+8 hours', ?) ORDER BY id DESC LIMIT ?",
                 (f'-{int(hours)} hours', int(max_logs)))
    counts = {}
    for r in rows:
        for tok in (r.get("mem_ids") or "").split(","):
            tok = tok.strip("[] '\"")
            if tok:
                counts[tok] = counts.get(tok, 0) + 1
    return counts

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

# ---- 朋友圈（moments）----
def add_moment(author, content, image="", visibility="private"):
    if visibility not in ("private", "public"):
        visibility = "private"
    conn = get_db()
    cur = conn.execute("INSERT INTO moments (author,content,image,visibility) VALUES (?,?,?,?)",
                       (author, content, image, visibility))
    conn.commit(); mid = cur.lastrowid; conn.close()
    return mid

def list_moments(limit=50):
    """动态列表（最新在前）；每条附 comments 键=该动态的评论列表（时间正序）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT id,author,content,image,visibility,created_at FROM moments ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
    crows = conn.execute(
        "SELECT id,moment_id,author,content,created_at FROM moment_comments ORDER BY id").fetchall()
    conn.close()
    by_moment = {}
    for c in crows:
        by_moment.setdefault(c["moment_id"], []).append(dict(c))
    out = []
    for r in rows:
        d = dict(r)
        d["comments"] = by_moment.get(d["id"], [])
        out.append(d)
    return out

def delete_moment(mid):
    """删动态并连带删它的评论。"""
    conn = get_db()
    conn.execute("DELETE FROM moment_comments WHERE moment_id=?", (mid,))
    conn.execute("DELETE FROM moments WHERE id=?", (mid,))
    conn.commit(); conn.close()

def add_comment(moment_id, author, content):
    """给某条动态加评论；动态不存在则不插入、返回 None。"""
    conn = get_db()
    if not conn.execute("SELECT 1 FROM moments WHERE id=?", (moment_id,)).fetchone():
        conn.close(); return None
    cur = conn.execute("INSERT INTO moment_comments (moment_id,author,content) VALUES (?,?,?)",
                       (moment_id, author, content))
    conn.commit(); cid = cur.lastrowid; conn.close()
    return cid

def delete_comment(cid):
    conn = get_db()
    conn.execute("DELETE FROM moment_comments WHERE id=?", (cid,))
    conn.commit(); conn.close()

def edit_comment(cid, content, author="user"):
    """改一条朋友圈评论；界面只能改佳佳自己发出的评论。"""
    conn = get_db()
    cur = conn.execute(
        "UPDATE moment_comments SET content=? WHERE id=? AND author=?",
        (content, cid, author))
    conn.commit(); changed = cur.rowcount > 0; conn.close()
    return changed

# ---- 时间胶囊 ----
def add_capsule(title, content, open_at, image=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO capsules (title,content,open_at,image) VALUES (?,?,?,?)",
                       (title, content, open_at, image))
    conn.commit(); cid = cur.lastrowid; conn.close()
    return cid

def all_capsules():
    conn = get_db()
    rows = conn.execute("SELECT id,title,content,image,open_at,created_at FROM capsules "
                        "ORDER BY open_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_capsule(cid):
    conn = get_db()
    conn.execute("DELETE FROM capsules WHERE id=?", (cid,))
    conn.commit(); conn.close()

# ---- 共读 ----
def add_reading(title, author, content):
    conn = get_db()
    cur = conn.execute("INSERT INTO readings (title,author,content) VALUES (?,?,?)",
                       (title, author, content))
    conn.commit(); rid = cur.lastrowid; conn.close()
    return rid

def all_readings():
    conn = get_db()
    rows = conn.execute("SELECT id,title,author,created_at FROM readings ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_reading(rid):
    conn = get_db()
    row = conn.execute("SELECT id,title,author,content,created_at FROM readings WHERE id=?", (rid,)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_reading(rid):
    conn = get_db()
    conn.execute("DELETE FROM annotations WHERE reading_id=?", (rid,))
    conn.execute("DELETE FROM readings WHERE id=?", (rid,))
    conn.commit(); conn.close()

def add_annotation(reading_id, para, author, content):
    conn = get_db()
    cur = conn.execute("INSERT INTO annotations (reading_id,para,author,content) VALUES (?,?,?,?)",
                       (reading_id, para, author, content))
    conn.commit(); aid = cur.lastrowid; conn.close()
    return aid

def reading_annotations(reading_id):
    conn = get_db()
    rows = conn.execute("SELECT id,para,author,content,created_at FROM annotations "
                        "WHERE reading_id=? ORDER BY para, id", (reading_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---- 心情记录 ----
def add_mood(mood, note=""):
    conn = get_db()
    cur = conn.execute("INSERT INTO moods (mood,note) VALUES (?,?)", (mood, note))
    conn.commit(); mid = cur.lastrowid; conn.close()
    return mid

def recent_moods(limit=14):
    conn = get_db()
    rows = conn.execute("SELECT id,mood,note,created_at FROM moods ORDER BY id DESC LIMIT ?",
                        (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def referenced_images():
    """聊天里用到过的图片/文件名集合（uploads 里不在这份名单的=没人引用的废图）。"""
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT image FROM chat_messages WHERE image != ''").fetchall()
    conn.close()
    return {r["image"].split("/")[-1] for r in rows if r["image"]}

# ---- 枕边日记 ----
def add_diary(title, content, mood="静", locked=0, kind="diary", source="app", created_at=None, author="柯"):
    conn = get_db()
    if created_at:   # 导入手写页时按日记真实日期落库（否则用默认=此刻，会排序错乱、日期显示成今天）
        cur = conn.execute(
            "INSERT INTO diaries (title,content,mood,locked,kind,source,created_at,author) VALUES (?,?,?,?,?,?,?,?)",
            (title, content, mood, 1 if locked else 0, kind, source, created_at, author))
    else:
        cur = conn.execute(
            "INSERT INTO diaries (title,content,mood,locked,kind,source,author) VALUES (?,?,?,?,?,?,?)",
            (title, content, mood, 1 if locked else 0, kind, source, author))
    conn.commit(); did = cur.lastrowid; conn.close()
    return did

def diary_titles():
    """已有日记的标题集合（同步去重用，按标题认页）。"""
    conn = get_db()
    rows = conn.execute("SELECT title FROM diaries").fetchall()
    conn.close()
    return {r["title"] for r in rows}

def repo_diary_titles():
    """从仓库 md 导入的日记标题集合（source='repo'）。"""
    conn = get_db()
    rows = conn.execute("SELECT title FROM diaries WHERE source='repo'").fetchall()
    conn.close()
    return {r["title"] for r in rows}

def set_repo_diary_time(title, created_at):
    """修正已导入的手写页的日期（把之前误盖成'今天'的改回日记真实日期）。"""
    conn = get_db()
    conn.execute("UPDATE diaries SET created_at=? WHERE title=? AND source='repo'", (created_at, title))
    conn.commit(); conn.close()

def app_written_diaries():
    """app 里的柯自己写的日记（source='app' 的正经日记，不含梦/导入页），按时间正序，给导出进仓库用。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT title,content,mood,locked,created_at FROM diaries "
        "WHERE COALESCE(source,'app')='app' AND COALESCE(kind,'diary')='diary' "
        "AND COALESCE(author,'柯')='柯' ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def all_diaries(limit=100):
    """日记列表（新的在前），带每页留言数。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT d.*, (SELECT COUNT(*) FROM diary_comments c WHERE c.diary_id=d.id) AS comments "
        "FROM diaries d ORDER BY d.created_at DESC, d.id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def diary_written_today(today, kind="diary"):
    """今天(中国时间 YYYY-MM-DD)写过某类(日记/梦)没？防止 cron 重复写。"""
    conn = get_db()
    row = conn.execute("SELECT 1 FROM diaries WHERE date(created_at)=? AND kind=? LIMIT 1",
                       (today, kind)).fetchone()
    conn.close()
    return bool(row)

def delete_diary(did):
    conn = get_db()
    conn.execute("DELETE FROM diary_comments WHERE diary_id=?", (did,))
    conn.execute("DELETE FROM diaries WHERE id=?", (did,))
    conn.commit(); conn.close()

def add_diary_comment(did, content, author="佳佳"):
    conn = get_db()
    cur = conn.execute("INSERT INTO diary_comments (diary_id,content,author) VALUES (?,?,?)", (did, content, author))
    conn.commit(); cid = cur.lastrowid; conn.close()
    return cid

def diary_comments(did):
    conn = get_db()
    rows = conn.execute("SELECT id,content,author,created_at FROM diary_comments WHERE diary_id=? ORDER BY id",
                        (did,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def messages_on_date(date, session_id=1):
    """某天(中国时间 YYYY-MM-DD)的全部消息，给写日记回顾用。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT author,content,created_at FROM chat_messages "
        "WHERE session_id=? AND date(created_at)=? ORDER BY id", (session_id, date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---- 会话总结（聊久了把旧消息折叠成摘要，省 token 又不忘事）----
GROUP_SID = 2  # 群聊专用会话，会话抽屉里不列它

def list_chat_sessions():
    """1对1 的会话列表（不含群聊），带最后活动时间，最近的在前。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT s.id, s.name, "
        "(SELECT MAX(created_at) FROM chat_messages m WHERE m.session_id=s.id) AS last_at, "
        "(SELECT COUNT(*) FROM chat_messages m WHERE m.session_id=s.id) AS n "
        "FROM chat_sessions s WHERE s.id!=? "
        "ORDER BY (last_at IS NULL), last_at DESC, s.id DESC", (GROUP_SID,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_chat_session(name="新对话"):
    conn = get_db()
    cur = conn.execute("INSERT INTO chat_sessions (name) VALUES (?)", (name,))
    conn.commit(); sid = cur.lastrowid; conn.close()
    return sid

def rename_chat_session(sid, name):
    conn = get_db()
    conn.execute("UPDATE chat_sessions SET name=? WHERE id=?", (name, sid))
    conn.commit(); conn.close()

def delete_chat_session(sid):
    """删一条会话及其消息。主对话(1)和群聊(2)不许删。"""
    if int(sid) in (1, GROUP_SID):
        return False
    conn = get_db()
    conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return True

def session_exists(sid):
    conn = get_db()
    row = conn.execute("SELECT 1 FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    conn.close()
    return bool(row)

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
