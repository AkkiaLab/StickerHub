import time
from types import SimpleNamespace

from stickerhub.adapters.telegram_source import (
    PendingStickerPackRequest,
    RunningStickerPackTask,
    _cleanup_pending_requests,
    _detect_sticker_mime,
    _has_running_task_for_user,
)


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
