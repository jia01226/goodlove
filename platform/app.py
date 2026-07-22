"""爱意平台 · 核心后端（Flask）—— 组装入口
只做三件事：创建 Flask app、初始化数据库、注册 routes/ 里的功能蓝图。
路由实现按功能拆在 routes/ 包里：
  pages    首页/静态/sw.js/登录/用量
  chat     1对1 聊天（SSE）/历史/会话抽屉/模型
  memory   记忆库 posts / 向量索引
  media    上传、uploads 静态与清理、/photos
  daily    纪念日/姨妈/排班/心情/心事
  push     Web Push
  track    行踪/健康上报与活动查询
  diary    枕边日记
  drawer   柯的抽屉（私藏内容无用户读取接口）
  group    群聊
  reading  共读
  capsule  时间胶囊
密钥只在服务器端，浏览器永远看不到。
gunicorn 入口：`gunicorn app:app`（模块级 app 对象，别动）。
"""
import os
import logging
from datetime import timedelta
from flask import Flask, jsonify

import db
from constants import MAX_UPLOAD_BYTES

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
# 登录记住一年：用户输一次口令，以后就不用再输了（门照样锁着，陌生人进不来）
app.permanent_session_lifetime = timedelta(days=365)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({"error": "文件超过 30MB，请压缩后再发"}), 413


db.init_db()

import routes
routes.register_all(app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
