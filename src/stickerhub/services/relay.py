import logging

from stickerhub.core.models import StickerAsset
from stickerhub.core.ports import MediaNormalizer, TargetPlatformSender
from stickerhub.services.binding import BindingService

logger = logging.getLogger(__name__)


class RelayStickerUseCase:
    """编排来源平台素材 -> 归一化 -> 目标平台发送。"""

    def __init__(
        self,
        normalizer: MediaNormalizer,
        target_sender: TargetPlatformSender,
        binding_service: BindingService,
    ) -> None:
        self._normalizer = normalizer
        self._target_sender = target_sender
        self._binding_service = binding_service

    async def relay(self, asset: StickerAsset) -> None:
        logger.debug(
            "开始转发素材: source=%s user=%s kind=%s mime=%s",
            asset.source_platform,
            asset.source_user_id,
            asset.media_kind,
            asset.mime_type,
        )
        target_user_id = await self._binding_service.get_target_user_id(
            source_platform=asset.source_platform,
            source_user_id=asset.source_user_id,
            target_platform="feishu",
        )
        if not target_user_id:
            raise RuntimeError("当前 Telegram 账号未绑定飞书。请先执行 /bind 完成跨平台绑定")

        normalized = await self._normalizer.normalize(asset)
        await self._target_sender.send(normalized, target_user_id=target_user_id)
        logger.info(
            "转发成功: source=%s user=%s kind=%s mime=%s",
            asset.source_platform,
            asset.source_user_id,
            normalized.media_kind,
            normalized.mime_type,
        )
