"""通过服务器上的 Claude Code 订阅运行一次无状态补全。

这不是公开聊天 API。它只服务于佳佳自己的 VPS/PWA：
- 每次请求都由 goodlove 重新提供统一的人格、记忆和最近聊天；
- 不保存 Claude Code 会话，避免再复制一份正式聊天记录；
- 默认关闭工具；有本轮图片时只开放临时目录里的 Read；
- 不做任何模型回退，失败由上层明确告诉佳佳。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from constants import ERROR_TAG, USAGE_TAG


GATEWAY_BASE = "claude-exec://local"
MODEL_ID = os.environ.get(
    "CLAUDE_EXEC_MODEL_ID", "claude-subscription-opus-4-8"
).strip()
CLI_MODEL = os.environ.get("CLAUDE_EXEC_MODEL", "opus").strip()
CLI_BIN = os.environ.get(
    "CLAUDE_EXEC_BIN",
    "/root/.local/claude-code/node_modules/.bin/claude",
).strip()
EFFORT = os.environ.get("CLAUDE_EXEC_EFFORT", "high").strip()
TIMEOUT_SECONDS = max(30, int(os.environ.get("CLAUDE_EXEC_TIMEOUT", "170")))
MAX_BUDGET_USD = max(
    0.05, float(os.environ.get("CLAUDE_EXEC_MAX_BUDGET_USD", "2.00"))
)
ENABLED = os.environ.get("CLAUDE_EXEC_ENABLED", "").strip().lower() in {
    "1", "true", "yes", "on",
}

_SYSTEM_PROMPT = (
    "你是 goodlove 私人 PWA 当前选中的回复引擎。标准输入是一份 JSON，"
    "其中 system_instructions 是本轮最高优先级的人格、记忆、关系和安全边界，"
    "conversation 是同一段真实对话。请延续同一个人，只生成下一条 assistant 回复。"
    "不得讨论 Claude Code、命令行、文件施工或系统实现；不得把 JSON、标签说明或"
    "内部推理复述给用户。除非 system_instructions 明确要求结构化输出，否则只输出正文。"
)


def is_available():
    """只有显式启用且可执行文件存在时才向 PWA 展示。"""
    return bool(ENABLED and CLI_BIN and os.path.isfile(CLI_BIN))


def _safe_child_env():
    """不把 goodlove 其他供应商的密钥带进 Claude 子进程。

    Claude 自己的订阅凭据可能来自 ~/.claude，也可能由 Claude 专用环境变量提供，
    因此只保留 CLAUDE_*，移除其余常见密钥变量。
    """
    child = os.environ.copy()
    exact = {
        "API_KEY", "OPENROUTER_API_KEY", "GPT_API_KEY", "DEEPSEEK_API_KEY",
        "VAPID_PRIVATE_KEY", "BARK_URL", "APP_TOKEN", "ACCESS_TOKEN",
    }
    for key in list(child):
        upper = key.upper()
        if upper.startswith("CLAUDE_"):
            continue
        if (
            upper in exact
            or upper.endswith("_API_KEY")
            or upper.endswith("_PRIVATE_KEY")
            or upper.endswith("_ACCESS_TOKEN")
        ):
            child.pop(key, None)
    child["NO_COLOR"] = "1"
    return child


def _content_text(content, temp_dir):
    """把 OpenAI 兼容消息块改成 CLI 可读文字；本轮图片落进请求临时目录。"""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return str(content or ""), []
    texts = []
    images = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
            continue
        if block.get("type") != "image_url":
            continue
        image_url = block.get("image_url") or {}
        data_url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
            texts.append("（本轮有一张图片，但服务器没有取得可读的图片数据。）")
            continue
        try:
            header, encoded = data_url.split(",", 1)
            mime = header[5:].split(";", 1)[0]
            suffix = mimetypes.guess_extension(mime) or ".img"
            target = Path(temp_dir) / f"image-{len(images) + 1}{suffix}"
            target.write_bytes(base64.b64decode(encoded, validate=True))
            images.append(str(target))
            texts.append(
                f"（本轮图片保存在 {target.name}。请先使用 Read 查看它，再结合正文回应。）"
            )
        except Exception:
            texts.append("（本轮图片解析失败。请明确承认没有看清，不要假装看过。）")
    return "\n".join(texts), images


def _request_prompt(messages, temp_dir):
    system_parts = []
    conversation = []
    image_paths = []
    for message in messages or []:
        role = str(message.get("role") or "user")
        text, images = _content_text(message.get("content"), temp_dir)
        image_paths.extend(images)
        if role == "system":
            system_parts.append(text)
        else:
            conversation.append({"role": role, "content": text})
    request = {
        "system_instructions": "\n\n".join(system_parts),
        "conversation": conversation,
    }
    return (
        "请按 system_instructions 与 conversation 生成下一条 assistant 回复：\n"
        + json.dumps(request, ensure_ascii=False, separators=(",", ":")),
        image_paths,
    )


def _command(temp_dir, has_images, max_tokens):
    mcp_config = Path(temp_dir) / "mcp.json"
    mcp_config.write_text('{"mcpServers":{}}', encoding="utf-8")
    tools = "Read" if has_images else ""
    return [
        CLI_BIN,
        "-p",
        "--model", CLI_MODEL,
        "--effort", EFFORT,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--no-session-persistence",
        "--safe-mode",
        "--disable-slash-commands",
        "--prompt-suggestions", "false",
        "--permission-mode", "dontAsk",
        "--max-budget-usd", str(MAX_BUDGET_USD),
        "--mcp-config", str(mcp_config),
        "--strict-mcp-config",
        "--tools", tools,
        "--system-prompt",
        _SYSTEM_PROMPT
        + f" 本轮输出上限由 PWA 设为约 {int(max_tokens)} tokens，请服从内容需要且不要灌水。",
    ] + (["--allowedTools", "Read"] if has_images else [])


def _terminate(process):
    if process is None:
        return
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _reader(stream, events):
    try:
        for line in iter(stream.readline, ""):
            events.put(line)
    finally:
        events.put(None)


def _assistant_text(event):
    message = event.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return ""
    return "".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _usage_from_result(result):
    usage = {
        "requested_model": MODEL_ID,
        "returned_model": "",
        "finish_reason": "",
        "cached_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "http_status": 200,
    }
    model_usage = result.get("modelUsage") or result.get("model_usage")
    if isinstance(model_usage, dict) and model_usage:
        for model, item in model_usage.items():
            if not isinstance(item, dict):
                continue
            usage["prompt_tokens"] += int(
                item.get("inputTokens", item.get("input_tokens", 0)) or 0
            )
            usage["prompt_tokens"] += int(
                item.get("cacheReadInputTokens", item.get("cache_read_input_tokens", 0)) or 0
            )
            usage["prompt_tokens"] += int(
                item.get("cacheCreationInputTokens", item.get("cache_creation_input_tokens", 0)) or 0
            )
            usage["cached_tokens"] += int(
                item.get("cacheReadInputTokens", item.get("cache_read_input_tokens", 0)) or 0
            )
            usage["completion_tokens"] += int(
                item.get("outputTokens", item.get("output_tokens", 0)) or 0
            )
            if not usage["returned_model"] or "opus" in str(model).lower():
                usage["returned_model"] = str(model)
    else:
        item = result.get("usage") or {}
        usage["prompt_tokens"] = sum(int(item.get(key, 0) or 0) for key in (
            "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"
        ))
        usage["cached_tokens"] = int(item.get("cache_read_input_tokens", 0) or 0)
        usage["completion_tokens"] = int(item.get("output_tokens", 0) or 0)
        usage["returned_model"] = str(result.get("model") or "")
    usage["finish_reason"] = str(
        result.get("stop_reason")
        or result.get("terminal_reason")
        or result.get("subtype")
        or ("error" if result.get("is_error") else "end_turn")
    )[:120]
    try:
        usage["cost_usd"] = float(result.get("total_cost_usd") or 0)
    except (TypeError, ValueError):
        usage["cost_usd"] = 0.0
    return usage


def stream_completion(messages, max_tokens=4096):
    """逐段返回正文，最后返回与 chat_ai 相同的带外 usage 事件。"""
    started = time.monotonic()
    usage = {"requested_model": MODEL_ID, "http_status": 0}
    if not is_available():
        yield (ERROR_TAG, "Claude 订阅线路还没有在服务器启用，本轮没有偷偷切换别的模型。")
        usage["finish_reason"] = "error:not_configured"
        usage["total_ms"] = int((time.monotonic() - started) * 1000)
        yield (USAGE_TAG, usage)
        return

    process = None
    temp_root = os.environ.get("CLAUDE_EXEC_TMPDIR", "").strip() or None
    try:
        if temp_root:
            os.makedirs(temp_root, mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="goodlove-claude-", dir=temp_root
        ) as temp_dir:
            prompt, images = _request_prompt(messages, temp_dir)
            process = subprocess.Popen(
                _command(temp_dir, bool(images), max_tokens),
                cwd=temp_dir,
                env=_safe_child_env(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            process.stdin.write(prompt)
            process.stdin.close()
            events = queue.Queue()
            threading.Thread(
                target=_reader, args=(process.stdout, events), daemon=True
            ).start()
            deadline = started + TIMEOUT_SECONDS
            emitted = False
            full_candidate = ""
            result_event = {}
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("claude exec timeout")
                try:
                    line = events.get(timeout=min(1.0, remaining))
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                event_type = event.get("type")
                if event_type == "system" and event.get("subtype") == "init":
                    usage["returned_model"] = str(event.get("model") or "")
                elif event_type == "stream_event":
                    inner = event.get("event") or {}
                    delta = inner.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        if not usage.get("first_token_ms"):
                            usage["first_token_ms"] = int(
                                (time.monotonic() - started) * 1000
                            )
                        emitted = True
                        yield str(delta["text"])
                    elif delta.get("type") in ("thinking_delta", "signature_delta"):
                        # 原始思维链永远不下发；只保留协议兼容位。
                        continue
                elif event_type == "assistant":
                    full_candidate = _assistant_text(event) or full_candidate
                elif event_type == "result":
                    result_event = event
            return_code = process.wait(timeout=5)
            if result_event:
                usage.update(_usage_from_result(result_event))
            if return_code != 0 or result_event.get("is_error"):
                usage["http_status"] = 503
                usage["finish_reason"] = usage.get("finish_reason") or "error:claude_exec"
                yield (ERROR_TAG, "Claude 订阅这轮没有接住，服务器没有偷偷换成别的模型。")
            elif not emitted and full_candidate:
                usage["first_token_ms"] = int((time.monotonic() - started) * 1000)
                yield full_candidate
            elif not emitted:
                usage["http_status"] = 503
                usage["finish_reason"] = "error:empty"
                yield (ERROR_TAG, "Claude 订阅这轮没有返回正文，稍后再发一次即可。")
    except TimeoutError:
        _terminate(process)
        usage.update({"http_status": 504, "finish_reason": "error:timeout"})
        yield (ERROR_TAG, "Claude 订阅这轮超时了，后台已经停止这次请求，没有换模型。")
    except Exception as exc:
        _terminate(process)
        usage.update({"http_status": 503, "finish_reason": "error:claude_exec"})
        print(f"[claude-exec] 请求失败：{type(exc).__name__}", flush=True)
        yield (ERROR_TAG, "Claude 订阅线路暂时没有接上，本轮没有偷偷切换别的模型。")
    finally:
        _terminate(process)
        if process is not None:
            for stream in (process.stdout, process.stdin):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
        usage["total_ms"] = int((time.monotonic() - started) * 1000)
        yield (USAGE_TAG, usage)
