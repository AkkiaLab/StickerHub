import asyncio
import time
from types import SimpleNamespace

from stickerhub.adapters.telegram_source import (
    BIND_MODE_CALLBACK_PREFIX,
    PACK_CALLBACK_PREFIX,
    PendingStickerPackRequest,
    RunningStickerPackTask,
    _cleanup_pending_requests,
    _deduplicate_filename,
    _detect_sticker_mime,
    _has_running_task_for_user,
    _parse_bind_mode_callback_data,
    _parse_pack_callback_data,
    _send_single_sticker_reply,
)
from stickerhub.core.models import StickerAsset


def test_detect_sticker_mime_prefers_legacy_mime_attr() -> None:
    sticker = SimpleNamespace(mime_type="image/webp", is_animated=True, is_video=True)
    assert _detect_sticker_mime(sticker) == "image/webp"


def test_detect_sticker_mime_video_when_no_legacy_mime() -> None:
    sticker = SimpleNamespace(is_animated=False, is_video=True)
    assert _detect_sticker_mime(sticker) == "video/webm"


def test_detect_sticker_mime_animated_when_no_legacy_mime() -> None:
    sticker = SimpleNamespace(is_animated=True, is_video=False)
    assert _detect_sticker_mime(sticker) == "application/x-tgsticker"


def test_detect_sticker_mime_static_when_no_legacy_mime() -> None:
    sticker = SimpleNamespace(is_animated=False, is_video=False)
    assert _detect_sticker_mime(sticker) == "image/webp"


def test_has_running_task_for_user() -> None:
    running = {
        "t1": RunningStickerPackTask(
            task_id="t1",
            telegram_user_id="100",
            source_user_id="100",
            set_name="pack_1",
            origin_chat_id=1,
            origin_message_id=1,
        )
    }
    assert _has_running_task_for_user(running, "100")
    assert not _has_running_task_for_user(running, "200")


def test_cleanup_pending_requests_removes_expired_only() -> None:
    now = int(time.time())
    pending = {
        "expired": PendingStickerPackRequest(
            telegram_user_id="u1",
            source_user_id="u1",
            set_name="a",
            original_sticker_unique_id="x",
            total_count=10,
            created_at=now - 3600,
        ),
        "fresh": PendingStickerPackRequest(
            telegram_user_id="u2",
            source_user_id="u2",
            set_name="b",
            original_sticker_unique_id="y",
            total_count=10,
            created_at=now,
        ),
    }
    _cleanup_pending_requests(pending)
    assert "expired" not in pending
    assert "fresh" in pending


class TestParsePackCallbackData:
    def test_valid_feishu_mode(self) -> None:
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}feishu:abc123")
        assert result == ("feishu", "abc123")

    def test_valid_zip_mode(self) -> None:
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}zip:def456")
        assert result == ("zip", "def456")

    def test_valid_photos_mode(self) -> None:
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}photos:ghi789")
        assert result == ("photos", "ghi789")

    def test_invalid_prefix(self) -> None:
        result = _parse_pack_callback_data("wrong_prefix:feishu:abc")
        assert result is None

    def test_unknown_mode(self) -> None:
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}unknown:abc")
        assert result is None

    def test_missing_token(self) -> None:
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}feishu")
        assert result is None

    def test_empty_string(self) -> None:
        result = _parse_pack_callback_data("")
        assert result is None

    def test_token_with_colon(self) -> None:
        """token 本身包含冒号时应正确分割。"""
        result = _parse_pack_callback_data(f"{PACK_CALLBACK_PREFIX}zip:token:with:colons")
        assert result == ("zip", "token:with:colons")


class TestParseBindModeCallbackData:
    def test_valid_bot_mode(self) -> None:
        result = _parse_bind_mode_callback_data(f"{BIND_MODE_CALLBACK_PREFIX}bot:123")
        assert result == ("bot", "123")

    def test_valid_webhook_mode(self) -> None:
        result = _parse_bind_mode_callback_data(f"{BIND_MODE_CALLBACK_PREFIX}webhook:456")
        assert result == ("webhook", "456")

    def test_invalid_prefix(self) -> None:
        assert _parse_bind_mode_callback_data("wrong:bot:123") is None

    def test_invalid_mode(self) -> None:
        assert _parse_bind_mode_callback_data(f"{BIND_MODE_CALLBACK_PREFIX}unknown:123") is None

    def test_missing_user_id(self) -> None:
        assert _parse_bind_mode_callback_data(f"{BIND_MODE_CALLBACK_PREFIX}bot:") is None


class TestDeduplicateFilename:
    def test_no_conflict(self) -> None:
        assert _deduplicate_filename("sticker.png", set()) == "sticker.png"

    def test_single_conflict(self) -> None:
        seen = {"sticker.png"}
        assert _deduplicate_filename("sticker.png", seen) == "sticker_1.png"

    def test_multiple_conflicts(self) -> None:
        seen = {"sticker.png", "sticker_1.png"}
        assert _deduplicate_filename("sticker.png", seen) == "sticker_2.png"

    def test_no_extension(self) -> None:
        seen = {"sticker"}
        assert _deduplicate_filename("sticker", seen) == "sticker_1"


def test_send_single_sticker_reply_animated_uses_document_not_animation() -> None:
    class DummyMessage:
        def __init__(self) -> None:
            self.animation_called = False
            self.document_called = False

        async def reply_animation(self, *args: object, **kwargs: object) -> None:
            self.animation_called = True

        async def reply_document(self, *args: object, **kwargs: object) -> None:
            self.document_called = True

    message = DummyMessage()
    asset = StickerAsset(
        source_platform="telegram",
        source_user_id="u1",
        media_kind="gif",
        mime_type="image/gif",
        file_name="demo.gif",
        content=b"gif-bytes",
        is_animated=True,
    )

    asyncio.run(_send_single_sticker_reply(message=message, normalized=asset))

    assert message.document_called is True
    assert message.animation_called is False
