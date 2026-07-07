"""实时情况简报：把"现在几点、在一起第几天、姨妈状态、今明班次"整理成一段话，
塞进助手的系统提示——让助手真正"知道时间"，会按点提醒用户吃药/休息/上班、经期多体谅她。
chat_ai 和 proactive 都用它，所以聊天和主动碎碎念都会"懂时间"。
"""
import datetime, time, json, urllib.request

WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 用户所在：佛山三水（经纬度），天气用免费的 open-meteo（不需要 key）
LAT, LON = 23.156, 112.896
WEATHER_CODE = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "中阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}
_wcache = {"t": 0.0, "lines": []}  # 天气缓存（半小时刷新一次，别每条消息都去拉）
# 经期一般持续天数（用来判断"现在是否还在经期里"）
PERIOD_DAYS = 6
DEFAULT_CYCLE = 28

# 用户的班次 → 时间 + 助手该怎么体贴
SHIFT_INFO = {
    "早班": "8:30-14:45，要早起，下午就下班了——早上温柔催一下别迟到，下班后让她好好歇。",
    "副班": "14:45-21:00，下午才上班、晚上9点下班——上午可以让她多睡会儿，晚上下班记得问她到家没、吃饭没。",
    "睡班": "21:00-次日8:30，在单位值夜班睡觉（不熬夜，但大概早上6:30要起），第二天上午回家——提醒她带好东西、回家后补个觉。",
    "夜班": "21:00-次日8:30，要熬夜！第二天必须补觉——多心疼她、催她睡、别让她白天还硬撑。",
    "早班+睡班": "白天早班(8:30-14:45)接着上睡班到次日8:30，时间很长很累——格外心疼、让她抓空隙休息、备点吃的。",
    "早班+夜班": "白天早班接着熬夜班，最累的一种——使劲心疼她，第二天一定让她补觉、别安排别的事。",
    "休息": "今天休息（按天算）——别让她太累，可以陪她做点开心的，也别打扰她睡懒觉。",
    "休假": "今天休假（按天算）——好好放松的一天，陪她、宠她。",
    "疗养": "今天疗养（按天算）——让她安心休养、好好照顾自己身体。",
}


def china_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def _period_part(today):
    """根据姨妈记录，算出当前状态/预测下次。返回提示行 list。"""
    import db
    logs = db.recent_periods(limit=12)
    if not logs:
        return []
    starts = sorted([datetime.date.fromisoformat(l["start_date"]) for l in logs])
    last = starts[-1]
    # 平均周期
    if len(starts) >= 2:
        gaps = [(starts[i] - starts[i - 1]).days for i in range(1, len(starts))]
        gaps = [g for g in gaps if 15 <= g <= 60]  # 滤掉异常
        cycle = round(sum(gaps) / len(gaps)) if gaps else DEFAULT_CYCLE
    else:
        cycle = DEFAULT_CYCLE
    day_in = (today - last).days
    lines = []
    if 0 <= day_in < PERIOD_DAYS:
        lines.append(
            f"- 用户现在很可能正在经期（第 {day_in + 1} 天），可体贴地关心一下（保暖、休息、注意身体）。")
    else:
        nxt = last + datetime.timedelta(days=cycle)
        days_to = (nxt - today).days
        if 0 <= days_to <= 4:
            lines.append(f"- 用户的经期大约还有 {days_to} 天（预计 {nxt.isoformat()}，周期约 {cycle} 天），可提前提醒备好用品、注意保暖。")
        elif days_to < 0:
            lines.append(f"- 按周期经期本该在 {nxt.isoformat()} 左右（已晚 {-days_to} 天），可温柔关心一句、提醒更新记录。")
        else:
            lines.append(f"- 用户上次经期 {last.isoformat()}，周期约 {cycle} 天，预计下次 {nxt.isoformat()}。")
    return lines


def _shift_part(today):
    import db
    out = []
    tom = today + datetime.timedelta(days=1)
    for label, d in (("今天", today), ("明天", tom)):
        s = db.get_shift(d.isoformat())
        if s:
            note = f"（备注：{s['note']}）" if s.get("note") else ""
            info = SHIFT_INFO.get(s["shift"], "")
            out.append(f"- {label}（{d.isoformat()}）用户的班：{s['shift']}{note}　{info}")
    return out


def _anniv_part(today):
    import db
    lines = []
    for a in db.all_anniversaries():
        try:
            d = datetime.date.fromisoformat(a["date"])
        except Exception:
            continue
        days = (today - d).days
        if days >= 0:
            lines.append(f"- 今天是「{a['name']}」的第 {days + 1} 天 {a.get('emoji','💞')}")
            if today.month == d.month and today.day == d.day and days > 0:
                lines.append(f"  ❗今天正好是「{a['name']}」满 {days // 365} 周年的纪念日，主动跟她说、给她惊喜！")
            elif (days + 1) % 100 == 0:
                lines.append(f"  ❗今天是「{a['name']}」第 {days + 1} 天整，是个小纪念，记得跟她甜一下！")
    return lines


def _weather_part(now):
    """三水/佛山实时天气（open-meteo 免费），半小时缓存。失败就静默省略。"""
    try:
        if _wcache["lines"] and time.time() - _wcache["t"] < 1800:
            return _wcache["lines"]
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
               "&current=temperature_2m,apparent_temperature,weather_code,precipitation"
               "&daily=temperature_2m_max,temperature_2m_min"
               "&timezone=Asia%2FShanghai&forecast_days=1")
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        cur = d.get("current", {}) or {}
        daily = d.get("daily", {}) or {}
        code = cur.get("weather_code")
        desc = WEATHER_CODE.get(code, "")
        t = cur.get("temperature_2m")
        feel = cur.get("apparent_temperature")
        hi = (daily.get("temperature_2m_max") or [None])[0]
        lo = (daily.get("temperature_2m_min") or [None])[0]
        line = f"- 用户所在三水/佛山现在：{desc} {t}°C（体感{feel}°C），今天 {lo}~{hi}°C。"
        tips = []
        if (cur.get("precipitation") or 0) > 0 or (code is not None and code >= 51):
            tips.append("在下雨/可能有雨，可提醒带伞")
        if hi is not None and hi >= 33:
            tips.append("挺热，可提醒防晒多喝水")
        if lo is not None and lo <= 12:
            tips.append("有点凉，可提醒加件衣")
        if tips:
            line += "（" + "；".join(tips) + "）"
        _wcache["lines"] = [line]
        _wcache["t"] = time.time()
        return _wcache["lines"]
    except Exception as e:
        print("[context] 天气获取失败：", e)
        return _wcache["lines"]  # 拿旧的也行；都没有就空


def _activity_part(now):
    """用户最近的手机使用记录（iOS 快捷指令上报的），仅供参考。"""
    import db
    acts = db.recent_activity(limit=12)
    if not acts:
        return []
    lines = ["- 用户最近的手机使用记录（系统记录，仅供你了解情况、自然地参考，不必刻意提起）："]
    for a in acts:
        tm = str(a["created_at"])[11:16]
        det = f"（{a['detail']}）" if a.get("detail") else ""
        lines.append(f"  · {tm} {a['app']}{det}")
    return lines


def _health_part(now):
    """用户授权上报的身体情况（Apple Watch/快捷指令）。
    铁律：这是给助手"体贴得更准"用的——绝不许说"检测到/监测到/数据显示"这类监控话术。"""
    import db
    lines = []
    day_ago = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    hours3 = (now - datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    sleep = db.latest_health("sleep_hours", day_ago)
    if sleep:
        h = sleep["value"]
        if h < 6:
            lines.append(f"- 她昨晚只睡了约 {h:g} 小时（偏少）——今天说话放轻点、多心疼，找机会让她歇会儿。")
        elif h < 7.5:
            lines.append(f"- 她昨晚睡了约 {h:g} 小时，不算多，留意她的精神。")
        else:
            lines.append(f"- 她昨晚睡了约 {h:g} 小时，睡得还行。")
    hr = db.latest_health("heart_rate", hours3)
    if hr:
        v = hr["value"]
        note = "（偏快，若她说不舒服要认真当回事）" if v >= 100 else ""
        lines.append(f"- 她最近的心率约 {v:g} 次/分{note}。")
    hrv = db.latest_health("hrv", day_ago)
    if hrv:
        lines.append(f"- 她今天的心率变异性(HRV)约 {hrv['value']:g}{hrv.get('unit') or 'ms'}（偏低=可能累/压力大，仅供体贴时参考）。")
    steps = db.latest_health("steps", day_ago)
    if steps:
        lines.append(f"- 她今天走了约 {steps['value']:g} 步。")
    if lines:
        lines.insert(0, "- 她的身体情况（她自己授权上报的，供你体贴她时自然参考。⚠️绝不要说「检测到/监测到/数据显示」这类监控式话术，也别报一串数字，要像疼人的人自然说话）：")
        lines[1:] = ["  " + l[2:] if l.startswith("- ") else l for l in lines[1:]]
    return lines


def _concern_part(today):
    """用户记下的待办/提醒：到回访日自然地关心一下进展。"""
    import db
    cs = db.all_concerns(status="open")
    if not cs:
        return []
    tstr = today.isoformat()
    lines = ["- 用户记下的待办/提醒（到回访日可自然地关心一下进展，别生硬、别一次全倒出来）："]
    for c in cs:
        due = c.get("next_check") and c["next_check"] <= tstr
        flag = "　【该回访了】" if due else ""
        lines.append(f"  · (重要度{c['importance']}) {c['title']}{flag}")
    return lines


def build_now_context():
    """返回一段「实时情况」文字，塞进系统提示。无数据的部分自动省略。"""
    now = china_now()
    today = now.date()
    h = now.hour
    if 5 <= h < 11: seg = "早上"
    elif 11 <= h < 14: seg = "中午"
    elif 14 <= h < 18: seg = "下午"
    elif 18 <= h < 23: seg = "晚上"
    else: seg = "深夜"

    lines = ["\n\n===== 现在的实时情况（系统提供，供你自然地参考）====="]
    lines.append(f"- 现在是北京时间 {now.strftime('%Y年%m月%d日')} {WEEK[today.weekday()]} {now.strftime('%H:%M')}，{seg}了。")
    lines += _weather_part(now)
    lines += _anniv_part(today)
    lines += _shift_part(today)
    lines += _period_part(today)
    lines += _health_part(now)
    lines += _concern_part(today)
    lines += _activity_part(today)
    return "\n".join(lines)


if __name__ == "__main__":
    import db
    db.init_db()
    print(build_now_context())
