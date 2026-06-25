"""Web Push（助手自己的推送）：VAPID 密钥 + 发送通知。
首次运行自动生成 VAPID 密钥文件（vapid_private.pem）。
"""
import os, json, base64
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization
from pywebpush import webpush, WebPushException
import db

VAPID_FILE = os.path.join(os.path.dirname(__file__), "vapid_private.pem")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "mailto:gude@jiagude.love")

def _vapid():
    if not os.path.exists(VAPID_FILE):
        v = Vapid01()
        v.generate_keys()
        v.save_key(VAPID_FILE)
    return Vapid01.from_file(VAPID_FILE)

def application_server_key():
    """给浏览器订阅用的公钥（base64url 的未压缩点）。"""
    v = _vapid()
    raw = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

def send_to_all(title, body, url="/"):
    """给所有已订阅的设备推送。返回成功条数。"""
    payload = json.dumps({"title": title, "body": body, "url": url})
    n = 0
    for sid, sub in db.all_push_subscriptions():
        try:
            webpush(subscription_info=json.loads(sub),
                    data=payload,
                    vapid_private_key=VAPID_FILE,
                    vapid_claims={"sub": VAPID_EMAIL})
            n += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):     # 订阅失效，清掉
                db.delete_push_subscription(sid)
        except Exception:
            pass
    return n
