"""上传/文件管理：上传、静态服务 uploads、/photos 页与清理接口。"""
import os
import uuid
import logging
from flask import Blueprint, jsonify, request, send_from_directory

import db
from constants import (STATIC_DIR, UPLOAD_DIR, IMG_EXT, TEXT_EXT, DOC_EXT,
                       UPLOAD_EXT, UPLOAD_EXT_MAXLEN)
from utils import guard, jget

logger = logging.getLogger(__name__)
bp = Blueprint("media", __name__)


@bp.post("/api/upload")
@guard
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "no file"}), 400
    ext = os.path.splitext(f.filename)[1].lower()[:UPLOAD_EXT_MAXLEN]
    if ext not in UPLOAD_EXT:
        return jsonify({"error": "暂不支持这种文件格式"}), 415
    original_name = os.path.basename(
        (request.form.get("original_name") or f.filename).replace("\\", "/")
    )[:255]
    name = uuid.uuid4().hex + ext
    f.save(os.path.join(UPLOAD_DIR, name))
    return jsonify({
        "url": "/uploads/" + name,
        "is_image": ext in IMG_EXT,
        "can_read": ext in (TEXT_EXT | DOC_EXT),
        "kind": "image" if ext in IMG_EXT else "document",
        "name": original_name,
    })


@bp.get("/uploads/<path:p>")
@guard
def serve_upload(p):
    return send_from_directory(UPLOAD_DIR, p)


# ---- 图片/文件管理（清废图，留纪念图）----
@bp.get("/photos")
def photos_page(): return send_from_directory(STATIC_DIR, "photos.html")


@bp.get("/api/uploads/list")
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


@bp.post("/api/uploads/delete")
@guard
def api_uploads_delete():
    names = jget("names") or []
    n = sum(1 for x in names if _safe_remove(x))
    return jsonify({"deleted": n})


@bp.post("/api/uploads/clean_unused")
@guard
def api_uploads_clean_unused():
    """一键清"聊天里没用到的"（废图/截图）。用过的（=有回忆的）绝不动。"""
    used = db.referenced_images()
    n = 0
    for name in os.listdir(UPLOAD_DIR):
        if name not in used and os.path.isfile(os.path.join(UPLOAD_DIR, name)):
            os.remove(os.path.join(UPLOAD_DIR, name)); n += 1
    return jsonify({"deleted": n})
