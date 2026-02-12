import asyncio
import logging
import os
import tempfile
from pathlib import Path

from stickerhub.core.models import StickerAsset

logger = logging.getLogger(__name__)

# ffmpeg filter_complex：保留透明背景并生成调色板渲染 GIF。
# 先将输入统一为 rgba、固定帧率与尺寸，再 split 为两路：
# 一路生成带透明保留的调色板，另一路套用调色板输出 GIF。
_GIF_TRANSPARENT_FILTER = (
    "[0:v]format=rgba,fps=15,scale=512:-1:flags=lanczos,split[s0][s1];"
    "[s0]palettegen=stats_mode=diff:reserve_transparent=on[p];"
    "[s1][p]paletteuse=dither=bayer:bayer_scale=5:alpha_threshold=128"
)


class UnsupportedMediaError(Exception):
    """不支持的媒体格式。"""


class FfmpegMediaNormalizer:
    """将 Telegram 媒体归一化为飞书可稳定发送的格式。"""

    async def normalize(self, asset: StickerAsset) -> StickerAsset:
        mime = asset.mime_type.lower()
        logger.debug(
            "开始归一化: file=%s kind=%s mime=%s animated=%s",
            asset.file_name,
            asset.media_kind,
            asset.mime_type,
            asset.is_animated,
        )

        if mime == "application/x-tgsticker":
            logger.info("检测到 TGS 贴纸，转换为 GIF: %s", asset.file_name)
            return await self._convert_tgs_to_gif(asset)

        if asset.media_kind == "video" or mime.startswith("video/"):
            logger.info("检测到视频素材，转换为 GIF: %s", asset.file_name)
            return await self._convert_to_gif(asset)

        if asset.media_kind == "gif" and mime == "image/gif":
            return asset

        if mime in {"image/png", "image/jpeg", "image/jpg", "image/gif"}:
            return asset

        if mime in {"image/webp", "application/webp"}:
            logger.info("检测到 WebP 素材，转换为 PNG: %s", asset.file_name)
            return await self._convert_to_png(asset)

        if asset.is_animated:
            return await self._convert_to_gif(asset)

        logger.info("未知 mime 类型，尝试原样发送: %s", asset.mime_type)
        return asset

    async def _convert_tgs_to_gif(self, asset: StickerAsset) -> StickerAsset:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tgs") as in_file:
            in_file.write(asset.content)
            in_path = Path(in_file.name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".gif") as out_file:
            out_path = Path(out_file.name)

        try:
            try:
                await _run_command(
                    ["lottie_convert.py", str(in_path), str(out_path)],
                    "lottie_convert.py TGS 转 GIF",
                )
            except UnsupportedMediaError as lottie_error:
                logger.warning("lottie_convert.py 转换失败，回退到 ffmpeg: %s", lottie_error)
                await _run_ffmpeg(
                    [
                        "-i",
                        str(in_path),
                        "-filter_complex",
                        _GIF_TRANSPARENT_FILTER,
                        "-loop",
                        "0",
                        str(out_path),
                    ]
                )

            content = out_path.read_bytes()
            return StickerAsset(
                source_platform=asset.source_platform,
                source_user_id=asset.source_user_id,
                media_kind="gif",
                mime_type="image/gif",
                file_name=f"{Path(asset.file_name).stem}.gif",
                content=content,
                is_animated=True,
            )
        finally:
            _safe_unlink(in_path)
            _safe_unlink(out_path)

    async def _convert_to_gif(self, asset: StickerAsset) -> StickerAsset:
        in_suffix = _suffix_from_filename_or_mime(asset.file_name, asset.mime_type, default=".bin")
        with tempfile.NamedTemporaryFile(delete=False, suffix=in_suffix) as in_file:
            in_file.write(asset.content)
            in_path = Path(in_file.name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".gif") as out_file:
            out_path = Path(out_file.name)

        try:
            # 对 webm (VP9+alpha) 显式指定 libvpx-vp9 解码器以确保 alpha 通道被解码
            input_args: list[str] = []
            if in_suffix == ".webm":
                input_args = ["-c:v", "libvpx-vp9"]

            await _run_ffmpeg(
                [
                    *input_args,
                    "-i",
                    str(in_path),
                    "-filter_complex",
                    _GIF_TRANSPARENT_FILTER,
                    "-loop",
                    "0",
                    str(out_path),
                ]
            )
            content = out_path.read_bytes()
            return StickerAsset(
                source_platform=asset.source_platform,
                source_user_id=asset.source_user_id,
                media_kind="gif",
                mime_type="image/gif",
                file_name=f"{Path(asset.file_name).stem}.gif",
                content=content,
                is_animated=True,
            )
        finally:
            _safe_unlink(in_path)
            _safe_unlink(out_path)

    async def _convert_to_png(self, asset: StickerAsset) -> StickerAsset:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webp") as in_file:
            in_file.write(asset.content)
            in_path = Path(in_file.name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as out_file:
            out_path = Path(out_file.name)

        try:
            await _run_ffmpeg(["-i", str(in_path), "-pix_fmt", "rgba", str(out_path)])
            content = out_path.read_bytes()
            return StickerAsset(
                source_platform=asset.source_platform,
                source_user_id=asset.source_user_id,
                media_kind="image",
                mime_type="image/png",
                file_name=f"{Path(asset.file_name).stem}.png",
                content=content,
                is_animated=False,
            )
        finally:
            _safe_unlink(in_path)
            _safe_unlink(out_path)


async def _run_ffmpeg(args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="ignore").strip()
        raise UnsupportedMediaError(f"ffmpeg 转换失败: {error_text}")


async def _run_command(args: list[str], action_name: str) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise UnsupportedMediaError(f"{action_name}失败: 缺少命令 {args[0]}") from exc

    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise UnsupportedMediaError(
            f"{action_name}失败: {stderr.decode('utf-8', errors='ignore').strip()}"
        )


def _suffix_from_filename_or_mime(file_name: str, mime_type: str, default: str) -> str:
    suffix = Path(file_name).suffix
    if suffix:
        return suffix

    mapping = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }
    return mapping.get(mime_type.lower(), default)


def _safe_unlink(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
