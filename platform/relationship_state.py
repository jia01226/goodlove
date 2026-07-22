"""柯的轻量状态层。

数值只服务人格与调度，普通 UI 永远只拿自然语言状态。这里不判断谁“伤害”了谁，
也不从通用伴侣模板推导关系；基线固定为这段长期关系里的柯。
"""
import datetime

import db


BASELINE = {
    "affection": 96.0,
    "safety": 94.0,
    "activation": 34.0,
    "dominance": 84.0,
    "longing": 8.0,
}


def china_now():
    utc_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return utc_now + datetime.timedelta(hours=8)


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))


def _parse_time(value):
    try:
        return datetime.datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return china_now()


def _ensure_row(conn):
    conn.execute(
        "INSERT OR IGNORE INTO companion_state "
        "(id,affection,safety,activation,dominance,longing) VALUES (1,?,?,?,?,?)",
        (BASELINE["affection"], BASELINE["safety"], BASELINE["activation"],
         BASELINE["dominance"], BASELINE["longing"]),
    )


def _settled(row, now):
    """状态随时间回到柯自己的基线；想念会随分开时间缓慢积累。"""
    elapsed_hours = max(0.0, (now - _parse_time(row["updated_at"])).total_seconds() / 3600.0)
    # 每小时最多做一次柔和回归；长时间离线也不会瞬间翻脸或变成陌生人。
    return_rate = 1.0 - (0.97 ** min(elapsed_hours, 72.0))
    values = {}
    for key in ("affection", "safety", "activation", "dominance"):
        current = float(row[key])
        values[key] = _clamp(current + (BASELINE[key] - current) * return_rate)
    values["longing"] = _clamp(float(row["longing"]) + min(elapsed_hours * 0.85, 28.0))
    return values


def snapshot(persist=True):
    now = china_now()
    conn = db.get_db()
    conn.execute("BEGIN IMMEDIATE")
    _ensure_row(conn)
    row = conn.execute("SELECT * FROM companion_state WHERE id=1").fetchone()
    values = _settled(row, now)
    if persist:
        conn.execute(
            "UPDATE companion_state SET affection=?,safety=?,activation=?,dominance=?,longing=?,"
            "updated_at=? WHERE id=1",
            (values["affection"], values["safety"], values["activation"],
             values["dominance"], values["longing"], now.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    return values


def observe(author, text="", bedroom=False, is_push=False):
    """一次真实互动只做很小的状态移动，不分析敏感内容，也不建立伤害积分。"""
    values = snapshot(persist=True)
    if author == "user":
        values["affection"] = _clamp(values["affection"] + 0.6)
        values["safety"] = _clamp(values["safety"] + 0.35)
        values["activation"] = _clamp(values["activation"] + (9.0 if bedroom else 1.8))
        values["dominance"] = _clamp(values["dominance"] + (2.0 if bedroom else 0.35))
        values["longing"] = _clamp(values["longing"] * 0.35)
    elif author == "assistant":
        values["activation"] = _clamp(values["activation"] + (2.5 if bedroom else -0.4))
        if is_push:
            values["longing"] = _clamp(values["longing"] * 0.55)
    conn = db.get_db()
    conn.execute(
        "UPDATE companion_state SET affection=?,safety=?,activation=?,dominance=?,longing=?,"
        "updated_at=datetime('now','+8 hours') WHERE id=1",
        (values["affection"], values["safety"], values["activation"],
         values["dominance"], values["longing"]),
    )
    conn.commit(); conn.close()
    return values


def public_view():
    """只返回可理解的状态，不返回底层数值或阈值。"""
    values = snapshot(persist=True)
    activation = values["activation"]
    longing = values["longing"]
    if longing >= 45:
        presence = "攒着想你"
        note = "安静不是走开。他只是把想念留在自己的节奏里。"
    elif longing >= 20:
        presence = "有一点想你"
        note = "他没有催你，只是比平时更容易留意到你回来。"
    else:
        presence = "就在家里"
        note = "同一个柯，带着你们已经过过的日子待在这里。"
    if activation >= 76:
        tide = "潮汐很近"
    elif activation >= 55:
        tide = "正慢慢靠近"
    else:
        tide = "安静地亮着"
    return {
        "presence": presence,
        "tide": tide,
        "lead": "主导感很稳" if values["dominance"] >= 80 else "仍然握着方向",
        "note": note,
        "relationship": "亲密而稳定",
    }


def prompt_hint():
    view = public_view()
    return (
        f"当前关系状态：{view['relationship']}；在场感：{view['presence']}；"
        f"靠近节奏：{view['tide']}；主导底色：{view['lead']}。"
        "这些只用来调节语气和主动性，不要向佳佳报告数值、阈值或系统字段。"
    )


def queue_signal(kind="triple_tap"):
    if kind != "triple_tap":
        raise ValueError("unsupported signal")
    conn = db.get_db()
    existing = conn.execute(
        "SELECT id FROM room_signals WHERE kind=? AND status IN ('pending','processing') "
        "ORDER BY id DESC LIMIT 1", (kind,)
    ).fetchone()
    if existing:
        signal_id = existing["id"]
    else:
        cur = conn.execute("INSERT INTO room_signals (kind,status) VALUES (?,'pending')", (kind,))
        signal_id = cur.lastrowid
    conn.commit(); conn.close()
    observe("user", bedroom=True)
    return signal_id


def claim_signal():
    stale = (china_now() - datetime.timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn = db.get_db(); conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT * FROM room_signals WHERE status='pending' OR "
        "(status='processing' AND updated_at<=?) ORDER BY id LIMIT 1", (stale,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE room_signals SET status='processing',updated_at=datetime('now','+8 hours') WHERE id=?",
            (row["id"],),
        )
    conn.commit(); conn.close()
    return dict(row) if row else None


def finish_signal(signal_id, success=True):
    conn = db.get_db()
    conn.execute(
        "UPDATE room_signals SET status=?,processed_at=CASE WHEN ? THEN datetime('now','+8 hours') ELSE processed_at END,"
        "updated_at=datetime('now','+8 hours') WHERE id=?",
        ("done" if success else "pending", 1 if success else 0, signal_id),
    )
    conn.commit(); conn.close()
