from typing import Protocol

from stickerhub.core.models import StickerAsset


class MediaNormalizer(Protocol):
    async def normalize(self, asset: StickerAsset) -> StickerAsset:
        """将来源素材转换为目标平台可接收的统一格式。"""


class TargetPlatformSender(Protocol):
    async def send(self, asset: StickerAsset, target_user_id: str) -> None:
        """将素材发送到目标平台。"""
