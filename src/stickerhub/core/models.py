from dataclasses import dataclass
from typing import Literal

MediaKind = Literal["sticker", "image", "gif", "video"]


@dataclass(slots=True)
class StickerAsset:
    source_platform: str
    source_user_id: str
    media_kind: MediaKind
    mime_type: str
    file_name: str
    content: bytes
    is_animated: bool = False
