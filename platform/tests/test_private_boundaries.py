"""隐私边界回归测试。

所有数据都写入系统临时目录中的一次性 SQLite；不会读取或修改正式 memories.db。
"""
import importlib
import datetime
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

    def test_new_message_returns_id_and_can_be_deleted_immediately(self):
        message_id = self.db.add_message("assistant", "这是一条临时测试回复", session_id=1)
        self.assertIsInstance(message_id, int)
        self.assertIn(message_id, [item["id"] for item in self.db.recent_messages(1)])
        self.assertTrue(self.db.delete_message(message_id))
        self.assertNotIn(message_id, [item["id"] for item in self.db.recent_messages(1)])

    def test_deleting_summarized_message_invalidates_derived_summary(self):
        first = self.db.add_message("user", "只用于测试的旧消息", session_id=1)
        self.db.add_message("assistant", "只用于测试的旧回复", session_id=1)
        self.db.set_session_summary(1, "由临时消息产生的旧摘要", first, "test-version")

        self.assertTrue(self.db.delete_message(first))
        session = self.db.get_session(1)
        self.assertEqual(session["summary"], "")
        self.assertEqual(session["summarized_until"], 0)
        self.assertEqual(session["summary_version"], "")

    def test_deleting_unsummarized_message_keeps_valid_summary(self):
        first = self.db.add_message("user", "已经被摘要的测试消息", session_id=1)
        self.db.set_session_summary(1, "仍然有效的旧摘要", first, "test-version")
        latest = self.db.add_message("assistant", "尚未进入摘要的新回复", session_id=1)

        self.assertTrue(self.db.delete_message(latest))
        session = self.db.get_session(1)
        self.assertEqual(session["summary"], "仍然有效的旧摘要")
        self.assertEqual(session["summarized_until"], first)

    def test_relationship_state_only_exposes_human_words(self):
        import relationship_state

        state = importlib.reload(relationship_state)
        view = state.public_view()
        self.assertEqual(set(view), {"presence", "tide", "lead", "note", "relationship"})
        self.assertTrue(all(isinstance(value, str) and value for value in view.values()))
        self.assertFalse(any(isinstance(value, (int, float)) for value in view.values()))

    def test_three_taps_queue_one_recoverable_signal(self):
        import relationship_state

        state = importlib.reload(relationship_state)
        first = state.queue_signal("triple_tap")
        second = state.queue_signal("triple_tap")
        self.assertEqual(first, second)
        claimed = state.claim_signal()
        self.assertEqual(claimed["id"], first)
        state.finish_signal(first, success=False)
        retried = state.claim_signal()
        self.assertEqual(retried["id"], first)
        state.finish_signal(first, success=True)
        self.assertIsNone(state.claim_signal())

    def test_moments_recall_is_relevant_recent_and_deletable(self):
        import moments_ai

        moments = importlib.reload(moments_ai)
        old_id = self.db.add_moment("user", "买猫粮时想起那只橘猫", reply_status="done")
        recent_id = self.db.add_moment("user", "今天买猫粮时又想起那只橘猫", reply_status="done")
        self.db.add_moment("user", "窗外的晚霞很好看", reply_status="done")
        conn = self.db.get_db()
        old_time = (moments.china_now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE moments SET created_at=? WHERE id=?", (old_time, old_id))
        conn.commit(); conn.close()

        related = moments.related_moments("猫粮快没有了", limit=2, max_age_days=14)
        self.assertEqual([item["id"] for item in related], [recent_id])
        self.db.delete_moment(recent_id)
        self.assertEqual(moments.related_moments("猫粮快没有了", limit=2, max_age_days=14), [])

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

    def test_living_voice_rule_rejects_assistant_templates(self):
        self.assertIn("活人感与表达节奏", self.source)
        self.assertIn("不要先复述问题", self.source)
        self.assertIn("不把佳佳当病人", self.source)
        self.assertIn("不为了显得深情而重复旧记忆", self.source)

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
