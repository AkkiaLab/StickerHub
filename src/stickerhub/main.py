import asyncio
import logging
from typing import Any

from stickerhub.adapters.feishu_longconn import FeishuLongConnectionReceiver
from stickerhub.adapters.feishu_sender import FeishuSender
from stickerhub.adapters.telegram_source import (
    build_telegram_application,
    get_telegram_bot_commands,
)
from stickerhub.config import Settings
from stickerhub.services.binding import BindingService, BindingStore
from stickerhub.services.media_converter import FfmpegMediaNormalizer
from stickerhub.services.relay import RelayStickerUseCase
from stickerhub.utils.logging import setup_logging


async def async_main() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    logger = logging.getLogger(__name__)

    binding_service = BindingService(
        store=BindingStore(settings.binding_db_path),
        magic_ttl_seconds=settings.bind_magic_ttl_seconds,
    )
    await binding_service.initialize()

    normalizer = FfmpegMediaNormalizer()
    feishu_sender = FeishuSender(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
    )
    relay_use_case = RelayStickerUseCase(
        normalizer=normalizer,
        target_sender=feishu_sender,
        binding_service=binding_service,
    )

    async def on_pack_batch_marker(
        source_user_id: str,
        batch_no: int,
        total_batches: int,
        start_index: int,
        end_index: int,
        set_name: str,
    ) -> None:
        target_user_id = await binding_service.get_target_user_id(
            source_platform="telegram",
            source_user_id=source_user_id,
            target_platform="feishu",
        )
        if not target_user_id:
            raise RuntimeError("当前 Telegram 账号未绑定飞书。请先执行 /bind 完成跨平台绑定")

        await feishu_sender.send_text(
            text=(
                f"—— 表情包《{set_name}》批次 {batch_no}/{total_batches} "
                f"（第 {start_index}-{end_index} 个） ——"
            ),
            receive_id=target_user_id,
            receive_id_type="open_id",
        )

    telegram_app = build_telegram_application(
        token=settings.telegram_bot_api_token,
        on_asset=relay_use_case.relay,
        on_bind=lambda user_id, arg: binding_service.handle_bind_command("telegram", user_id, arg),
        on_pack_batch_marker=on_pack_batch_marker,
    )

    feishu_receiver = FeishuLongConnectionReceiver(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        feishu_sender=feishu_sender,
        on_bind=lambda open_id, arg: binding_service.handle_bind_command("feishu", open_id, arg),
    )

    logger.info("StickerHub 启动成功，开始监听 Telegram 与飞书长连接事件")

    await asyncio.gather(
        _run_telegram_polling(telegram_app),
        feishu_receiver.run(),
    )


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("收到中断信号，StickerHub 正在退出")


async def _run_telegram_polling(application: Any) -> None:
    await application.initialize()
    await application.start()
    await _register_telegram_commands(application)
    await application.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


async def _register_telegram_commands(application: Any) -> None:
    logger = logging.getLogger(__name__)
    try:
        await application.bot.set_my_commands(get_telegram_bot_commands())
        logger.info("Telegram 命令已注册: /bind /help /start")
    except Exception:  # noqa: BLE001
        logger.exception("Telegram 命令注册失败")


if __name__ == "__main__":
    main()
