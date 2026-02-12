import asyncio
import logging
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import ceil

from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Sticker,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stickerhub.core.models import StickerAsset

logger = logging.getLogger(__name__)

AssetHandler = Callable[[StickerAsset], Awaitable[None]]
BindHandler = Callable[[str, str | None], Awaitable[str]]
PackBatchMarkerHandler = Callable[[str, int, int, int, int, str], Awaitable[None]]

PACK_CALLBACK_PREFIX = "send_pack:"
STOP_PACK_CALLBACK_PREFIX = "stop_pack:"
PACK_REQUEST_TTL_SECONDS = 15 * 60
PACK_BATCH_SIZE = 10


@dataclass(slots=True)
class PendingStickerPackRequest:
    telegram_user_id: str
    source_user_id: str
    set_name: str
    original_sticker_unique_id: str
    total_count: int
    created_at: int


@dataclass(slots=True)
class RunningStickerPackTask:
    task_id: str
    telegram_user_id: str
    source_user_id: str
    set_name: str
    origin_chat_id: int
    origin_message_id: int
    cancel_requested: bool = False


def build_telegram_usage_text() -> str:
    return (
        "StickerHub 使用说明：\n"
        "1. 发送 /bind 获取魔法字符串，在另一平台使用 /bind <code> 完成绑定\n"
        "2. 直接发送贴纸/图片/GIF/视频，机器人会转发到飞书\n"
        "3. 发送单个贴纸后，可点击按钮继续发送整个表情包\n"
        "\n"
        "支持命令：\n"
        "/bind [魔法字符串]\n"
        "/help\n"
        "/start"
    )


def get_telegram_bot_commands() -> list[BotCommand]:
    return [
        BotCommand("bind", "绑定账号：/bind 或 /bind <code>"),
        BotCommand("help", "查看使用说明"),
        BotCommand("start", "开始使用并查看说明"),
    ]


def build_telegram_application(
    token: str,
    on_asset: AssetHandler,
    on_bind: BindHandler,
    on_pack_batch_marker: PackBatchMarkerHandler | None = None,
) -> Application:
    application = Application.builder().token(token).build()
    pending_pack_requests: dict[str, PendingStickerPackRequest] = {}
    running_pack_tasks: dict[str, RunningStickerPackTask] = {}

    async def handle_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_user:
            return

        try:
            arg = context.args[0] if context.args else None
            reply = await on_bind(str(update.effective_user.id), arg)
            await update.message.reply_text(reply)
        except Exception as exc:  # noqa: BLE001
            logger.exception("处理 Telegram /bind 失败")
            await update.message.reply_text(f"绑定失败: {exc}")

    async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text(build_telegram_usage_text())

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return

        _cleanup_pending_requests(pending_pack_requests)

        try:
            asset = await _extract_asset(update.message, context)
            if asset is None:
                return

            logger.info(
                "收到 Telegram 素材: user=%s kind=%s mime=%s",
                asset.source_user_id,
                asset.media_kind,
                asset.mime_type,
            )
            await on_asset(asset)

            if update.message.sticker and update.effective_user:
                await _offer_send_pack_button(
                    message=update.message,
                    context=context,
                    effective_user_id=str(update.effective_user.id),
                    pending_pack_requests=pending_pack_requests,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("处理 Telegram 消息失败")
            await update.message.reply_text(f"处理失败: {exc}")

    async def handle_send_pack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        await query.answer()
        _cleanup_pending_requests(pending_pack_requests)

        data = query.data or ""
        if not data.startswith(PACK_CALLBACK_PREFIX):
            return

        token = data[len(PACK_CALLBACK_PREFIX) :]
        request = pending_pack_requests.get(token)
        if request is None:
            await query.edit_message_text("该操作已过期，请重新发送一个贴纸再试。")
            return

        effective_user = update.effective_user
        if not effective_user or str(effective_user.id) != request.telegram_user_id:
            await query.answer("仅发起请求的用户可以点击该按钮", show_alert=True)
            return

        if _has_running_task_for_user(running_pack_tasks, request.telegram_user_id):
            await query.answer(
                "你当前已有一个整包发送任务在运行，请先停止或等待完成",
                show_alert=True,
            )
            return

        if not query.message:
            await query.answer("无法获取消息上下文，请重试", show_alert=True)
            return

        if not isinstance(query.message, Message):
            await query.answer("消息已不可访问，请重新发起任务", show_alert=True)
            return

        effective_chat = update.effective_chat
        if not effective_chat:
            await query.answer("无法获取会话信息，请重试", show_alert=True)
            return

        pending_pack_requests.pop(token, None)

        task_id = secrets.token_hex(6)
        running_task = RunningStickerPackTask(
            task_id=task_id,
            telegram_user_id=request.telegram_user_id,
            source_user_id=request.source_user_id,
            set_name=request.set_name,
            origin_chat_id=effective_chat.id,
            origin_message_id=query.message.message_id,
        )
        running_pack_tasks[task_id] = running_task

        await query.edit_message_text(
            text=(
                f"开始发送表情包《{request.set_name}》...\n"
                f"每批 {PACK_BATCH_SIZE} 个并发发送。\n"
                "可随时点击下方按钮停止任务。"
            ),
            reply_markup=_build_stop_keyboard(task_id),
        )

        context.application.create_task(
            _run_sticker_pack_task(
                context=context,
                request=request,
                running_task=running_task,
                on_asset=on_asset,
                on_pack_batch_marker=on_pack_batch_marker,
                running_pack_tasks=running_pack_tasks,
            )
        )

    async def handle_stop_pack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context

        query = update.callback_query
        if not query:
            return

        data = query.data or ""
        if not data.startswith(STOP_PACK_CALLBACK_PREFIX):
            return

        task_id = data[len(STOP_PACK_CALLBACK_PREFIX) :]
        running_task = running_pack_tasks.get(task_id)
        if running_task is None:
            await query.answer("任务已结束或不存在", show_alert=True)
            return

        effective_user = update.effective_user
        if not effective_user or str(effective_user.id) != running_task.telegram_user_id:
            await query.answer("仅发起任务的用户可以停止", show_alert=True)
            return

        running_task.cancel_requested = True
        await query.answer("已请求停止，当前批次结束后会停止")

    async def handle_unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        if not update.message or not update.message.text:
            return
        await update.message.reply_text(
            f"不支持的命令：{update.message.text}\n\n{build_telegram_usage_text()}"
        )

    async def handle_unsupported_message(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text("暂不支持该消息类型。\n\n" + build_telegram_usage_text())

    message_filter = (
        filters.Sticker.ALL
        | filters.PHOTO
        | filters.ANIMATION
        | filters.VIDEO
        | filters.Document.IMAGE
        | filters.Document.VIDEO
    )

    unsupported_filter = ~message_filter & ~filters.COMMAND

    application.add_handler(CommandHandler("bind", handle_bind))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("start", handle_help))
    application.add_handler(
        CallbackQueryHandler(
            handle_send_pack_callback,
            pattern=rf"^{PACK_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_stop_pack_callback,
            pattern=rf"^{STOP_PACK_CALLBACK_PREFIX}",
        )
    )
    application.add_handler(MessageHandler(message_filter, handle_message))
    application.add_handler(MessageHandler(filters.COMMAND, handle_unknown_command))
    application.add_handler(MessageHandler(unsupported_filter, handle_unsupported_message))
    return application


async def _run_sticker_pack_task(
    context: ContextTypes.DEFAULT_TYPE,
    request: PendingStickerPackRequest,
    running_task: RunningStickerPackTask,
    on_asset: AssetHandler,
    on_pack_batch_marker: PackBatchMarkerHandler | None,
    running_pack_tasks: dict[str, RunningStickerPackTask],
) -> None:
    bot = context.bot

    try:
        sticker_set = await bot.get_sticker_set(request.set_name)
        stickers = [
            sticker
            for sticker in sticker_set.stickers
            if sticker.file_unique_id != request.original_sticker_unique_id
        ]

        if not stickers:
            await _edit_task_message(
                bot=bot,
                running_task=running_task,
                text="该表情包没有额外表情可发送。",
                reply_markup=None,
            )
            return

        total = len(stickers)
        total_batches = ceil(total / PACK_BATCH_SIZE)
        sent = 0
        failed = 0

        logger.info(
            "开始整包发送任务: task=%s user=%s set=%s total=%s",
            running_task.task_id,
            running_task.telegram_user_id,
            request.set_name,
            total,
        )

        for batch_index in range(total_batches):
            if running_task.cancel_requested:
                break

            start = batch_index * PACK_BATCH_SIZE
            end = min(start + PACK_BATCH_SIZE, total)
            batch = stickers[start:end]

            if on_pack_batch_marker:
                await on_pack_batch_marker(
                    request.source_user_id,
                    batch_index + 1,
                    total_batches,
                    start + 1,
                    end,
                    request.set_name,
                )

            batch_sent, batch_failed = await _send_batch_concurrently(
                batch=batch,
                bot=bot,
                source_user_id=request.source_user_id,
                file_prefix=f"pack_{_safe_pack_name(request.set_name)}",
                on_asset=on_asset,
                set_name=request.set_name,
            )
            sent += batch_sent
            failed += batch_failed

            await _edit_task_message(
                bot=bot,
                running_task=running_task,
                text=(
                    f"正在发送表情包《{request.set_name}》\n"
                    f"批次: {batch_index + 1}/{total_batches}\n"
                    f"进度: 成功 {sent} / 失败 {failed} / 总计 {total}"
                ),
                reply_markup=(
                    None
                    if running_task.cancel_requested
                    else _build_stop_keyboard(running_task.task_id)
                ),
            )

        if running_task.cancel_requested:
            await _edit_task_message(
                bot=bot,
                running_task=running_task,
                text=(
                    f"已停止发送表情包《{request.set_name}》\n"
                    f"已完成: 成功 {sent} / 失败 {failed} / 总计 {total}"
                ),
                reply_markup=None,
            )
            logger.info("整包发送任务已停止: task=%s", running_task.task_id)
            return

        await _edit_task_message(
            bot=bot,
            running_task=running_task,
            text=(
                f"表情包《{request.set_name}》发送完成\n"
                f"成功: {sent}，失败: {failed}，总计: {total}"
            ),
            reply_markup=None,
        )
        logger.info(
            "整包发送任务完成: task=%s sent=%s failed=%s",
            running_task.task_id,
            sent,
            failed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("发送整个表情包失败: task=%s", running_task.task_id)
        await _edit_task_message(
            bot=bot,
            running_task=running_task,
            text=f"发送整个表情包失败: {exc}",
            reply_markup=None,
        )
    finally:
        running_pack_tasks.pop(running_task.task_id, None)


async def _send_batch_concurrently(
    batch: list[Sticker],
    bot: Bot,
    source_user_id: str,
    file_prefix: str,
    on_asset: AssetHandler,
    set_name: str,
) -> tuple[int, int]:
    async def _send_single(sticker: Sticker) -> bool:
        try:
            asset = await _build_sticker_asset(
                sticker=sticker,
                bot=bot,
                source_user_id=source_user_id,
                file_prefix=file_prefix,
            )
            await on_asset(asset)
            return True
        except Exception:  # noqa: BLE001
            logger.exception(
                "发送表情包子项失败: set=%s user=%s sticker=%s",
                set_name,
                source_user_id,
                sticker.file_unique_id,
            )
            return False

    results = await asyncio.gather(*[_send_single(sticker) for sticker in batch])
    sent = sum(1 for ok in results if ok)
    failed = len(results) - sent
    return sent, failed


def _has_running_task_for_user(
    running_pack_tasks: dict[str, RunningStickerPackTask],
    telegram_user_id: str,
) -> bool:
    return any(task.telegram_user_id == telegram_user_id for task in running_pack_tasks.values())


async def _edit_task_message(
    bot: Bot,
    running_task: RunningStickerPackTask,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    await bot.edit_message_text(
        chat_id=running_task.origin_chat_id,
        message_id=running_task.origin_message_id,
        text=text,
        reply_markup=reply_markup,
    )


def _build_stop_keyboard(task_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="停止发送",
                    callback_data=f"{STOP_PACK_CALLBACK_PREFIX}{task_id}",
                )
            ]
        ]
    )


async def _offer_send_pack_button(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    effective_user_id: str,
    pending_pack_requests: dict[str, PendingStickerPackRequest],
) -> None:
    sticker = message.sticker
    if not sticker:
        return

    set_name = sticker.set_name
    if not set_name:
        logger.info("当前贴纸不属于可枚举表情包，跳过整包提示")
        return

    try:
        sticker_set = await context.bot.get_sticker_set(set_name)
    except Exception:  # noqa: BLE001
        logger.exception("获取贴纸包失败: set_name=%s", set_name)
        return

    total = len(sticker_set.stickers)
    remaining = max(total - 1, 0)
    if remaining == 0:
        await message.reply_text("当前贴纸已发送。该表情包没有其它可发送表情。")
        return

    token = secrets.token_hex(6)
    pending_pack_requests[token] = PendingStickerPackRequest(
        telegram_user_id=effective_user_id,
        source_user_id=effective_user_id,
        set_name=set_name,
        original_sticker_unique_id=sticker.file_unique_id,
        total_count=total,
        created_at=int(time.time()),
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=f"发送整个表情包（共 {total} 个）",
                    callback_data=f"{PACK_CALLBACK_PREFIX}{token}",
                )
            ]
        ]
    )

    await message.reply_text(
        (
            "当前表情已发送到飞书。\n"
            f"是否继续发送整个表情包《{set_name}》？\n"
            f"将额外发送 {remaining} 个（每批 {PACK_BATCH_SIZE} 个并发）。"
        ),
        reply_markup=keyboard,
    )

    logger.info(
        "已创建整包发送请求: token=%s user=%s set=%s total=%s",
        token,
        effective_user_id,
        set_name,
        total,
    )


async def _extract_asset(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
) -> StickerAsset | None:
    bot = context.bot
    source_user_id = str(message.from_user.id) if message.from_user else ""

    if message.sticker:
        return await _build_sticker_asset(
            sticker=message.sticker,
            bot=bot,
            source_user_id=source_user_id,
            file_prefix="sticker",
        )

    if message.photo:
        largest = message.photo[-1]
        tg_file = await bot.get_file(largest.file_id)
        content = bytes(await tg_file.download_as_bytearray())
        return StickerAsset(
            source_platform="telegram",
            source_user_id=source_user_id,
            media_kind="image",
            mime_type="image/jpeg",
            file_name=f"photo_{largest.file_unique_id}.jpg",
            content=content,
            is_animated=False,
        )

    if message.animation:
        animation = message.animation
        tg_file = await bot.get_file(animation.file_id)
        content = bytes(await tg_file.download_as_bytearray())
        mime = animation.mime_type or "video/mp4"
        extension = _extension_from_mime(mime)
        return StickerAsset(
            source_platform="telegram",
            source_user_id=source_user_id,
            media_kind="gif" if mime == "image/gif" else "video",
            mime_type=mime,
            file_name=animation.file_name or f"animation_{animation.file_unique_id}{extension}",
            content=content,
            is_animated=True,
        )

    if message.video:
        video = message.video
        tg_file = await bot.get_file(video.file_id)
        content = bytes(await tg_file.download_as_bytearray())
        mime = video.mime_type or "video/mp4"
        extension = _extension_from_mime(mime)
        return StickerAsset(
            source_platform="telegram",
            source_user_id=source_user_id,
            media_kind="video",
            mime_type=mime,
            file_name=video.file_name or f"video_{video.file_unique_id}{extension}",
            content=content,
            is_animated=True,
        )

    if message.document:
        doc = message.document
        if not doc.mime_type:
            return None

        mime = doc.mime_type
        if not (mime.startswith("image/") or mime.startswith("video/")):
            return None

        tg_file = await bot.get_file(doc.file_id)
        content = bytes(await tg_file.download_as_bytearray())
        media_kind = (
            "video" if mime.startswith("video/") else ("gif" if mime == "image/gif" else "image")
        )
        extension = _extension_from_mime(mime)
        name = doc.file_name or f"doc_{doc.file_unique_id}{extension}"

        return StickerAsset(
            source_platform="telegram",
            source_user_id=source_user_id,
            media_kind=media_kind,
            mime_type=mime,
            file_name=name,
            content=content,
            is_animated=media_kind in {"video", "gif"},
        )

    return None


async def _build_sticker_asset(
    sticker: Sticker,
    bot: Bot,
    source_user_id: str,
    file_prefix: str,
) -> StickerAsset:
    tg_file = await bot.get_file(sticker.file_id)
    content = bytes(await tg_file.download_as_bytearray())
    mime = _detect_sticker_mime(sticker)
    extension = _extension_from_mime(mime)

    return StickerAsset(
        source_platform="telegram",
        source_user_id=source_user_id,
        media_kind="sticker",
        mime_type=mime,
        file_name=f"{file_prefix}_{sticker.file_unique_id}{extension}",
        content=content,
        is_animated=bool(sticker.is_animated or sticker.is_video),
    )


def _extension_from_mime(mime: str) -> str:
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "application/x-tgsticker": ".tgs",
    }
    return mapping.get(mime.lower(), ".bin")


def _detect_sticker_mime(sticker: Sticker) -> str:
    """
    PTB 的 Sticker 对象在不同版本中字段存在差异：
    - 新版本可能没有 sticker.mime_type
    - 需要根据 is_animated / is_video 推断真实格式
    """
    try:
        legacy_mime = sticker.mime_type  # type: ignore[attr-defined]
    except AttributeError:
        legacy_mime = None

    if isinstance(legacy_mime, str) and legacy_mime.strip():
        return legacy_mime.strip().lower()

    if sticker.is_video:
        return "video/webm"
    if sticker.is_animated:
        return "application/x-tgsticker"
    return "image/webp"


def _cleanup_pending_requests(pending_pack_requests: dict[str, PendingStickerPackRequest]) -> None:
    now = int(time.time())
    expired = [
        token
        for token, req in pending_pack_requests.items()
        if now - req.created_at > PACK_REQUEST_TTL_SECONDS
    ]
    for token in expired:
        pending_pack_requests.pop(token, None)


def _safe_pack_name(set_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", set_name)
