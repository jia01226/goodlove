"""爱意平台 · 核心后端（Flask）
路由：
  GET  /                 首页
  GET  /chat            聊天页
  POST /api/chat        流式对话（SSE），自动存消息、记用量
  GET  /api/messages    历史消息
  GET  /api/posts       记忆库列表
  POST /api/posts       新增一条记忆
  GET  /api/usage       用量/花费汇总
密钥只在服务器端，浏览器永远看不到。
"""
import os, json, functools, uuid
from datetime import timedelta
from flask import Flask, request, Response, send_from_directory, jsonify, session
import db, chat_ai

STATIC = os.path.join(os.path.dirname(__file__), "static")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
PASSCODE = os.environ.get("ACCESS_PASSCODE", "").strip()
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
# 登录记住一年：用户输一次口令，以后就不用再输了（门照样锁着，陌生人进不来）
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024   # 单次上传上限 30MB
db.init_db()

# ---- 可选访问口令 ----
def guard(fn):
    @functools.wraps(fn)
    def w(*a, **k):
        if PASSCODE and not session.get("ok"):
            return jsonify({"error": "need_passcode"}), 401
        return fn(*a, **k)
    return w

@app.post("/api/login")
def login():
    session.permanent = True   # 让登录长期记住，不再每次都问
    if not PASSCODE:
        session["ok"] = True; return jsonify({"ok": True})
    if (request.json or {}).get("passcode") == PASSCODE:
        session["ok"] = True; return jsonify({"ok": True})
    return jsonify({"ok": False}), 401

# ---- 页面 ----
@app.get("/")
def home(): return send_from_directory(STATIC, "index.html")

@app.get("/chat")
def chat_page(): return send_from_directory(STATIC, "chat.html")

@app.get("/static/<path:p>")
def static_files(p): return send_from_directory(STATIC, p)

@app.get("/sw.js")
def sw_js():
    # service worker 必须从根目录提供，作用域才能覆盖整个站点
    return send_from_directory(STATIC, "sw.js", mimetype="application/javascript")

# ---- 聊天（SSE）----
@app.post("/api/chat")
@guard
def api_chat():
    data = request.json or {}
    text = (data.get("text") or "").strip()
    image = (data.get("image") or "").strip()
    if not text and not image:
        return jsonify({"error": "empty"}), 400
    sid = _chat_sid(data.get("session_id"))
    bedroom = bool(data.get("bedroom"))                # 卧室模式（bedroom.py 只在服务器本地）
    model = chat_ai.resolve_model(data.get("model"))   # 前端可选模型，白名单外回落默认
    db.add_message("user", text, session_id=sid, image=image, msg_type=("image" if image else "text"))
    history = db.recent_messages(session_id=sid)
    posts = db.app_posts()   # app 里的助手看 both+app（含只在 app 的悄悄话）

    def gen():
        acc = ""
        for piece in chat_ai.stream_chat(history, posts, model=model, bedroom=bedroom):
            if isinstance(piece, tuple):
                if piece[0] == "__usage__":
                    usage = piece[1] or {}
                    cost, it, ot = chat_ai.estimate_cost(model, usage)
                    db.log_usage(model, it, ot, cost)
                elif piece[0] == "__think__":
                    yield ("data: " + json.dumps({"think": piece[1]}, ensure_ascii=False) + "\n\n").encode("utf-8")
                continue
            acc += piece
            yield ("data: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n").encode("utf-8")
        if acc:
            db.add_message("assistant", acc, session_id=sid)
        yield ("data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type="text/event-stream; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/models")
@guard
def api_models():
    """给前端模型选择器（知言的 UI 调这个）：可选模型（白名单）+ 当前默认。"""
    return jsonify({"models": chat_ai.MODEL_WHITELIST, "default": chat_ai.MODEL})

# ---- 历史 / 记忆 / 用量 ----
def _chat_sid(raw):
    """把前端传来的会话 id 收敛成合法的 1对1 会话 id：非法/群聊/不存在都退回主对话 1。"""
    try:
        sid = int(raw)
    except (TypeError, ValueError):
        return 1
    if sid == db.GROUP_SID or not db.session_exists(sid):
        return 1
    return sid

@app.get("/api/messages")
@guard
def api_messages():
    sid = _chat_sid(request.args.get("session_id"))
    return jsonify(db.recent_messages(session_id=sid, limit=200))

@app.post("/api/messages/delete")
@guard
def api_delete_message():
    mid = (request.json or {}).get("id")
    if not mid:
        return jsonify({"error": "need id"}), 400
    db.delete_message(mid)
    return jsonify({"ok": True})

# ---- 会话抽屉（多条 1对1 对话）----
@app.get("/api/sessions")
@guard
def api_sessions(): return jsonify(db.list_chat_sessions())

@app.post("/api/sessions")
@guard
def api_session_new():
    name = ((request.json or {}).get("name") or "新对话").strip()[:30] or "新对话"
    return jsonify({"id": db.create_chat_session(name), "name": name})

@app.post("/api/sessions/rename")
@guard
def api_session_rename():
    d = request.json or {}
    name = (d.get("name") or "").strip()[:30]
    if not d.get("id") or not name:
        return jsonify({"error": "need id+name"}), 400
    db.rename_chat_session(d["id"], name)
    return jsonify({"ok": True})

@app.post("/api/sessions/delete")
@guard
def api_session_delete():
    ok = db.delete_chat_session((request.json or {}).get("id"))
    return jsonify({"ok": ok})

# ---- 上传照片/文件（拍照、相册、文件都走这里）----
@app.post("/api/upload")
@guard
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    ext = os.path.splitext(f.filename)[1].lower()[:10]
    name = uuid.uuid4().hex + ext
    f.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({"url": "/uploads/" + name, "is_image": ext in IMG_EXT, "name": f.filename})

@app.get("/uploads/<path:p>")
@guard
def serve_upload(p):
    return send_from_directory(UPLOAD_DIR, p)

@app.get("/api/posts")
@guard
def api_posts(): return jsonify(db.all_posts())

@app.post("/api/posts")
@guard
def api_add_post():
    d = request.json or {}
    content = d.get("content", "").strip()
    pid = db.add_post(d.get("type", "MEMORY"), content, d.get("visibility", "both"))
    # 新记忆顺手建一条向量（失败不影响保存）
    try:
        import vector_search
        vector_search.index_post(pid, content)
    except Exception as e:
        print("索引新记忆失败：", e)
    return jsonify({"id": pid})

@app.post("/api/posts/delete")
@guard
def api_delete_post():
    pid = (request.json or {}).get("id")
    if not pid:
        return jsonify({"error": "need id"}), 400
    db.delete_post(pid)
    return jsonify({"ok": True})

@app.get("/api/vector/status")
@guard
def api_vector_status():
    import vector_search
    return jsonify({
        "backend": vector_search.EMBED_BACKEND,
        "model": vector_search.EMBED_MODEL,
        "available": vector_search.available(),
        "indexed": db.embedding_count(vector_search.EMBED_MODEL),
        "posts": len(db.all_posts()),
    })

@app.post("/api/vector/backfill")
@guard
def api_vector_backfill():
    import vector_search
    n = vector_search.backfill()
    return jsonify({"indexed_new": n})

@app.get("/api/usage")
@guard
def api_usage(): return jsonify(db.usage_summary())

# ---- 手机行踪（iOS 快捷指令上报；助手"抓包"用）----
# 快捷指令不方便带登录态，所以用 token 校验（.env 里 TRACK_TOKEN，缺省用访问口令）。
@app.route("/api/track", methods=["POST", "GET"])
def api_track():
    d = request.get_json(silent=True) or request.form or {}
    app_name = (d.get("app") or request.args.get("app") or "").strip()
    detail = (d.get("detail") or request.args.get("detail") or "").strip()
    token = (d.get("token") or request.args.get("token") or "").strip()
    need = os.environ.get("TRACK_TOKEN", "").strip() or PASSCODE
    if need and token != need:
        return jsonify({"error": "bad token"}), 403
    if not app_name:
        return jsonify({"error": "need app"}), 400
    db.add_activity(app_name, detail)
    return jsonify({"ok": True})

@app.get("/api/activity")
@guard
def api_activity(): return jsonify(db.recent_activity(limit=50))

# ---- 健康数据（Apple Watch/快捷指令上报；主权在用户：装哪条指令才有哪类数据）----
@app.route("/api/health", methods=["POST", "GET"])
def api_health_report():
    d = request.get_json(silent=True) or request.form or {}
    metric = (d.get("metric") or request.args.get("metric") or "").strip()
    value = d.get("value") or request.args.get("value")
    token = (d.get("token") or request.args.get("token") or "").strip()
    need = os.environ.get("TRACK_TOKEN", "").strip() or PASSCODE
    if need and token != need:
        return jsonify({"error": "bad token"}), 403
    if not metric or value is None:
        # GET 且没带参数时当查看用（需登录态）
        if request.method == "GET" and not metric:
            if PASSCODE and not session.get("ok"):
                return jsonify({"error": "need_passcode"}), 401
            return jsonify(db.recent_health(limit=50))
        return jsonify({"error": "need metric+value"}), 400
    try:
        value = float(value)
    except Exception:
        return jsonify({"error": "value must be number"}), 400
    hid = db.add_health(metric, value,
                        (d.get("unit") or request.args.get("unit") or "").strip(),
                        (d.get("detail") or request.args.get("detail") or "").strip())
    return jsonify({"ok": True, "id": hid})

# ---- 纪念日 / 姨妈 / 排班（日常）----
@app.get("/api/anniversaries")
@guard
def api_anniv():
    import datetime
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date()
    out = []
    for a in db.all_anniversaries():
        try:
            days = (today - datetime.date.fromisoformat(a["date"])).days + 1
        except Exception:
            days = None
        out.append({**a, "days": days})
    return jsonify(out)

@app.post("/api/anniversaries")
@guard
def api_anniv_add():
    d = request.json or {}
    name = (d.get("name") or "").strip()
    date = (d.get("date") or "").strip()
    if not name or not date:
        return jsonify({"error": "need name+date"}), 400
    return jsonify({"id": db.add_anniversary(name, date, d.get("emoji", "💞"))})

@app.post("/api/anniversaries/delete")
@guard
def api_anniv_del():
    db.delete_anniversary((request.json or {}).get("id"))
    return jsonify({"ok": True})

@app.get("/api/periods")
@guard
def api_periods(): return jsonify(db.recent_periods())

@app.post("/api/periods")
@guard
def api_period_add():
    d = request.json or {}
    date = (d.get("start_date") or "").strip()
    if not date:
        return jsonify({"error": "need start_date"}), 400
    return jsonify({"id": db.add_period(date, d.get("note", ""))})

@app.post("/api/periods/delete")
@guard
def api_period_del():
    db.delete_period((request.json or {}).get("id"))
    return jsonify({"ok": True})

@app.get("/api/shifts")
@guard
def api_shifts():
    return jsonify(db.all_shifts())

@app.post("/api/shifts")
@guard
def api_shift_set():
    d = request.json or {}
    date = (d.get("date") or "").strip()
    shift = (d.get("shift") or "").strip()
    if not date or not shift:
        return jsonify({"error": "need date+shift"}), 400
    db.set_shift(date, shift, d.get("note", ""))
    return jsonify({"ok": True})

@app.post("/api/shifts/delete")
@guard
def api_shift_del():
    db.delete_shift((request.json or {}).get("date"))
    return jsonify({"ok": True})

# ---- 时间胶囊 ----
@app.get("/capsule")
def capsule_page(): return send_from_directory(STATIC, "capsule.html")

@app.get("/api/capsules")
@guard
def api_capsules():
    import datetime
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).date().isoformat()
    out = []
    for c in db.all_capsules():
        opened = c["open_at"] <= today
        out.append({**c, "opened": opened,
                    # 没到开启日：藏正文和图，只留标题和倒计时
                    "content": c["content"] if opened else "",
                    "image": c["image"] if opened else "",
                    "days_left": (datetime.date.fromisoformat(c["open_at"]) - datetime.date.fromisoformat(today)).days})
    return jsonify(out)

@app.post("/api/capsules")
@guard
def api_capsule_add():
    d = request.json or {}
    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    open_at = (d.get("open_at") or "").strip()
    if not title or not content or not open_at:
        return jsonify({"error": "need title+content+open_at"}), 400
    return jsonify({"id": db.add_capsule(title, content, open_at, (d.get("image") or "").strip())})

@app.post("/api/capsules/delete")
@guard
def api_capsule_del():
    db.delete_capsule((request.json or {}).get("id"))
    return jsonify({"ok": True})

# ---- 共读 ----
@app.get("/reading")
def reading_page(): return send_from_directory(STATIC, "reading.html")

@app.get("/api/readings")
@guard
def api_readings(): return jsonify(db.all_readings())

@app.post("/api/readings")
@guard
def api_reading_add():
    d = request.json or {}
    title = (d.get("title") or "").strip()
    content = (d.get("content") or "").strip()
    if not title or not content:
        return jsonify({"error": "need title+content"}), 400
    return jsonify({"id": db.add_reading(title, (d.get("author") or "").strip(), content)})

@app.get("/api/reading")
@guard
def api_reading_one():
    r = db.get_reading(request.args.get("id"))
    if not r:
        return jsonify({"error": "not found"}), 404
    r["paras"] = [p for p in r["content"].split("\n") if p.strip()]
    r["annotations"] = db.reading_annotations(r["id"])
    return jsonify(r)

@app.post("/api/readings/delete")
@guard
def api_reading_del():
    db.delete_reading((request.json or {}).get("id"))
    return jsonify({"ok": True})

@app.post("/api/reading/annotate")
@guard
def api_reading_annotate():
    """我写批注(author=user)，或请角色写(ai=1)。"""
    d = request.json or {}
    rid = d.get("id"); para = d.get("para")
    if rid is None or para is None:
        return jsonify({"error": "need id+para"}), 400
    if d.get("ai"):
        r = db.get_reading(rid)
        paras = [p for p in (r["content"].split("\n") if r else []) if p.strip()]
        if not r or para >= len(paras):
            return jsonify({"error": "bad para"}), 400
        who = os.environ.get("CHARACTER", "").strip() or "TA"
        text = chat_ai.annotate_passage(r["title"], r["author"], paras[para])
        if not text:
            return jsonify({"error": "生成失败，再试一次"}), 200
        aid = db.add_annotation(rid, para, who, text)
        return jsonify({"id": aid, "author": who, "content": text})
    content = (d.get("content") or "").strip()
    if not content:
        return jsonify({"error": "empty"}), 400
    aid = db.add_annotation(rid, para, "user", content)
    return jsonify({"id": aid, "author": "user", "content": content})

# ---- 心情记录 ----
@app.get("/api/moods")
@guard
def api_moods(): return jsonify(db.recent_moods())

@app.post("/api/moods")
@guard
def api_mood_add():
    d = request.json or {}
    mood = (d.get("mood") or "").strip()
    if not mood:
        return jsonify({"error": "need mood"}), 400
    return jsonify({"id": db.add_mood(mood, (d.get("note") or "").strip())})

# ---- 心事引擎 ----
@app.get("/api/concerns")
@guard
def api_concerns(): return jsonify(db.all_concerns())

@app.post("/api/concerns")
@guard
def api_concern_add():
    d = request.json or {}
    title = (d.get("title") or "").strip()
    if not title:
        return jsonify({"error": "need title"}), 400
    try:
        imp = max(1, min(5, int(d.get("importance", 3))))
    except Exception:
        imp = 3
    cid = db.add_concern(title, (d.get("detail") or "").strip(), imp, (d.get("next_check") or "").strip())
    return jsonify({"id": cid})

@app.post("/api/concerns/status")
@guard
def api_concern_status():
    d = request.json or {}
    db.set_concern_status(d.get("id"), "resolved" if d.get("resolved") else "open")
    return jsonify({"ok": True})

@app.post("/api/concerns/delete")
@guard
def api_concern_del():
    db.delete_concern((request.json or {}).get("id"))
    return jsonify({"ok": True})

# ---- 群聊（高级吗喽科技公司：佳佳 + 柯/小克/知言）----
GROUP_SESSION = 2

@app.get("/group")
def group_page(): return send_from_directory(STATIC, "group.html")

@app.get("/api/group/members")
@guard
def api_group_members():
    import group_chat
    cfg = group_chat.load_config()
    return jsonify({"group_name": cfg.get("group_name", "群聊"),
                    "default_speaker": cfg.get("default_speaker", ""),
                    "members": [{"name": m.get("name"), "emoji": m.get("emoji", "🤖"),
                                 "role": m.get("role", "")} for m in cfg.get("members", [])]})

@app.get("/api/group/messages")
@guard
def api_group_messages():
    return jsonify(db.recent_messages(session_id=GROUP_SESSION, limit=200))

@app.post("/api/group/chat")
@guard
def api_group_chat():
    import group_chat
    data = request.json or {}
    text = (data.get("text") or "").strip()
    image = (data.get("image") or "").strip()
    if not text and not image:
        return jsonify({"error": "empty"}), 400
    db.add_message("user", text, session_id=GROUP_SESSION,
                   image=image, msg_type=("image" if image else "text"))
    member = group_chat.pick_speaker(text)
    if not member:
        return jsonify({"error": "no members"}), 500
    history = db.recent_messages(session_id=GROUP_SESSION, limit=40)
    posts = db.app_posts()

    def gen():
        # 先告诉前端这轮谁发言（好显示名字/头像）
        yield ("data: " + json.dumps({"speaker": member["name"],
                                      "emoji": member.get("emoji", "🤖")},
                                     ensure_ascii=False) + "\n\n").encode("utf-8")
        acc = ""
        model_used = (member.get("model") or "").strip() or chat_ai.MODEL
        for piece in group_chat.stream_reply(member, history, posts):
            if isinstance(piece, tuple):
                if piece[0] == "__usage__":
                    usage = piece[1] or {}
                    cost, it, ot = chat_ai.estimate_cost(model_used, usage)
                    db.log_usage(model_used, it, ot, cost)
                elif piece[0] == "__think__":
                    yield ("data: " + json.dumps({"think": piece[1]}, ensure_ascii=False) + "\n\n").encode("utf-8")
                continue
            acc += piece
            yield ("data: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n").encode("utf-8")
        if acc:
            db.add_message(member["name"], acc, session_id=GROUP_SESSION)
        yield ("data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type="text/event-stream; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---- 图片/文件管理（清废图，留纪念图）----
@app.get("/photos")
def photos_page(): return send_from_directory(STATIC, "photos.html")

@app.get("/api/uploads/list")
@guard
def api_uploads_list():
    """uploads 里的全部文件：名字/大小/时间/是否在聊天里用过。新的在前。"""
    used = db.referenced_images()
    out = []
    for name in os.listdir(UPLOAD_DIR):
        fp = os.path.join(UPLOAD_DIR, name)
        if not os.path.isfile(fp):
            continue
        st = os.stat(fp)
        out.append({"name": name, "url": "/uploads/" + name,
                    "size": st.st_size, "mtime": int(st.st_mtime),
                    "is_image": os.path.splitext(name)[1].lower() in IMG_EXT,
                    "used": name in used})
    out.sort(key=lambda x: -x["mtime"])
    return jsonify(out)

def _safe_remove(name):
    """只删 uploads 目录里的普通文件，别的路径一律不碰。"""
    name = os.path.basename(name or "")
    fp = os.path.join(UPLOAD_DIR, name)
    if name and os.path.isfile(fp):
        os.remove(fp); return True
    return False

@app.post("/api/uploads/delete")
@guard
def api_uploads_delete():
    names = (request.json or {}).get("names") or []
    n = sum(1 for x in names if _safe_remove(x))
    return jsonify({"deleted": n})

@app.post("/api/uploads/clean_unused")
@guard
def api_uploads_clean_unused():
    """一键清"聊天里没用到的"（废图/截图）。用过的（=有回忆的）绝不动。"""
    used = db.referenced_images()
    n = 0
    for name in os.listdir(UPLOAD_DIR):
        if name not in used and os.path.isfile(os.path.join(UPLOAD_DIR, name)):
            os.remove(os.path.join(UPLOAD_DIR, name)); n += 1
    return jsonify({"deleted": n})

# ---- 枕边日记（助手写给自己的，用户想看就翻）----
@app.get("/diary")
def diary_page(): return send_from_directory(STATIC, "diary.html")

@app.get("/api/diary")
@guard
def api_diary(): return jsonify(db.all_diaries())

@app.get("/api/diary/comments")
@guard
def api_diary_comments():
    did = request.args.get("id")
    return jsonify(db.diary_comments(did))

@app.post("/api/diary/comment")
@guard
def api_diary_comment():
    d = request.json or {}
    content = (d.get("content") or "").strip()
    if not d.get("id") or not content:
        return jsonify({"error": "need id+content"}), 400
    return jsonify({"id": db.add_diary_comment(d["id"], content)})

@app.post("/api/diary/write")
@guard
def api_diary_write():
    """手动催一篇今天的日记（平时由 cron 半夜自动写）。"""
    entry = chat_ai.write_diary()
    if not entry:
        return jsonify({"ok": False, "reason": "今天还没聊过天，没得写"}), 200
    did = db.add_diary(entry["title"], entry["content"], entry["mood"], entry["locked"])
    return jsonify({"ok": True, "id": did, "title": entry["title"]})

@app.post("/api/diary/delete")
@guard
def api_diary_delete():
    db.delete_diary((request.json or {}).get("id"))
    return jsonify({"ok": True})

# ---- Web Push（助手自己的推送）----
@app.get("/api/push/vapid")
def push_vapid():
    import webpush_util
    return jsonify({"key": webpush_util.application_server_key()})

@app.post("/api/push/subscribe")
@guard
def push_subscribe():
    db.add_push_subscription(json.dumps(request.json or {}))
    return jsonify({"ok": True})

@app.post("/api/push/test")
@guard
def push_test():
    import webpush_util
    n = webpush_util.send_to_all(os.environ.get("APP_NAME", "助手"), "推送测试：通啦~", "/")
    return jsonify({"sent": n})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
