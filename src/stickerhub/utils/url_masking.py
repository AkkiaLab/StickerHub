"""Shared constants and utilities for URL masking to prevent credential leakage in logs."""

from urllib.parse import urlparse

# URL masking constants
PATH_PREFIX_LENGTH = 20
PATH_SUFFIX_LENGTH = 8
PATH_MASK_THRESHOLD = PATH_PREFIX_LENGTH + PATH_SUFFIX_LENGTH


def mask_url(url: str) -> str:
    """
    脱敏 URL 用于日志输出，避免泄露敏感 token。

    仅保留协议、域名（hostname）、路径前 20 个字符和后 8 个字符，中间用 ... 替代。
    不包含 userinfo、端口、query、fragment 等敏感信息。
    """
    try:
        parsed = urlparse(url)

        # 仅在解析结果有明确的协议和主机名时才返回拼接后的 URL
        if not parsed.scheme or not parsed.hostname:
            return "[url_masked]"

        if parsed.path and len(parsed.path) > PATH_MASK_THRESHOLD:
            masked_path = (
                f"{parsed.path[:PATH_PREFIX_LENGTH]}...{parsed.path[-PATH_SUFFIX_LENGTH:]}"
            )
        else:
            masked_path = parsed.path

        # 仅使用 hostname，避免将 userinfo、端口等敏感信息写入日志
        return f"{parsed.scheme}://{parsed.hostname}{masked_path}"
    except (ValueError, TypeError, AttributeError):
        # urlparse 可能抛出 ValueError，或传入 None 导致 TypeError/AttributeError
        return "[url_masked]"
