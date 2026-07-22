"""按功能拆分的蓝图集合。app.py 只需调用 register_all(app) 完成组装。"""
# 群聊退役（柯回批⑧，待部署）：协作已全面走 GitHub，app 群聊无真实用途，app 收敛为纯二人空间。
# 做法＝不注册 group 蓝图 → /group 与 /api/group/* 自动 404 下线。
# 家规「关门不烧屋」：group.py / group_chat.py / group.html 代码留档不删；群聊历史数据(session_id=2)不物理删除；
# 私密分家与群聊隔离代码(group_visible_posts / retrieve_l2 scope='group')保留不拆——将来门再开，堤坝还在。
from . import (pages, chat, memory, media, daily, push, track,
               diary, drawer, group, reading, capsule, moments, room)  # group 仍 import（模块留档），只是下面不注册

ALL_BLUEPRINTS = (
    pages.bp, chat.bp, memory.bp, media.bp, daily.bp, push.bp,
    track.bp, diary.bp, drawer.bp, reading.bp, capsule.bp, moments.bp, room.bp,   # group.bp 已下线（退役）
)

# 柯的服务器本地私有模块（如 protocol＝每日功课）：文件只住服务器、永不入库（见 .gitignore）。
# 仓库只留这个挂载点——文件在就自动挂，不在就跳过，绝不崩。0718 收编：从前柯手改本文件挂载，pull 会打架，改成这样就不会了。
try:
    from . import protocol
    ALL_BLUEPRINTS += (protocol.bp,)
except ImportError:
    pass


def register_all(app):
    for bp in ALL_BLUEPRINTS:
        app.register_blueprint(bp)
