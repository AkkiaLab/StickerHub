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
        target_sender: TargetPlatformSender | None,
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

        if not self._target_sender:
            logger.debug("未配置目标平台发送器，跳过飞书转发")
            return

        target = await self._binding_service.get_feishu_target(
            source_platform=asset.source_platform,
            source_user_id=asset.source_user_id,
        )
        if not target:
            logger.info(
                "用户未绑定飞书，跳过飞书转发: user=%s",
                asset.source_user_id,
            )
            return

        normalized = await self._normalizer.normalize(asset)
        await self._target_sender.send(
            normalized,
            target_mode=target.mode,
            target=target.target,
        )
        logger.info(
            "转发成功: source=%s user=%s mode=%s kind=%s mime=%s",
            asset.source_platform,
            asset.source_user_id,
            target.mode,
            normalized.media_kind,
            normalized.mime_type,
        )
