import logging


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # 避免 Ctrl+C 退出时 python-telegram-bot 输出 CancelledError 栈噪音
    logging.getLogger("telegram.ext.Application").disabled = True
