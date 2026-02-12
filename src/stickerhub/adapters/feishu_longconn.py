import asyncio
import json
import logging
import re
import threading
from collections.abc import Awaitable, Callable

import lark_oapi as lark

from stickerhub.adapters.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

BindHandler = Callable[[str, str | None], Awaitable[str]]


class FeishuLongConnectionReceiver:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        feishu_sender: FeishuSender,
        on_bind: BindHandler,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._feishu_sender = feishu_sender
        self._on_bind = on_bind

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        worker = threading.Thread(
            target=self._run_blocking,
            args=(loop,),
            name="feishu-longconn",
            daemon=True,
        )
        worker.start()
        await asyncio.Event().wait()

    def _run_blocking(self, loop: asyncio.AbstractEventLoop) -> None:
        dispatcher = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(lambda data: self._handle_message_event(data, loop))
            .build()
        )

        client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=dispatcher,
            log_level=lark.LogLevel.INFO,
        )
        client.start()

    def _handle_message_event(self, data: object, loop: asyncio.AbstractEventLoop) -> None:
        event = _obj_get(data, "event")
        message = _obj_get(event, "message")
        sender = _obj_get(event, "sender")
        chat_id = _obj_get(message, "chat_id")

        sender_type = _obj_get(sender, "sender_type")
        if sender_type and sender_type != "user":
            return

        sender_id = _obj_get(sender, "sender_id")
        open_id = _obj_get(sender_id, "open_id")
        if not open_id:
            logger.info("飞书事件忽略：未获取到 sender.open_id")
            return

        message_type = _obj_get(message, "message_type")
        if message_type != "text":
            self._schedule_help_reply(
                loop=loop,
                open_id=str(open_id),
                chat_id=str(chat_id) if chat_id else None,
                reason="暂不支持该消息类型",
            )
            return

        content_raw = _obj_get(message, "content")
        text = _extract_text(content_raw)
        matched, bind_arg = _parse_bind_command(text)
        if not matched:
            if text.strip().startswith("/"):
                self._schedule_help_reply(
                    loop=loop,
                    open_id=str(open_id),
                    chat_id=str(chat_id) if chat_id else None,
                    reason=f"不支持的命令：{text.strip()}",
                )
            return

        logger.info("收到飞书 /bind 命令: open_id=%s chat_id=%s arg=%s", open_id, chat_id, bind_arg)

        async def _process_bind() -> None:
            try:
                reply = await self._on_bind(str(open_id), bind_arg)
            except Exception as exc:  # noqa: BLE001
                logger.exception("处理飞书 /bind 失败")
                reply = f"绑定失败: {exc}"

            # 优先回发到原会话，保证群聊与私聊场景都能看到回复。
            if chat_id:
                await self._feishu_sender.send_text(
                    text=reply,
                    receive_id=str(chat_id),
                    receive_id_type="chat_id",
                )
            else:
                await self._feishu_sender.send_text(
                    text=reply,
                    receive_id=str(open_id),
                    receive_id_type="open_id",
                )

        future = asyncio.run_coroutine_threadsafe(_process_bind(), loop)
        try:
            future.result(timeout=30)
        except Exception:  # noqa: BLE001
            logger.exception("飞书 /bind 异步处理失败")

    def _schedule_help_reply(
        self,
        loop: asyncio.AbstractEventLoop,
        open_id: str,
        chat_id: str | None,
        reason: str,
    ) -> None:
        async def _send_help() -> None:
            text = (
                f"{reason}\n\n"
                "StickerHub 使用说明：\n"
                "1. 发送 /bind 获取魔法字符串\n"
                "2. 在另一平台发送 /bind <code> 完成绑定\n"
                "3. Telegram 发送贴纸/图片/GIF/视频将自动转发到飞书"
            )
            if chat_id:
                await self._feishu_sender.send_text(
                    text=text,
                    receive_id=chat_id,
                    receive_id_type="chat_id",
                )
            else:
                await self._feishu_sender.send_text(
                    text=text,
                    receive_id=open_id,
                    receive_id_type="open_id",
                )

        future = asyncio.run_coroutine_threadsafe(_send_help(), loop)
        try:
            future.result(timeout=30)
        except Exception:  # noqa: BLE001
            logger.exception("飞书帮助消息发送失败")


def _extract_text(content_raw: object) -> str:
    if isinstance(content_raw, str):
        try:
            payload = json.loads(content_raw)
        except json.JSONDecodeError:
            return ""
        return str(payload.get("text") or "").strip()

    if isinstance(content_raw, dict):
        return str(content_raw.get("text") or "").strip()

    return ""


def _obj_get(obj: object, key: str) -> object:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _parse_bind_command(text: str) -> tuple[bool, str | None]:
    """
    支持：
    - /bind
    - /bind CODE
    - @机器人 /bind CODE
    """
    if not text:
        return False, None

    match = re.search(r"(?<!\S)/bind(?:\s+([A-Za-z0-9]+))?", text)
    if not match:
        return False, None

    arg = match.group(1)
    return True, (arg.strip() if arg else None)
