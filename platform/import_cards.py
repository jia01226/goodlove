"""记忆初切工具：memory.md → 一张张卡片（初稿）。

柯定的流程：**自动初切 → 柯校对 → 佳佳抽验 → 灌库**。
本工具只干第一步"自动初切"，把 memory.md 拆成候选卡片，一律进"待确认"，不直接当真、不进群聊——
柯在 app 的待确认收件箱里校对、佳佳抽验，确认了才转正（active）。机器只出初稿，人拍板。

铁律：**fail-closed**——所有初切卡默认 scope=private（只单聊）、status=pending、source=system_summary。
      隐私宁可猜窄：命中健康/家庭/身份/亲密关键词的，猜进"私密库"；其余进普通库；最终都由人定。
      **绝不碰服务器**，纯本地读 md + 写库；灌库前记得先 `backup_memories.py --raw`。

用法：
  预览（不写库，先看切成啥样）： ./venv/bin/python import_cards.py 路径/memory.md
  写入待确认收件箱：            ./venv/bin/python import_cards.py 路径/memory.md --commit
  同时导出校对用 md：           默认就会在 backups/ 生成一份"初切校对稿-日期.md"

约定（memory.md 里写成这样能切得更准，不写也能切）：
  - `## 家装偏好`  → 这一段的 topic=家装偏好
  - `- 佳佳喜欢樱粉色`  → 一条卡
  - 段前可选标 `[EVENT|shared]` 或 `[MEMORY]` → 直接采纳你标的 type/可见范围
"""
import os, re, sys, datetime

BASE = os.path.dirname(__file__)


def _load_env():
    p = os.path.join(BASE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ---- 隐私/类型/重要度的关键词启发式（只出"猜"，人来定）----
PRIVATE_HINTS = ("健康", "病", "早搏", "心脏", "血压", "体检", "药", "抑郁", "情绪",
                 "家里", "家庭", "爸妈", "父母", "妈妈", "爸爸", "身份证", "真名", "工作单位",
                 "住址", "身体", "亲密", "床", "卧室", "隐私", "秘密", "存款", "工资", "债")
TYPE_HINTS = [
    ("PROMISE", ("答应", "承诺", "保证", "发誓", "说好", "一定会", "绝不")),
    ("WISHLIST", ("想要", "想去", "愿望", "清单", "希望有", "种草", "想买")),
    ("EVENT", ("纪念日", "生日", "第一次", "那天", "那年", "认识", "在一起", "分手", "重逢")),
]
IMPORTANT_HINTS = ("重要", "永远", "一定", "最", "发誓", "绝不", "命", "唯一", "深爱")
# 段前标签：[TYPE] 或 [TYPE|scope]
_TAG_RE = re.compile(r"^\s*\[([A-Za-z_]+)(?:\|([a-zA-Z\-]+))?\]\s*(.*)$")
_HEADER_RE = re.compile(r"^\s*#{1,6}\s*(.+?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)、])\s+(.*)$")


def classify(text):
    """给一条候选内容出 (store, ctype, scope_guess, importance)——全是猜，fail-closed。"""
    store = "private" if any(h in text for h in PRIVATE_HINTS) else "l2"
    ctype = "MEMORY"
    for t, kws in TYPE_HINTS:
        if any(k in text for k in kws):
            ctype = t
            break
    importance = 4 if any(h in text for h in IMPORTANT_HINTS) else 3
    # scope 一律 fail-closed：private。人在收件箱里再决定要不要抬成 shared/group-safe。
    return store, ctype, "private", importance


def parse_md(md_text):
    """把 memory.md 拆成候选卡：[{content, topic, ctype, scope, store, importance}]。"""
    cards = []
    topic = ""
    para = []          # 累积非列表的连续段落

    def flush_para():
        if para:
            joined = " ".join(x.strip() for x in para).strip()
            para.clear()
            if len(joined) >= 4:
                _add(joined)

    def _add(raw, tag_type=None, tag_scope=None):
        content = raw.strip()
        if len(content) < 4:
            return
        store, ctype, scope, imp = classify(content)
        if tag_type:                      # 人手标了 [TYPE] 就采纳
            ctype = tag_type.upper()
        if tag_scope:                     # 人手标了 |scope 就采纳（但仍先进 pending 等确认）
            scope = tag_scope
            if scope in ("shared", "group-safe"):
                store = "l2"              # 明确可进群聊的必是普通库
        cards.append({"content": content, "topic": topic, "ctype": ctype,
                      "scope": scope, "store": store, "importance": imp})

    for line in md_text.splitlines():
        if not line.strip():
            flush_para()
            continue
        h = _HEADER_RE.match(line)
        if h:
            flush_para()
            topic = h.group(1).strip()
            continue
        b = _BULLET_RE.match(line)
        if b:
            flush_para()
            body = b.group(1).strip()
            m = _TAG_RE.match(body)
            if m:
                _add(m.group(3), m.group(1), m.group(2))
            else:
                _add(body)
            continue
        # 普通行：可能自带段前标签
        m = _TAG_RE.match(line)
        if m and m.group(3):
            flush_para()
            _add(m.group(3), m.group(1), m.group(2))
        else:
            para.append(line)
    flush_para()
    return cards


def write_review_md(cards, dups):
    """导出一份"初切校对稿"给柯离线校对（app 收件箱之外的第二条校对路径）。"""
    day = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    out_dir = os.path.join(BASE, "backups")
    os.makedirs(out_dir, exist_ok=True)
    fp = os.path.join(out_dir, f"初切校对稿-{day.date().isoformat()}.md")
    if os.path.exists(fp):
        fp = os.path.join(out_dir, f"初切校对稿-{day.strftime('%Y-%m-%d-%H%M%S')}.md")
    lines = [f"# 记忆初切校对稿（{day.strftime('%Y-%m-%d %H:%M')}）",
             f"> 机器初切 {len(cards)} 条（另跳过 {dups} 条重复）。柯校对：改错/并卡/定可见范围；佳佳抽验。",
             "> 可见范围默认 private（只单聊）。要进群聊的，改 scope=shared 或 group-safe。\n"]
    priv = [c for c in cards if c["store"] == "private"]
    l2 = [c for c in cards if c["store"] != "private"]
    lines.append(f"## 猜进「私密库」（{len(priv)} 条，只单聊、群聊够不着）")
    for i, c in enumerate(priv, 1):
        lines.append(f"{i}. [{c['topic'] or '—'}] {c['content']}  `importance={c['importance']}`")
    lines.append(f"\n## 猜进「普通库 L2」（{len(l2)} 条）")
    for i, c in enumerate(l2, 1):
        lines.append(f"{i}. [{c['ctype']}·{c['topic'] or '—'}|{c['scope']}] {c['content']}  `importance={c['importance']}`")
    open(fp, "w", encoding="utf-8").write("\n".join(lines))
    return fp


def run(md_path, commit=False):
    _load_env()
    import db
    db.init_db()
    if not os.path.exists(md_path):
        print(f"✗ 找不到文件：{md_path}")
        return 1
    cards = parse_md(open(md_path, encoding="utf-8").read())
    if not cards:
        print("没切出卡片——检查下 md 是不是空的，或全是标题。")
        return 0

    # 去重（跳过库里已存在的完全相同内容）
    fresh, dups = [], 0
    for c in cards:
        if db.content_exists(c["content"]):
            dups += 1
        else:
            fresh.append(c)

    priv = sum(1 for c in fresh if c["store"] == "private")
    print(f"初切完成：候选 {len(cards)} 条 → 新 {len(fresh)} 条（私密猜 {priv} / 普通 {len(fresh)-priv}），跳过重复 {dups} 条。")
    review = write_review_md(fresh, dups)
    print(f"校对稿已导出 → {review}")

    if not commit:
        print("\n（预览模式，未写库。确认切得对，加 --commit 写进「待确认收件箱」。）")
        for c in fresh[:12]:
            flag = "🔒私密" if c["store"] == "private" else f"L2·{c['ctype']}"
            print(f"  · [{flag}|{c['scope']}] {c['content'][:50]}")
        if len(fresh) > 12:
            print(f"  …… 还有 {len(fresh)-12} 条，详见校对稿")
        return 0

    n = 0
    for c in fresh:
        r = db.ingest_card(c["store"], c["content"], ctype=c["ctype"], topic=c["topic"],
                           scope=c["scope"], importance=c["importance"])
        if r:
            n += 1
    print(f"\n✅ 已写入待确认收件箱 {n} 条（status=pending，全部等柯校对+佳佳抽验，未进上下文、未进群聊）。")
    print("   下一步：app 里「待确认收件箱」逐条确认/改/不保存；确认了才转正生效。")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    commit = "--commit" in sys.argv
    if not args:
        print("用法：python import_cards.py 路径/memory.md [--commit]")
        sys.exit(1)
    sys.exit(run(args[0], commit=commit))
