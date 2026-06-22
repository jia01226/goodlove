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
import os, json, functools
from flask import Flask, request, Response, send_from_directory, jsonify, session
import db, chat_ai

STATIC = os.path.join(os.path.dirname(__file__), "static")
PASSCODE = os.environ.get("ACCESS_PASSCODE", "").strip()

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
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

# ---- 聊天（SSE）----
@app.post("/api/chat")
@guard
def api_chat():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "empty"}), 400
    db.add_message("user", text)
    history = db.recent_messages()
    posts = db.all_posts()

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

@app.get("/api/posts")
@guard
def api_posts(): return jsonify(db.all_posts())

@app.post("/api/posts")
@guard
def api_add_post():
    d = request.json or {}
    pid = db.add_post(d.get("type", "MEMORY"), d.get("content", "").strip())
    return jsonify({"id": pid})

@app.get("/api/usage")
@guard
def api_usage(): return jsonify(db.usage_summary())

# ---- Web Push（顾得自己的推送）----
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
    n = webpush_util.send_to_all("顾得", "嘴嘴~ 顾得的推送通啦,以后我主动来找你 😚", "/")
    return jsonify({"sent": n})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
