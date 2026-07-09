"""按功能拆分的蓝图集合。app.py 只需调用 register_all(app) 完成组装。"""
from . import (pages, chat, memory, media, daily, push, track,
               diary, group, reading, capsule, moments)

ALL_BLUEPRINTS = (
    pages.bp, chat.bp, memory.bp, media.bp, daily.bp, push.bp,
    track.bp, diary.bp, group.bp, reading.bp, capsule.bp, moments.bp,
)


def register_all(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
