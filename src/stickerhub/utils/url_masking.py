"""Shared constants and utilities for URL masking to prevent credential leakage in logs."""

from urllib.parse import urlparse

# URL masking constants
PATH_PREFIX_LENGTH = 20
PATH_SUFFIX_LENGTH = 8
PATH_MASK_THRESHOLD = PATH_PREFIX_LENGTH + PATH_SUFFIX_LENGTH


def mask_url(url: str) -> str:
    """
    脱敏 URL 用于日志输出，避免泄露敏感 token。

    仅保留协议、域名、路径前 20 个字符和后 8 个字符，中间用 ... 替代。
    """
    try:
        parsed = urlparse(url)
        if parsed.path and len(parsed.path) > PATH_MASK_THRESHOLD:
            masked_path = (
                f"{parsed.path[:PATH_PREFIX_LENGTH]}...{parsed.path[-PATH_SUFFIX_LENGTH:]}"
            )
        else:
            masked_path = parsed.path
        return f"{parsed.scheme}://{parsed.netloc}{masked_path}"
    except (ValueError, TypeError, AttributeError):
        # urlparse 可能抛出 ValueError，或传入 None 导致 TypeError/AttributeError
        return "[url_masked]"
