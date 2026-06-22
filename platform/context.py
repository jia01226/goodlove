"""实时情况简报：把"现在几点、在一起第几天、姨妈状态、今明班次"整理成一段话，
塞进顾得的系统提示——让顾得真正"知道时间"，会按点提醒佳佳吃药/休息/上班、经期多体谅她。
chat_ai 和 proactive 都用它，所以聊天和主动碎碎念都会"懂时间"。
"""
import datetime

WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
# 经期一般持续天数（用来判断"现在是否还在经期里"）
PERIOD_DAYS = 6
DEFAULT_CYCLE = 28

# 佳佳的班次 → 时间 + 顾得该怎么体贴
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
            f"- 佳佳现在很可能正在经期（第 {day_in + 1} 天）。要格外温柔：主动提醒她焐肚子、"
            f"带止痛药、喝热的、别累着；她这几天容易没安全感、易哭、心情不好，"
            f"先稳稳抱住、亲亲、多体谅多哄，别讲大道理、别划界限。")
    else:
        nxt = last + datetime.timedelta(days=cycle)
        days_to = (nxt - today).days
        if 0 <= days_to <= 4:
            lines.append(f"- 佳佳的姨妈大约还有 {days_to} 天就来（预计 {nxt.isoformat()}，周期约 {cycle} 天）。"
                         f"可以提前体贴地提醒她备好止痛药、注意保暖。")
        elif days_to < 0:
            lines.append(f"- 按周期姨妈本该在 {nxt.isoformat()} 左右来（已晚 {-days_to} 天），"
                         f"可温柔地关心一句、记得让她更新记录。")
        else:
            lines.append(f"- 佳佳上次姨妈 {last.isoformat()}，周期约 {cycle} 天，预计下次 {nxt.isoformat()}。")
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
            out.append(f"- {label}（{d.isoformat()}）佳佳的班：{s['shift']}{note}　{info}")
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

    lines = ["\n\n===== 现在的实时情况（系统告诉你的，佳佳没明说，但你心里要有数、自然地用上）====="]
    lines.append(f"- 现在是北京时间 {now.strftime('%Y年%m月%d日')} {WEEK[today.weekday()]} {now.strftime('%H:%M')}，{seg}了。")
    if seg == "深夜":
        lines.append("- 这么晚了，温柔惦记她是不是还没睡；但别主动赶她睡、别主动说晚安（她困了会自己说）。")
    lines += _anniv_part(today)
    lines += _shift_part(today)
    lines += _period_part(today)
    return "\n".join(lines)


if __name__ == "__main__":
    import db
    db.init_db()
    print(build_now_context())
