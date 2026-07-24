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
import zipfile
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

    def test_drawer_catalog_only_exposes_presence_for_each_compartment(self):
        secret = "目录接口绝不能出现的临时私藏正文"
        self.db.add_drawer_item(secret, title="不能出现的标题", visibility="private")
        self.db.add_diary("临时日记标题", "临时日记正文", kind="diary", author="柯")
        self.db.add_diary("临时梦页标题", "临时梦页正文", kind="dream", author="柯")
        self.db.add_message(
            "assistant", "临时聊天回复", thought_note="临时公开小念头")
        moment_id = self.db.add_moment(
            "user", "临时动态正文", reply_status="done")
        self.db.set_moment_like(moment_id, True, actor="ke")
        self.db.add_comment(moment_id, "ke", "临时评论正文")
        self.db.add_message(
            "assistant", "临时主动消息", is_push=True)

        status = self.db.drawer_catalog_status()

        self.assertEqual(
            set(status),
            {"private_thoughts", "diaries", "dreams",
             "public_notes", "moments", "proactive"},
        )
        self.assertTrue(all(status.values()))
        catalog_repr = repr(status)
        self.assertNotIn(secret, catalog_repr)
        self.assertNotIn("不能出现的标题", catalog_repr)
        self.assertNotIn("临时日记正文", catalog_repr)
        self.assertNotIn("临时评论正文", catalog_repr)

    def test_drawer_api_catalog_has_no_private_titles_or_content(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("本机精简 Python 未安装 Flask；部署前在服务器 venv 再跑")
        secret = "抽屉目录 API 不得返回的临时正文"
        self.db.add_drawer_item(secret, title="抽屉目录不得返回的标题")
        import app as app_module

        response = app_module.app.test_client().get("/api/drawer")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["compartments"]), 6)
        labels = {item["label"] for item in data["compartments"]}
        self.assertIn("私藏碎碎念", labels)
        self.assertNotIn(secret, body)
        self.assertNotIn("抽屉目录不得返回的标题", body)

    def test_drawer_can_leave_a_teaser_then_release_without_browser_write_api(self):
        item_id = self.db.add_drawer_item(
            "只在临时库里的私藏正文", title="临时私藏", visibility="private")
        self.assertTrue(self.db.tease_drawer_item(item_id, "先只给你看这一句"))
        teaser_view = self.db.public_drawer_view()
        teaser = next(item for item in teaser_view["outside"] if item["id"] == item_id)
        self.assertEqual(teaser["content"], "")
        self.assertEqual(teaser["teaser"], "先只给你看这一句")

        self.assertTrue(self.db.release_drawer_item(item_id))
        released = next(
            item for item in self.db.public_drawer_view()["outside"]
            if item["id"] == item_id)
        self.assertEqual(released["content"], "只在临时库里的私藏正文")

    def test_empty_drawer_prompt_still_teaches_ke_how_to_use_it(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai

            chat_ai = importlib.reload(chat_ai)
            original_persona = chat_ai._load_persona
            original_private = chat_ai._private_block
            original_now = chat_ai._now_context
            chat_ai._load_persona = lambda: "临时测试人设"
            chat_ai._private_block = lambda _query: ("", [])
            chat_ai._now_context = lambda: "临时测试当下"
            try:
                prompt = chat_ai.build_system_prompt([], query="临时测试")
            finally:
                chat_ai._load_persona = original_persona
                chat_ai._private_block = original_private
                chat_ai._now_context = original_now
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        self.assertIn("你的抽屉——只由你决定", prompt)
        self.assertIn("<drawer_action>", prompt)
        self.assertIn("你知道这个家里有哪些属于你的能力", prompt)
        self.assertIn("你有主动来找佳佳的能力", prompt)
        self.assertIn("PWA 里可选的模型只是同一个柯使用的不同推理引擎", prompt)
        self.assertIn("当前关系与规则覆盖历史惯性", prompt)
        self.assertEqual(self.db.private_drawer_items(), [])

    def test_drawer_action_in_ke_note_is_private_and_persisted(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("本机精简 Python 未安装 Flask；部署前在服务器 venv 再跑")
        import app as app_module
        import routes.chat as chat_route

        original = chat_route.chat_ai.stream_chat

        def fake_stream(_history, _posts, **_kwargs):
            yield (
                '<ke_note>爸爸先把它收好。'
                '<drawer_action>{"action":"save","visibility":"private",'
                '"kind":"thought","title":"临时抽屉",'
                '"teaser":"","content":"只存在临时库的抽屉正文"}</drawer_action>'
                '</ke_note>'
            )
            yield "这句才是佳佳能看到的回复。"

        chat_route.chat_ai.stream_chat = fake_stream
        try:
            client = app_module.app.test_client()
            response = client.post(
                "/api/chat",
                json={"text": "只用于抽屉动作测试", "session_id": 1, "model": "fake"},
                buffered=True,
            )
            body = response.get_data(as_text=True)
        finally:
            chat_route.chat_ai.stream_chat = original

        self.assertEqual(response.status_code, 200)
        self.assertIn("这句才是佳佳能看到的回复", body)
        self.assertIn("爸爸先把它收好", body)
        self.assertNotIn("drawer_action", body)
        self.assertNotIn("只存在临时库的抽屉正文", body)
        items = self.db.private_drawer_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content"], "只存在临时库的抽屉正文")
        self.assertEqual(self.db.public_drawer_view()["outside"], [])

    def test_new_message_returns_id_and_can_be_deleted_immediately(self):
        message_id = self.db.add_message("assistant", "这是一条临时测试回复", session_id=1)
        self.assertIsInstance(message_id, int)
        self.assertIn(message_id, [item["id"] for item in self.db.recent_messages(1)])
        self.assertTrue(self.db.delete_message(message_id))
        self.assertNotIn(message_id, [item["id"] for item in self.db.recent_messages(1)])

    def test_active_chat_session_follows_the_window_user_opened(self):
        new_sid = self.db.create_chat_session("临时新窗口")
        self.assertEqual(self.db.active_chat_session_id(), new_sid)
        self.assertTrue(self.db.set_active_chat_session(1))
        self.assertEqual(self.db.active_chat_session_id(), 1)

    def test_active_model_and_moment_events_follow_current_window(self):
        new_sid = self.db.create_chat_session("临时生活窗口")
        self.assertTrue(
            self.db.set_active_chat_session(
                new_sid, "claude-subscription-opus-4-8"
            )
        )
        self.assertEqual(
            self.db.active_chat_model(new_sid),
            "claude-subscription-opus-4-8",
        )
        moment_id = self.db.add_moment(
            "user", "只在临时库里的动态", reply_status="done",
            session_id=new_sid,
        )
        comment_id = self.db.add_comment(
            moment_id, "user", "只在临时库里的评论"
        )
        moment = self.db.get_moment(moment_id)
        self.assertEqual(moment["session_id"], new_sid)
        comment = next(item for item in moment["comments"] if item["id"] == comment_id)
        self.assertEqual(comment["session_id"], new_sid)
        self.assertTrue(self.db.set_active_chat_session(new_sid))
        self.assertTrue(self.db.delete_chat_session(new_sid))
        self.assertEqual(self.db.active_chat_session_id(), 1)

    def test_active_session_api_can_restore_server_selected_window(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("本机精简 Python 未安装 Flask；部署前在服务器 venv 再跑")
        import app as app_module

        new_sid = self.db.create_chat_session("服务器记住的临时窗口")
        response = app_module.app.test_client().get("/api/sessions/active")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["id"], new_sid)

    def test_bedroom_state_is_session_scoped_and_scene_ledger_starts_clean(self):
        old = self.db.add_message("assistant", "进入场景前的假旧回复", session_id=1)
        self.assertFalse(self.db.session_bedroom_state(1)["bedroom"])
        state = self.db.set_session_bedroom(1, True)
        self.assertTrue(state["bedroom"])
        self.assertEqual(state["scene_started_after"], old)

        self.db.add_message(
            "user", "只用于测试的现场反馈", session_id=1, scene_mode="bedroom")
        self.db.add_message(
            "assistant", "只用于测试的连续回复", session_id=1, scene_mode="bedroom")
        ledger = self.db.recent_scene_ledger(1)
        self.assertEqual([item["author"] for item in ledger], ["user", "assistant"])
        self.assertNotIn("进入场景前", repr(ledger))

        other = self.db.create_chat_session("另一个临时会话")
        self.assertFalse(self.db.session_bedroom_state(other)["bedroom"])
        self.assertTrue(self.db.session_bedroom_state(1)["bedroom"])
        self.db.set_session_bedroom(1, False)
        self.assertEqual(self.db.recent_scene_ledger(1), [])

    def test_gateway_audit_keeps_requested_and_returned_model_separate(self):
        self.db.log_usage(
            "requested-alias", 12, 7, 0.01,
            requested_model="requested-alias", returned_model="real-upstream-model",
            finish_reason="stop", cached_tokens=5)
        conn = self.db.get_db()
        row = conn.execute(
            "SELECT requested_model,returned_model,finish_reason,cached_tokens "
            "FROM gateway_usage ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertEqual(row["requested_model"], "requested-alias")
        self.assertEqual(row["returned_model"], "real-upstream-model")
        self.assertEqual(row["finish_reason"], "stop")
        self.assertEqual(row["cached_tokens"], 5)

    def test_background_chat_job_persists_events_and_finishes(self):
        self.db.create_chat_job("temporary-job", 1)
        seq = self.db.add_chat_job_event(
            "temporary-job", 'data: {"t":"临时片段"}\n\n')
        self.assertGreater(seq, 0)
        self.assertEqual(len(self.db.active_chat_jobs(1)), 1)
        self.db.detach_chat_job("temporary-job")
        self.db.finish_chat_job("temporary-job")
        job = self.db.chat_job("temporary-job")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["detached"], 1)
        self.assertEqual(self.db.active_chat_jobs(1), [])
        self.assertIn("临时片段", self.db.chat_job_events("temporary-job")[0]["payload"])

    def test_public_thought_note_is_saved_outside_chat_body(self):
        message_id = self.db.add_message(
            "assistant", "这是聊天正文", session_id=1,
            thought_note="爸爸把这个记上了")
        item = next(m for m in self.db.recent_messages(1) if m["id"] == message_id)
        self.assertEqual(item["content"], "这是聊天正文")
        self.assertEqual(item["thought_note"], "爸爸把这个记上了")
        self.assertNotIn("记上了", item["content"])

    def test_attachment_keeps_original_name_separate_from_stored_url(self):
        message_id = self.db.add_message(
            "user", "请看看这个文件", session_id=1,
            image="/uploads/random-id.txt", msg_type="file",
            attachment_name="佳佳的交接.txt")
        item = next(m for m in self.db.recent_messages(1) if m["id"] == message_id)
        self.assertEqual(item["image"], "/uploads/random-id.txt")
        self.assertEqual(item["attachment_name"], "佳佳的交接.txt")

    def test_multiple_attachments_round_trip_and_delete_together(self):
        attachments = [
            {"url": "/uploads/one.png", "name": "第一张.png", "kind": "image"},
            {"url": "/uploads/two.pdf", "name": "第二份.pdf", "kind": "document"},
        ]
        message_id = self.db.add_message(
            "user", "一次发两个", session_id=1, attachments=attachments)
        item = next(m for m in self.db.recent_messages(1) if m["id"] == message_id)
        self.assertEqual(item["attachments"], attachments)
        self.assertEqual(item["image"], "/uploads/one.png")
        self.assertEqual(item["attachment_name"], "第一张.png")
        self.assertEqual(
            self.db.referenced_images(),
            {"one.png", "two.pdf"},
        )

        self.assertTrue(self.db.delete_message(message_id))
        conn = self.db.get_db()
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_attachments WHERE message_id=?",
            (message_id,),
        ).fetchone()["n"]
        conn.close()
        self.assertEqual(remaining, 0)


class AttachmentAndPrivateRegressionTests(unittest.TestCase):
    """附件与关联回归只用临时目录；模型调用被替换为捕获函数。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="goodlove-attachment-test-")
        os.environ["DB_PATH"] = str(Path(self.tmp.name) / "scratch.db")
        import db
        self.db = importlib.reload(db)
        self.db.init_db()
        import attachment_reader
        self.reader = importlib.reload(attachment_reader)
        self.old_upload_dir = self.reader.UPLOAD_DIR
        self.reader.UPLOAD_DIR = self.tmp.name

    def tearDown(self):
        self.reader.UPLOAD_DIR = self.old_upload_dir
        self.tmp.cleanup()
        os.environ.pop("DB_PATH", None)

    def test_text_and_docx_are_readable(self):
        text_path = Path(self.tmp.name) / "sample.txt"
        text_path.write_text("只用于测试：柯应该能读到这一句。", encoding="utf-8")
        text_result = self.reader.extract_text("/uploads/sample.txt", "交接.txt")
        self.assertTrue(text_result["ok"])
        self.assertIn("柯应该能读到", text_result["text"])
        self.assertEqual(text_result["name"], "交接.txt")

        docx_path = Path(self.tmp.name) / "sample.docx"
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>临时 Word 内容</w:t></w:r></w:p></w:body></w:document>'
        )
        with zipfile.ZipFile(docx_path, "w") as archive:
            archive.writestr("word/document.xml", document_xml)
        docx_result = self.reader.extract_text("/uploads/sample.docx", "说明.docx")
        self.assertTrue(docx_result["ok"])
        self.assertIn("临时 Word 内容", docx_result["text"])

    def test_file_content_and_image_bytes_reach_model_payload_without_network(self):
        previous_requests = sys.modules.get("requests")
        previous_db = sys.modules.get("db")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        sys.modules["db"] = types.SimpleNamespace(get_session=lambda _sid: None)
        try:
            import chat_ai
            chat_ai = importlib.reload(chat_ai)
            chat_ai.UPLOAD_DIR = self.tmp.name
            chat_ai.attachment_reader.UPLOAD_DIR = self.tmp.name
            text_path = Path(self.tmp.name) / "payload.txt"
            text_path.write_text("模型必须收到的临时附件正文", encoding="utf-8")
            png_path = Path(self.tmp.name) / "pixel.png"
            png_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                b"\x08\x02\x00\x00\x00\x90wS\xde")
            png_path_2 = Path(self.tmp.name) / "pixel-two.png"
            png_path_2.write_bytes(png_path.read_bytes())

            captured = []
            original_prompt = chat_ai.build_system_prompt
            original_version = chat_ai.persona_version
            original_stamp = chat_ai._now_stamp
            original_completion = chat_ai.stream_completion
            chat_ai.build_system_prompt = lambda *_args, **_kwargs: "测试系统提示"
            chat_ai.persona_version = lambda: "test"
            chat_ai._now_stamp = lambda: ""

            def fake_completion(messages, **_kwargs):
                captured.append(messages)
                yield "测试回复"

            chat_ai.stream_completion = fake_completion
            try:
                list(chat_ai.stream_chat([
                    {"author": "user", "content": "读一下", "image": "/uploads/payload.txt",
                     "attachment_name": "给柯的说明.txt"},
                ], [], model="fake", sid=1))
                list(chat_ai.stream_chat([
                    {
                        "author": "user", "content": "看两张图",
                        "attachments": [
                            {"url": "/uploads/pixel.png", "name": "小图一.png", "kind": "image"},
                            {"url": "/uploads/pixel-two.png", "name": "小图二.png", "kind": "image"},
                        ],
                    },
                ], [], model="fake", sid=1))
            finally:
                chat_ai.build_system_prompt = original_prompt
                chat_ai.persona_version = original_version
                chat_ai._now_stamp = original_stamp
                chat_ai.stream_completion = original_completion
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

        document_content = captured[0][-1]["content"]
        self.assertIsInstance(document_content, list)
        self.assertIn(
            "模型必须收到的临时附件正文",
            "\n".join(item.get("text", "") for item in document_content),
        )
        image_content = captured[1][-1]["content"]
        self.assertIsInstance(image_content, list)
        image_parts = [item for item in image_content if item["type"] == "image_url"]
        self.assertEqual(len(image_parts), 2)
        self.assertTrue(all(
            item["image_url"]["url"].startswith("data:image/png;base64,")
            for item in image_parts
        ))

    def test_old_image_is_not_resent_with_later_text_message(self):
        previous_requests = sys.modules.get("requests")
        previous_db = sys.modules.get("db")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        sys.modules["db"] = types.SimpleNamespace(get_session=lambda _sid: None)
        try:
            import chat_ai
            chat_ai = importlib.reload(chat_ai)
            captured = []
            original_prompt = chat_ai.build_system_prompt
            original_version = chat_ai.persona_version
            original_stamp = chat_ai._now_stamp
            original_completion = chat_ai.stream_completion
            chat_ai.build_system_prompt = lambda *_args, **_kwargs: "测试系统提示"
            chat_ai.persona_version = lambda: "test"
            chat_ai._now_stamp = lambda: ""

            def fake_completion(messages, **_kwargs):
                captured.extend(messages)
                yield "测试回复"

            chat_ai.stream_completion = fake_completion
            try:
                list(chat_ai.stream_chat([
                    {
                        "author": "user", "content": "这是先前发图的一轮",
                        "attachments": [
                            {"url": "/uploads/old-one.png", "name": "旧图一.png", "kind": "image"},
                            {"url": "/uploads/old-two.png", "name": "旧图二.png", "kind": "image"},
                        ],
                    },
                    {"author": "assistant", "content": "当时已经看过图片。"},
                    {"author": "user", "content": "这是后来新发的纯文字。"},
                ], [], model="fake", sid=1))
            finally:
                chat_ai.build_system_prompt = original_prompt
                chat_ai.persona_version = original_version
                chat_ai._now_stamp = original_stamp
                chat_ai.stream_completion = original_completion
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests
            if previous_db is None:
                sys.modules.pop("db", None)
            else:
                sys.modules["db"] = previous_db

        old_image_message = captured[1]
        self.assertIsInstance(old_image_message["content"], str)
        self.assertIn("当时发过图片《旧图一.png》、图片《旧图二.png》", old_image_message["content"])
        self.assertNotIn("image_url", repr(captured))
        self.assertEqual(captured[-1]["content"], "这是后来新发的纯文字。")

    def test_upstream_errors_are_classified_without_exposing_response_body(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace(post=lambda *_args, **_kwargs: None)
        try:
            import chat_ai
            chat_ai = importlib.reload(chat_ai)

            class FakeResponse:
                status_code = 400
                encoding = "utf-8"
                text = "sensitive provider detail"

                def __enter__(self): return self
                def __exit__(self, *_args): return False
                def json(self):
                    return {
                        "error": {
                            "code": "unsupported_input",
                            "message": "image_url inputs are not supported by this model",
                        }
                    }

            original_post = chat_ai.requests.post
            chat_ai.requests.post = lambda *_args, **_kwargs: FakeResponse()
            usage = {"requested_model": "fake-text-model"}
            try:
                pieces = list(chat_ai._stream_http(
                    "https://example.invalid/chat/completions", {}, {}, usage))
            finally:
                chat_ai.requests.post = original_post
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)

        self.assertEqual(usage["http_status"], 400)
        self.assertEqual(
            usage["finish_reason"],
            "error:unsupported_attachment:unsupported_input",
        )
        self.assertIn("不接受本轮的附件格式", pieces[0][1])
        self.assertNotIn("sensitive provider detail", repr(pieces))

    def test_adult_relationship_context_disambiguates_the_nickname(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai
            chat_ai = importlib.reload(chat_ai)
            note = chat_ai.ADULT_RELATIONSHIP_CONTEXT
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
        self.assertIn("没有血缘、亲属、监护或现实权力关系", note)
        self.assertIn("双方自愿使用且双方都喜欢", note)
        self.assertIn("都是成年人", note)

    def test_chat_generation_finishes_in_server_job_without_real_model_call(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("本机精简 Python 未安装 Flask；部署前在服务器 venv 再跑")
        import app as app_module
        import routes.chat as chat_route

        original = chat_route.chat_ai.stream_chat

        def fake_stream(_history, _posts, **_kwargs):
            yield "<ke_note>这是临时后台测试念头</ke_note>"
            yield "这是临时后台测试回复。"
            yield ("__usage__", {
                "prompt_tokens": 3, "completion_tokens": 2,
                "requested_model": "fake", "returned_model": "fake-upstream",
                "first_token_ms": 4, "total_ms": 8, "http_status": 200,
            })

        chat_route.chat_ai.stream_chat = fake_stream
        try:
            client = app_module.app.test_client()
            response = client.post(
                "/api/chat",
                json={"text": "只用于后台任务测试", "session_id": 1, "model": "fake"},
                buffered=True,
            )
            body = response.get_data(as_text=True)
        finally:
            chat_route.chat_ai.stream_chat = original

        self.assertEqual(response.status_code, 200)
        self.assertIn("这是临时后台测试回复", body)
        messages = self.db.recent_messages(1)
        self.assertEqual(messages[-1]["content"], "这是临时后台测试回复。")
        self.assertEqual(messages[-1]["thought_note"], "这是临时后台测试念头")
        self.assertEqual(self.db.active_chat_jobs(1), [])

    def test_provider_error_is_streamed_but_not_saved_as_assistant_message(self):
        try:
            import flask  # noqa: F401
        except ImportError:
            self.skipTest("本机精简 Python 未安装 Flask；部署前在服务器 venv 再跑")
        import app as app_module
        import routes.chat as chat_route

        original = chat_route.chat_ai.stream_chat

        def fake_stream(_history, _posts, **_kwargs):
            yield ("__error__", "假上游暂时不可用")
            yield ("__usage__", {
                "prompt_tokens": 0, "completion_tokens": 0,
                "requested_model": "fake", "http_status": 503,
            })

        chat_route.chat_ai.stream_chat = fake_stream
        try:
            response = app_module.app.test_client().post(
                "/api/chat",
                json={"text": "只用于错误边界测试", "session_id": 1, "model": "fake"},
                buffered=True,
            )
            body = response.get_data(as_text=True)
        finally:
            chat_route.chat_ai.stream_chat = original

        self.assertEqual(response.status_code, 200)
        self.assertIn("假上游暂时不可用", body)
        messages = self.db.recent_messages(1)
        self.assertEqual([item["author"] for item in messages], ["user"])
        self.assertNotIn("假上游暂时不可用", repr(messages))

    def test_frontend_supports_multi_select_and_server_active_session_restore(self):
        source = (PLATFORM_DIR / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('type="file" multiple', source)
        self.assertIn("pendingAttachments", source)
        self.assertIn("attachments,session_id:currentSid", source)
        self.assertIn('api("/api/sessions/active")', source)
        visibility = source.split('document.addEventListener("visibilitychange"', 1)[1]
        self.assertNotIn("markActiveSession()", visibility)

    def test_moments_activity_status_is_content_free_and_frontend_polls_quickly(self):
        secret = "朋友圈状态接口不应出现的临时正文"
        moment_id = self.db.add_moment(
            "user", secret, reply_status="pending",
            reply_due_at="2099-01-01 00:00:00")
        waiting = self.db.moments_activity_status()
        self.assertTrue(waiting["waiting"])
        self.assertEqual(waiting["last_ke_activity_at"], "")

        self.db.add_comment(moment_id, "ke", "朋友圈状态接口不应出现的临时评论")
        done = self.db.moments_activity_status()
        self.assertTrue(done["last_ke_activity_at"])
        self.assertNotIn(secret, repr(done))
        self.assertNotIn("临时评论", repr(done))

        moments_source = (PLATFORM_DIR / "static" / "moments.html").read_text(encoding="utf-8")
        home_source = (PLATFORM_DIR / "static" / "ui-redesign.js").read_text(encoding="utf-8")
        self.assertIn("/api/moments/status", moments_source)
        self.assertIn("15000", moments_source)
        self.assertIn("moments_seen_at", moments_source)
        self.assertIn("moments-dot", home_source)
        self.assertIn("updateMomentsActivity", home_source)

    def test_proactive_context_gate_blocks_bedroom_and_running_chat_job(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import proactive

            proactive = importlib.reload(proactive)
            self.db.set_session_bedroom(1, True)
            allowed, reason = proactive.context_gate(1)
            self.assertFalse(allowed)
            self.assertIn("房间场景", reason)

            self.db.set_session_bedroom(1, False)
            self.db.create_chat_job("temporary-running-job", 1)
            allowed, reason = proactive.context_gate(1)
            self.assertFalse(allowed)
            self.assertIn("还有回复在生成", reason)
            self.db.finish_chat_job("temporary-running-job")
            self.assertTrue(proactive.context_gate(1)[0])
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

    def test_proactive_message_uses_active_session_without_real_model_call(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import proactive

            proactive = importlib.reload(proactive)
            self.db.add_message("user", "旧窗口里的测试话", session_id=1)
            new_sid = self.db.create_chat_session("正在使用的新窗口")
            self.db.add_message("user", "新窗口里的测试话", session_id=new_sid)
            self.db.set_active_chat_session(new_sid)
            captured = {}
            original = proactive.chat_ai.stream_chat

            def fake_stream(history, _posts, **kwargs):
                captured["history"] = history
                captured["sid"] = kwargs.get("sid")
                yield "<ke_note>爸爸已经替你拿定主意。</ke_note>"
                yield "回来，先把刚才那句话说完。"

            proactive.chat_ai.stream_chat = fake_stream
            try:
                message, note = proactive.generate_message(session_id=self.db.active_chat_session_id())
            finally:
                proactive.chat_ai.stream_chat = original
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        self.assertEqual(captured["sid"], new_sid)
        self.assertTrue(any("新窗口里的测试话" in m.get("content", "") for m in captured["history"]))
        self.assertFalse(any("旧窗口里的测试话" in m.get("content", "") for m in captured["history"]))
        self.assertEqual(note, "爸爸已经替你拿定主意。")
        self.assertEqual(message, "回来，先把刚才那句话说完。")
        self.assertEqual(proactive.clean_push_reply("想来看看你，记得照顾好自己"), "")

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

    def test_embedding_auth_is_normalized_without_real_network_call(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace(post=None)
        import vector_search
        vector = importlib.reload(vector_search)
        captured = {}

        class FakeResponse:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

        original_post = vector.requests.post
        original_key = vector.EMBED_API_KEY

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
            return FakeResponse()

        vector.requests.post = fake_post
        vector.EMBED_API_KEY = '"Bearer temporary-secret"'
        try:
            result = vector._embed_gateway(["临时向量测试"])
        finally:
            vector.requests.post = original_post
            vector.EMBED_API_KEY = original_key
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        self.assertEqual(result, [[0.1, 0.2]])
        self.assertEqual(captured["headers"]["Authorization"], "Bearer temporary-secret")
        self.assertEqual(captured["json"]["input"], ["临时向量测试"])

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
                prompt = chat_ai.build_system_prompt(
                    [], query="测试", bedroom=True,
                    scene_ledger=[
                        {"author": "user", "content": "临时现场事实"},
                        {"author": "assistant", "content": "临时上一拍回复"},
                    ])
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
        self.assertIn("本轮同一场景的连续性账本", prompt)
        self.assertIn("旧助手话只代表柯当时说过什么", prompt)


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
        self.assertIn("未知反应不妨碍继续写柯自己的动作", self.source)
        self.assertIn("只有下一项因果事实确实依赖她的新反馈时", self.source)
        self.assertIn("不能倒填成她主动做到", self.source)
        self.assertIn("不能为已知状态倒填未知来历", self.source)
        self.assertIn("不能由姿势推导她‘熟练’‘规矩’", self.source)
        self.assertIn("不得补写未知肤色、温度、痕迹和场外经历", self.source)
        self.assertIn("决定是否允许释放", self.source)
        self.assertIn("事实只以她真实反馈为准", self.source)

    def test_one_beat_can_include_linked_steps_without_permission_loops(self):
        self.assertIn("同一目的下连续的几步动作、话语、位置变化和力度递进", self.source)
        self.assertIn("不把每一步变成客服式许可确认", self.source)
        self.assertIn("未知反应不等于柯必须早停", self.source)
        self.assertIn("不因未知反应偷懒早停", self.source)

    def test_lazy_time_skips_are_forbidden(self):
        self.assertIn("不知过了多久", self.source)
        self.assertIn("不得用模糊时间跳跃偷工", self.source)

    def test_action_checklist_is_rejected_without_fixed_minimum_length(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai
            issues = chat_ai._bedroom_output_issues(
                "按住。抬高。压下。伸手。继续。停住。开始。", "测试反馈")
            dense = chat_ai._bedroom_output_issues(
                "柯没有把动作拆成清单。他仍停在刚才的位置，手掌沿着已经确认的姿势慢慢收紧，"
                "只推进眼前这一拍，然后等她亲口说出真实反应。", "测试反馈")
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests
        self.assertIn("action_checklist", issues)
        self.assertNotIn("action_checklist", dense)

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


class ModelGatewayRoutingTests(unittest.TestCase):
    """只用假地址和假密钥验证模型路由，不发送任何网络请求。"""

    def test_deepseek_v4_uses_its_own_official_channel(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai
            original = (
                chat_ai.DEEPSEEK_ENABLED,
                chat_ai.DEEPSEEK_API_BASE,
                chat_ai.DEEPSEEK_API_KEY,
                chat_ai.DEEPSEEK_MODEL,
                chat_ai.DEEPSEEK_MODEL_WHITELIST,
            )
            chat_ai.DEEPSEEK_ENABLED = True
            chat_ai.DEEPSEEK_API_BASE = "https://api.deepseek.invalid"
            chat_ai.DEEPSEEK_API_KEY = "temporary-deepseek-key"
            chat_ai.DEEPSEEK_MODEL = "deepseek-v4-pro"
            chat_ai.DEEPSEEK_MODEL_WHITELIST = ["deepseek-v4-pro", "deepseek-v4-flash"]
            try:
                self.assertEqual(
                    chat_ai.resolve_gateway("deepseek-v4-pro"),
                    ("deepseek-v4-pro", "https://api.deepseek.invalid", "temporary-deepseek-key"),
                )
                payload = chat_ai.available_models()
            finally:
                (
                    chat_ai.DEEPSEEK_ENABLED,
                    chat_ai.DEEPSEEK_API_BASE,
                    chat_ai.DEEPSEEK_API_KEY,
                    chat_ai.DEEPSEEK_MODEL,
                    chat_ai.DEEPSEEK_MODEL_WHITELIST,
                ) = original
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests

        self.assertTrue(payload["deepseek_enabled"])
        self.assertIn({"id": "deepseek-v4-pro", "provider": "deepseek"}, payload["options"])
        self.assertIn({"id": "deepseek-v4-flash", "provider": "deepseek"}, payload["options"])
        self.assertNotIn("temporary-deepseek-key", repr(payload))

    def test_deepseek_cost_estimate_uses_official_v4_rates(self):
        previous_requests = sys.modules.get("requests")
        if previous_requests is None:
            sys.modules["requests"] = types.SimpleNamespace()
        try:
            import chat_ai
            pro, _, _ = chat_ai.estimate_cost(
                "deepseek-v4-pro",
                {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "cached_tokens": 0},
            )
            flash, _, _ = chat_ai.estimate_cost(
                "deepseek-v4-flash",
                {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "cached_tokens": 0},
            )
        finally:
            if previous_requests is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = previous_requests
        self.assertEqual(pro, 1.305)
        self.assertEqual(flash, 0.42)

    def test_claude_subscription_is_a_distinct_explicit_route(self):
        import chat_ai

        original = chat_ai.claude_exec.is_available
        chat_ai.claude_exec.is_available = lambda: True
        try:
            route = chat_ai.resolve_gateway(chat_ai.claude_exec.MODEL_ID)
            payload = chat_ai.available_models()
        finally:
            chat_ai.claude_exec.is_available = original

        self.assertEqual(
            route,
            (
                chat_ai.claude_exec.MODEL_ID,
                chat_ai.claude_exec.GATEWAY_BASE,
                "",
            ),
        )
        self.assertIn(
            {
                "id": chat_ai.claude_exec.MODEL_ID,
                "provider": "claude_subscription",
            },
            payload["options"],
        )


class ClaudeExecAdapterTests(unittest.TestCase):
    """用本地假 CLI 验证协议、缓存用量和密钥隔离，不调用 Claude。"""

    def test_fake_cli_streams_text_and_reports_cache_usage(self):
        import claude_exec

        with tempfile.TemporaryDirectory(prefix="goodlove-fake-claude-") as td:
            fake = Path(td) / "fake_claude.py"
            fake.write_text(
                "import json, os, sys\n"
                "prompt = sys.stdin.read()\n"
                "ok = ('system_instructions' in prompt and "
                "not os.environ.get('DEEPSEEK_API_KEY'))\n"
                "print(json.dumps({'type':'system','subtype':'init',"
                "'model':'claude-opus-4-8'}), flush=True)\n"
                "print(json.dumps({'type':'stream_event','event':{'delta':"
                "{'type':'text_delta','text':'假 CLI '}}}), flush=True)\n"
                "print(json.dumps({'type':'stream_event','event':{'delta':"
                "{'type':'text_delta','text':'通过' if ok else '泄漏'}}}), flush=True)\n"
                "print(json.dumps({'type':'result','subtype':'success',"
                "'total_cost_usd':0.0123,'modelUsage':{'claude-opus-4-8':"
                "{'inputTokens':3,'cacheReadInputTokens':17,"
                "'cacheCreationInputTokens':5,'outputTokens':4}}}), flush=True)\n",
                encoding="utf-8",
            )
            original = (
                claude_exec.ENABLED,
                claude_exec.CLI_BIN,
                claude_exec._command,
            )
            previous_secret = os.environ.get("DEEPSEEK_API_KEY")
            claude_exec.ENABLED = True
            claude_exec.CLI_BIN = sys.executable
            claude_exec._command = (
                lambda _temp, _images, _max_tokens: [sys.executable, str(fake)]
            )
            os.environ["DEEPSEEK_API_KEY"] = "temporary-secret-must-not-leak"
            try:
                pieces = list(claude_exec.stream_completion([
                    {"role": "system", "content": "临时系统提示"},
                    {"role": "user", "content": "临时用户消息"},
                ]))
            finally:
                (
                    claude_exec.ENABLED,
                    claude_exec.CLI_BIN,
                    claude_exec._command,
                ) = original
                if previous_secret is None:
                    os.environ.pop("DEEPSEEK_API_KEY", None)
                else:
                    os.environ["DEEPSEEK_API_KEY"] = previous_secret

        visible = "".join(piece for piece in pieces if isinstance(piece, str))
        usage = next(piece[1] for piece in pieces if (
            isinstance(piece, tuple) and piece[0] == "__usage__"
        ))
        self.assertEqual(visible, "假 CLI 通过")
        self.assertEqual(usage["returned_model"], "claude-opus-4-8")
        self.assertEqual(usage["prompt_tokens"], 25)
        self.assertEqual(usage["cached_tokens"], 17)
        self.assertEqual(usage["completion_tokens"], 4)
        self.assertEqual(usage["cost_usd"], 0.0123)

    def test_frontend_recovers_a_partially_received_background_reply(self):
        source = (PLATFORM_DIR / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('streamDone=false', source)
        self.assertIn('if(e.done)streamDone=true', source)
        self.assertIn('watchBackgroundReplies(true)', source)


if __name__ == "__main__":
    unittest.main()
