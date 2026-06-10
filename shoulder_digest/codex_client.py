from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CodexError(RuntimeError):
    pass


class CodexUnavailableError(CodexError):
    pass


@dataclass(slots=True)
class CodexTurnResult:
    text: str
    raw_messages: list[dict[str, Any]]


CODEX_SAFETY_INSTRUCTIONS = (
    "This thread is used by a local PubMed digest app. Do not inspect local files, "
    "run shell commands, edit files, request permissions, or use external data. "
    "Use only the user-provided PubMed JSON/content. Return the requested text or "
    "generate the requested image directly."
)


class CodexAppServerClient:
    def __init__(
        self,
        codex_bin: str = "codex",
        model: str = "",
        cwd: Path | None = None,
        timeout_seconds: int = 600,
    ):
        self.codex_bin = codex_bin
        self.model = model
        self.cwd = cwd or Path.cwd()
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return shutil.which(self.codex_bin) is not None or Path(self.codex_bin).exists()

    def run_turn(self, prompt: str) -> CodexTurnResult:
        if not self.available():
            raise CodexUnavailableError(f"Codex CLI not found: {self.codex_bin}")
        proc = subprocess.Popen(
            [self.codex_bin, "app-server", "--listen", "stdio://"],
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        stderr_lines: list[str] = []
        stdout_lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=_read_stdout, args=(proc.stdout, stdout_lines), daemon=True).start()
        threading.Thread(target=_drain_stderr, args=(proc.stderr, stderr_lines), daemon=True).start()

        next_id = 1
        responses: dict[int, dict[str, Any]] = {}
        messages: list[dict[str, Any]] = []
        text_parts: list[str] = []
        completed_agent_texts: list[str] = []

        def send(message: dict[str, Any]) -> None:
            proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            proc.stdin.flush()

        def request(method: str, params: dict[str, Any]) -> int:
            nonlocal next_id
            request_id = next_id
            next_id += 1
            send({"id": request_id, "method": method, "params": params})
            return request_id

        init_id = request(
            "initialize",
            {
                "clientInfo": {
                    "name": "shoulder_digest",
                    "title": "Shoulder PubMed Digest",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        send({"method": "initialized", "params": {}})
        thread_id_request = request("thread/start", self._thread_start_params())

        deadline = time.monotonic() + self.timeout_seconds
        thread_id = ""
        turn_started = False
        turn_completed = False

        while time.monotonic() < deadline:
            try:
                line = stdout_lines.get(timeout=min(0.5, max(0.05, deadline - time.monotonic())))
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            messages.append(message)

            message_id = message.get("id")
            if message_id is not None and ("result" in message or "error" in message):
                responses[int(message_id)] = message
                if message_id == init_id and "error" in message:
                    raise CodexError(message["error"].get("message", "initialize failed"))
                if message_id == thread_id_request:
                    if "error" in message:
                        raise CodexError(message["error"].get("message", "thread/start failed"))
                    thread_id = _find_thread_id(message.get("result", {}))
                    if not thread_id:
                        raise CodexError("thread/start did not return a thread id")
                    request(
                        "turn/start",
                        self._turn_start_params(thread_id, prompt),
                    )
                    turn_started = True
                continue

            if message_id is not None and message.get("method"):
                response = _server_request_response(message.get("method", ""))
                if response is None:
                    send(
                        {
                            "id": message_id,
                            "error": {
                                "code": -32001,
                                "message": f"Unsupported app-server request: {message.get('method', '')}",
                            },
                        }
                    )
                else:
                    send({"id": message_id, "result": response})
                continue

            method = message.get("method", "")
            params = message.get("params", {})
            if method in {"item/agentMessage/delta", "item/delta"}:
                delta = params.get("delta") or params.get("textDelta") or params.get("text")
                if isinstance(delta, str):
                    text_parts.append(delta)
            elif method == "item/completed":
                extracted = _extract_agent_text(params)
                if extracted:
                    completed_agent_texts.append(extracted)
            elif method == "turn/completed":
                turn_completed = True
                break

        _terminate(proc)
        if not turn_started:
            raise CodexError("Codex turn did not start")
        if not turn_completed:
            stderr_tail = "\n".join(stderr_lines[-20:])
            raise CodexError(f"Codex turn timed out or closed early. {stderr_tail}".strip())
        final_text = "\n".join(completed_agent_texts).strip() if completed_agent_texts else "".join(text_parts).strip()
        return CodexTurnResult(text=_dedupe_text(final_text), raw_messages=messages)

    def _thread_start_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "approvalPolicy": "on-request",
            "cwd": str(self.cwd),
            "developerInstructions": CODEX_SAFETY_INSTRUCTIONS,
            "ephemeral": True,
            "sandbox": "read-only",
        }
        if self.model:
            params["model"] = self.model
        return params

    def _turn_start_params(self, thread_id: str, prompt: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": str(self.cwd),
            "approvalPolicy": "on-request",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        }
        if self.model:
            params["model"] = self.model
        return params


def _read_stdout(stream: Any, lines: queue.Queue[str]) -> None:
    for line in stream:
        lines.put(line)


def _drain_stderr(stream: Any, lines: list[str]) -> None:
    if stream is None:
        return
    for line in stream:
        lines.append(line.rstrip())


def _terminate(proc: subprocess.Popen[str]) -> None:
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()


def _server_request_response(method: str) -> dict[str, Any] | None:
    if method in {"item/commandExecution/requestApproval"}:
        return {"decision": "decline"}
    if method in {"item/fileChange/requestApproval"}:
        return {"decision": "decline"}
    if method in {"execCommandApproval", "applyPatchApproval"}:
        return {"decision": "denied"}
    if method == "item/permissions/requestApproval":
        return {
            "permissions": {"fileSystem": None, "network": None},
            "scope": "turn",
            "strictAutoReview": True,
        }
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    if method == "item/tool/requestUserInput":
        return {"answers": {}}
    if method == "item/tool/call":
        return {
            "success": False,
            "contentItems": [
                {
                    "type": "inputText",
                    "text": "Dynamic client-side tools are disabled in shoulder_digest.",
                }
            ],
        }
    return None


def _find_thread_id(result: Any) -> str:
    if isinstance(result, dict):
        thread = result.get("thread")
        if isinstance(thread, dict) and isinstance(thread.get("id"), str):
            return thread["id"]
        if isinstance(result.get("threadId"), str):
            return result["threadId"]
        if isinstance(result.get("id"), str):
            return result["id"]
    return ""


def _extract_agent_text(params: Any) -> str:
    if not isinstance(params, dict):
        return ""
    item = params.get("item")
    if not isinstance(item, dict) or item.get("type") != "agentMessage":
        return ""
    text = item.get("text")
    return text if isinstance(text, str) else ""


def _dedupe_text(text: str) -> str:
    if not text:
        return ""
    half = len(text) // 2
    if len(text) % 2 == 0 and text[:half] == text[half:]:
        return text[:half]
    return text
