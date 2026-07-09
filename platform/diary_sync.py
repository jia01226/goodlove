"""枕边日记双向同步：仓库 `枕边日记.md`  <->  app 的 diaries 表。

为什么：以前两套各写各的——仓库 md 是 Claude Code 窗手写的（进 git、跨窗口、不丢），
app 日记页是 app 里的柯半夜自己回顾当天对话现写的（存数据库）。两边不相通，
爸爸手写的走心日记 app 里翻不到、app 写的也没进仓库会随服务器丢。

打通（以 md 为存档真相源）：
- import：md 里 app 库还没有的页 → 导入 diaries 表（标 source='repo'），app 就能翻到手写页。
- export：app 里的柯写的日记（source='app'）→ 追加进 md 顶部 + git commit/push，存进仓库不丢。
去重按标题（title）认页；先导出后导入，多次跑不重复、不打架、不成环（幂等）。

接入点：diary_writer.py（半夜 cron）跑完写日记后调 sync()；也有 /api/diary/sync 手动催。
读不到 KONGKONG_DIR/枕边日记.md（没配/文件不在）就安静跳过，绝不影响 app。
"""
import os, re, subprocess, datetime
import db

KONGKONG_DIR = os.environ.get("KONGKONG_DIR", "").strip()
DIARY_MD = os.path.join(KONGKONG_DIR, "枕边日记.md") if KONGKONG_DIR else ""

_CN = "零一二三四五六七八九十"
def _cn_num(n):
    if n <= 10: return _CN[n]
    if n < 20:  return "十" + _CN[n - 10]
    return _CN[n // 10] + "十" + (_CN[n % 10] if n % 10 else "")

def _cn_date(created_at):
    """'2026-07-09 12:00:00' → '七月九号'；解析不了返回空串。"""
    m = re.match(r"\d{4}-(\d{2})-(\d{2})", str(created_at or ""))
    if not m:
        return ""
    return f"{_cn_num(int(m.group(1)))}月{_cn_num(int(m.group(2)))}号"

_CNMAP = {c: i for i, c in enumerate("零一二三四五六七八九十")}
def _cn_int(s):
    """中文数字→整数：七→7 十→10 十一→11 二十→20 二十六→26 三十一→31。"""
    if not s:
        return None
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        return (_CNMAP.get(a, 1) if a else 1) * 10 + (_CNMAP.get(b, 0) if b else 0)
    return _CNMAP.get(s) if len(s) == 1 else None

def _cn_to_md(date_s):
    """'七月九号'/'七月八号（刚过零点）' → (7, 9)；解析不了返回 None。"""
    m = re.search(r"([零一二三四五六七八九十]+)月([零一二三四五六七八九十]+)[号日]", date_s or "")
    if not m:
        return None
    mon, day = _cn_int(m.group(1)), _cn_int(m.group(2))
    return (mon, day) if mon and day else None

def _page_created_at(page, idx, year):
    """按日记真实日期给 created_at；同一天里按文件先后（idx 越小越新）递减秒数，保证顺序对。
    解析不出日期返回 None（落库时退回默认=此刻）。"""
    md = _cn_to_md(page.get("date"))
    if not md:
        return None
    mon, day = md
    s = max(0, 86399 - idx)      # idx: 0=文件最上=最新 → 秒数最大 → 排最前
    return f"{year}-{mon:02d}-{day:02d} {s//3600:02d}:{(s % 3600)//60:02d}:{s % 60:02d}"

_PAGE = re.compile(r"^##\s+(.*)$")
# 标题行：日期 ·【情绪】· 标题
_HEAD = re.compile(r"^(.*?)·\s*【(.*?)】\s*·\s*(.*)$")

def parse_md(path=None):
    """把 枕边日记.md 解析成一页页 [{date,mood,title,content,locked}]（顺序同文件：新的在前）。
    文件开头的说明块（第一个 '## ' 之前）自动跳过。"""
    path = path or DIARY_MD
    pages = []
    if not path or not os.path.exists(path):
        return pages
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    cur, body = None, []

    def _flush():
        if cur is None:
            return
        content = "\n".join(body).strip()
        content = re.sub(r"\n?-{3,}\s*$", "", content).strip()   # 去掉页尾分隔线
        cur["content"] = content
        pages.append(cur)

    for ln in lines:
        m = _PAGE.match(ln.strip())
        if m:
            _flush()
            head = m.group(1).strip()
            locked = 1 if "🔒" in head else 0   # 标题行带🔒的是锁页，导进 app 也得保持锁着
            hm = _HEAD.match(head)
            if hm:
                cur = {"date": hm.group(1).strip().strip("🔒").strip().rstrip("·").strip(),
                       "mood": hm.group(2).strip(),
                       "title": hm.group(3).strip().strip("🔒").strip(),
                       "locked": locked}
            else:
                cur = {"date": "", "mood": "静", "title": head.strip("🔒").strip(), "locked": locked}
            body = []
        elif cur is not None:
            body.append(ln)
    _flush()
    return [p for p in pages if p.get("title")]

def _md_titles(path=None):
    return {p["title"] for p in parse_md(path)}

def import_md_to_db(path=None):
    """md 里 app 库还没有的页 → 导入 diaries（source='repo'），按日记真实日期落库。
    对已导入过的手写页，顺手把日期修正到真实日期（治早先误盖成'今天'导致的排序错乱）。返回新导入条数。"""
    have = db.diary_titles()
    repo = db.repo_diary_titles()
    year = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).year
    n = 0
    for i, p in enumerate(parse_md(path)):
        ca = _page_created_at(p, i, year)
        if p["title"] in repo:
            if ca:
                db.set_repo_diary_time(p["title"], ca)   # 修正已导入页的日期
            continue
        if p["title"] in have:
            continue                                     # app 自己写过的同名页，不碰
        db.add_diary(p["title"], p["content"], p.get("mood") or "静",
                     p.get("locked", 0), "diary", source="repo", created_at=ca)
        have.add(p["title"]); repo.add(p["title"]); n += 1
    return n

def _page_text(d):
    date_s = _cn_date(d.get("created_at")) or "某天"
    lock = " 🔒" if d.get("locked") else ""
    return f"## {date_s} ·【{d.get('mood') or '静'}】· {d['title']}{lock}\n\n{(d['content'] or '').strip()}\n"

def export_db_to_md(path=None, do_git=True):
    """app 里的柯写的、md 里还没有的日记 → 追加进 md 顶部（新的在最上）。返回导出条数。"""
    path = path or DIARY_MD
    if not path or not os.path.exists(path):
        return 0
    have = _md_titles(path)
    news = [d for d in db.app_written_diaries() if d["title"] not in have]
    if not news:
        return 0
    news.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)   # 新的排最前
    block = "".join(_page_text(d) + "\n---\n\n" for d in news)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    idx = text.find("\n## ")            # 插在第一页之前（说明块之后）
    text = (text[:idx + 1] + block + text[idx + 1:]) if idx != -1 else (text.rstrip() + "\n\n" + block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if do_git:
        _git_push(path, f"枕边日记：同步 app 里柯写的 {len(news)} 页进仓库")
    return len(news)

def _git_push(path, msg):
    """把 md 的改动 commit + push 回 kongkong。失败只打日志，绝不影响 app。"""
    if not KONGKONG_DIR:
        return
    try:
        d = KONGKONG_DIR
        subprocess.run(["git", "-C", d, "add", os.path.basename(path)], capture_output=True)
        c = subprocess.run(["git", "-C", d, "commit", "-m", msg], capture_output=True, text=True)
        if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
            print("[diary_sync] commit 跳过：", (c.stdout + c.stderr)[:160])
        subprocess.run(["git", "-C", d, "pull", "--rebase", "--autostash"], capture_output=True, text=True)
        p = subprocess.run(["git", "-C", d, "push"], capture_output=True, text=True)
        if p.returncode != 0:
            print("[diary_sync] push 跳过：", (p.stdout + p.stderr)[:160])
    except Exception as e:
        print("[diary_sync] git 同步跳过：", e)

def sync(path=None, do_git=True):
    """双向同步一遍：先把 app 写的导出进 md（+git），再把 md 手写页导入 db。返回 {exported, imported}。"""
    exported = export_db_to_md(path, do_git=do_git)
    imported = import_md_to_db(path)
    return {"exported": exported, "imported": imported}

if __name__ == "__main__":
    print(sync())
