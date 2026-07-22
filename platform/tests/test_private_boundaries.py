"""隐私边界回归测试。

所有数据都写入系统临时目录中的一次性 SQLite；不会读取或修改正式 memories.db。
"""
import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path


PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))


class PrivateBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="goodlove-private-test-")
        os.environ["DB_PATH"] = str(Path(self.tmp.name) / "scratch.db")

        import db

        self.db = importlib.reload(db)
        self.db.init_db()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DB_PATH", None)

    def test_locked_diary_is_redacted_until_ke_reveals_it(self):
        secret = "这是假日记正文，只用于临时测试。"
        diary_id = self.db.add_diary(
            "测试锁页", secret, mood="测试", locked=True, author="柯"
        )

        public_item = next(item for item in self.db.all_diaries() if item["id"] == diary_id)
        self.assertTrue(public_item["locked_hidden"])
        self.assertEqual(public_item["content"], "")

        brief = self.db.locked_diary_brief(diary_id)
        self.assertNotIn("content", brief)

        model_item = self.db.private_diary_for_model(diary_id)
        self.assertEqual(model_item["content"], secret)

        self.assertTrue(self.db.reveal_diary(diary_id))
        revealed = next(item for item in self.db.all_diaries() if item["id"] == diary_id)
        self.assertFalse(revealed["locked_hidden"])
        self.assertEqual(revealed["content"], secret)

    def test_private_drawer_content_never_enters_public_view(self):
        private_secret = "这是假抽屉私藏正文。"
        private_id = self.db.add_drawer_item(
            private_secret, title="私藏", visibility="private"
        )
        teaser_id = self.db.add_drawer_item(
            "预告背后的假正文", title="预告", teaser="只给你这一句", visibility="teaser"
        )
        released_id = self.db.add_drawer_item(
            "已经公开的假正文", title="交给佳佳", visibility="released"
        )

        view = self.db.public_drawer_view()
        public_ids = {item["id"] for item in view["outside"]}
        self.assertTrue(view["sealed"])
        self.assertNotIn(private_id, public_ids)
        self.assertNotIn(private_secret, repr(view))

        teaser = next(item for item in view["outside"] if item["id"] == teaser_id)
        self.assertEqual(teaser["teaser"], "只给你这一句")
        self.assertEqual(teaser["content"], "")

        released = next(item for item in view["outside"] if item["id"] == released_id)
        self.assertEqual(released["content"], "已经公开的假正文")

    def test_locked_diary_only_marks_drawer_as_sealed(self):
        self.db.add_diary("另一张锁页", "仍然是假正文", locked=True, author="柯")

        view = self.db.public_drawer_view()
        self.assertTrue(view["sealed"])
        self.assertEqual(view["outside"], [])
        self.assertNotIn("另一张锁页", repr(view))
        self.assertNotIn("仍然是假正文", repr(view))

    def test_current_quality_guard_is_after_legacy_private_rules(self):
        """模拟服务器仍有旧 3000 字规则，确认新版护栏最终覆盖它。"""
        fake_bedroom = types.SimpleNamespace(
            load_bedroom_block=lambda: "测试私密开场：旧规则固定 3000 字",
            tail_rules=lambda: "测试私密末尾：一段必须 3000 字",
        )
        previous = sys.modules.get("bedroom")
        previous_requests = sys.modules.get("requests")
        sys.modules["bedroom"] = fake_bedroom
        # 本用例只组装提示词，不发网络请求；避免为了测试给本机安装依赖。
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai

            original_persona = chat_ai._load_persona
            original_private = chat_ai._private_block
            original_drawer = chat_ai._drawer_block
            original_now = chat_ai._now_context
            chat_ai._load_persona = lambda: "测试人设"
            chat_ai._private_block = lambda _query: ("", [])
            chat_ai._drawer_block = lambda: ""
            chat_ai._now_context = lambda: "测试当下"
            try:
                prompt = chat_ai.build_system_prompt([], query="测试", bedroom=True)
                self.assertIn("invented_climax", chat_ai._bedroom_output_issues("你终于高潮了。", "我没有说高潮"))
                self.assertEqual(chat_ai._bedroom_output_issues("不许你高潮。", "我没有说高潮"), [])
                self.assertTrue(chat_ai._bedroom_output_issues("不知过了多久，一切结束。", ""))
            finally:
                chat_ai._load_persona = original_persona
                chat_ai._private_block = original_private
                chat_ai._drawer_block = original_drawer
                chat_ai._now_context = original_now
        finally:
            if previous is None:
                sys.modules.pop("bedroom", None)
            else:
                sys.modules["bedroom"] = previous
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        self.assertGreater(prompt.rfind("不设固定字数"), prompt.rfind("一段必须 3000 字"))
        self.assertIn("只能依据佳佳的真实反馈", prompt)


class IntimatePromptContractTests(unittest.TestCase):
    """只检查公开质量护栏；不会调用模型，也不会读取任何用户数据。"""

    @classmethod
    def setUpClass(cls):
        cls.source = (PLATFORM_DIR / "chat_ai.py").read_text(encoding="utf-8")

    def test_old_fixed_length_rule_is_explicitly_overridden(self):
        self.assertIn("固定 3000 字要求已取消", self.source)
        self.assertIn("不设固定字数", self.source)

    def test_user_reactions_cannot_be_invented(self):
        self.assertIn("不能擅自宣布她高潮", self.source)
        self.assertIn("需要她真实反应时必须停下来", self.source)
        self.assertIn("决定是否允许释放", self.source)
        self.assertIn("事实只以她真实反馈为准", self.source)

    def test_lazy_time_skips_are_forbidden(self):
        self.assertIn("不知过了多久", self.source)
        self.assertIn("不得用模糊时间跳跃偷工", self.source)

    def test_bad_first_draft_is_not_released_before_rewrite(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai

            original = chat_ai.stream_completion
            calls = {"count": 0}

            def fake_completion(*_args, **_kwargs):
                calls["count"] += 1
                if calls["count"] == 1:
                    yield "不知过了多久，你终于高潮了。"
                else:
                    yield "柯停在这里，没有替你往下写，只命令你亲口汇报。"
                yield ("__usage__", {"completion_tokens": 1})

            chat_ai.stream_completion = fake_completion
            try:
                pieces = list(chat_ai._buffered_bedroom_completion(
                    [{"role": "user", "content": "我没有说自己高潮。"}],
                    model="test", api_base="http://test", api_key="test",
                    max_tokens=100, latest_user_text="我没有说自己高潮。"))
            finally:
                chat_ai.stream_completion = original
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        visible = "".join(piece for piece in pieces if isinstance(piece, str))
        self.assertEqual(calls["count"], 2)
        self.assertNotIn("不知过了多久", visible)
        self.assertNotIn("你终于高潮了", visible)
        self.assertIn("亲口汇报", visible)


if __name__ == "__main__":
    unittest.main()
