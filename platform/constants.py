"""全站常量：魔法字符串/数字集中在这里，routes/ 与 app.py 共用。
注意：db.GROUP_SID 的定义仍在 db.py（会话表的保留 id），这里只放路由层自己的常量。
"""
import os

# ---- 路径 ----
BASE_DIR = os.path.dirname(__file__)
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---- 访问口令（可选；为空则不设防）----
PASSCODE = os.environ.get("ACCESS_PASSCODE", "").strip()

# ---- 上传 ----
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp"}
TEXT_EXT = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".log",
    ".html", ".htm", ".xml", ".yaml", ".yml", ".ini", ".cfg", ".py",
    ".js", ".ts", ".css", ".sql",
}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".pptx"}
UPLOAD_EXT = IMG_EXT | TEXT_EXT | DOC_EXT
MAX_UPLOAD_BYTES = 30 * 1024 * 1024   # 单次上传上限 30MB
UPLOAD_EXT_MAXLEN = 10                # 上传文件扩展名最长保留 10 字符
MODEL_FILE_TEXT_MAX = 18000           # 单个文件最多送给模型的可读字符，避免撑爆上下文

# ---- 聊天流（chat_ai.stream_chat / group_chat.stream_reply 的带外信号）----
USAGE_TAG = "__usage__"
THINK_TAG = "__think__"
ERROR_TAG = "__error__"

# ---- 单条聊天附件 ----
MAX_CHAT_ATTACHMENTS = 9

# ---- 会话 ----
MAIN_SESSION = 1        # 主对话（1对1 默认会话）
GROUP_SESSION = 2       # 群聊专用会话（与 db.GROUP_SID 同值，定义不动 db 里的）
SESSION_NAME_MAXLEN = 30  # 会话名字数上限
DEFAULT_SESSION_NAME = "新对话"

# ---- SSE 响应 ----
SSE_CONTENT_TYPE = "text/event-stream; charset=utf-8"
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
