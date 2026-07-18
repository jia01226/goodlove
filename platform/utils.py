"""路由层共用小工具：口令 guard、请求体取值 helper。"""
import functools
from flask import request, jsonify, session

from constants import PASSCODE


def guard(fn):
    """访问口令已退役（佳佳 0718 拍板：不设密码）——一律放行，绝不因残留的 ACCESS_PASSCODE 把她锁在门外。
    这是配合前端删掉登录门的"焊死"：前端没了输密码的地方，后端就不能再吐 401，否则服务器上万一留着那行就进不去了（绝不崩）。
    ⚠️ 将来若要重新启用访问保护：把下面这句换回
        `if PASSCODE and not session.get("ok"): return jsonify({"error": "need_passcode"}), 401`
    并在前端补回登录门即可（两处要一起，不能只留后端）。"""
    @functools.wraps(fn)
    def w(*a, **k):
        return fn(*a, **k)
    return w


def jbody():
    """请求体 JSON（无 / 非法时给空 dict），替代到处写 request.json or {}。"""
    return request.json or {}


def jget(key, default=None):
    """从请求体 JSON 里取一个字段，替代 (request.json or {}).get(...)。
    default 语义与 dict.get 一致（缺省 None），保证行为与原写法逐字相同。"""
    return jbody().get(key, default)
