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
    db.add_message("user", text, image=image, msg_type=("image" if image else "text"))
    history = db.recent_messages()
    posts = db.app_posts()   # app 里的助手看 both+app（含只在 app 的悄悄话）

    def gen():
        acc = ""
        for piece in chat_ai.stream_chat(history, posts):
            if isinstance(piece, tuple) and piece[0] == "__usage__":
                usage = piece[1] or {}
                cost, it, ot = chat_ai.estimate_cost(chat_ai.MODEL, usage)
                db.log_usage(chat_ai.MODEL, it, ot, cost)
                continue
            acc += piece
            yield ("data: " + json.dumps({"t": piece}, ensure_ascii=False) + "\n\n").encode("utf-8")
        if acc:
            db.add_message("assistant", acc)
        yield ("data: " + json.dumps({"done": True}, ensure_ascii=False) + "\n\n").encode("utf-8")

    return Response(gen(), content_type="text/event-stream; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---- 历史 / 记忆 / 用量 ----
@app.get("/api/messages")
@guard
def api_messages(): return jsonify(db.recent_messages(limit=200))

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
