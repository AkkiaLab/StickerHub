import asyncio
import logging
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class BindingStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._lock = asyncio.Lock()

    async def ensure_initialized(self) -> None:
        async with self._lock:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS platform_bindings (
                        platform TEXT NOT NULL,
                        platform_user_id TEXT NOT NULL,
                        hub_id TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY (platform, platform_user_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_platform_bindings_hub
                    ON platform_bindings (platform, hub_id);

                    CREATE TABLE IF NOT EXISTS magic_codes (
                        code TEXT PRIMARY KEY,
                        hub_id TEXT NOT NULL,
                        expires_at INTEGER NOT NULL,
                        used INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        used_at INTEGER
                    );
                    """
                )
                conn.commit()

            logger.info("绑定数据库已初始化: %s", self._db_path)

    async def get_hub_id(self, platform: str, platform_user_id: str) -> str | None:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT hub_id
                    FROM platform_bindings
                    WHERE platform = ? AND platform_user_id = ?
                    """,
                    (platform, platform_user_id),
                ).fetchone()

        return str(row["hub_id"]) if row else None

    async def bind_platform(
        self,
        platform: str,
        platform_user_id: str,
        hub_id: str,
    ) -> None:
        now = int(time.time())
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO platform_bindings(
                        platform, platform_user_id, hub_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(platform, platform_user_id)
                    DO UPDATE SET
                        hub_id = excluded.hub_id,
                        updated_at = excluded.updated_at
                    """,
                    (platform, platform_user_id, hub_id, now, now),
                )
                conn.commit()

        logger.info("绑定平台身份成功: platform=%s user=%s", platform, platform_user_id)

    async def force_bind_platform(
        self,
        platform: str,
        platform_user_id: str,
        hub_id: str,
    ) -> dict[str, str | None]:
        """
        强制绑定策略（用于消费魔法字符串）：
        1. 当前账号总是绑定到目标 hub_id
        2. 若同平台已有其他账号绑定到该 hub_id，旧账号会被替换（魔法字符串所属身份优先）
        """
        now = int(time.time())
        async with self._lock:
            with self._connect() as conn:
                current_row = conn.execute(
                    """
                    SELECT hub_id
                    FROM platform_bindings
                    WHERE platform = ? AND platform_user_id = ?
                    """,
                    (platform, platform_user_id),
                ).fetchone()
                previous_hub_id = str(current_row["hub_id"]) if current_row else None

                replaced_row = conn.execute(
                    """
                    SELECT platform_user_id
                    FROM platform_bindings
                    WHERE platform = ? AND hub_id = ? AND platform_user_id != ?
                    LIMIT 1
                    """,
                    (platform, hub_id, platform_user_id),
                ).fetchone()
                replaced_user_id = str(replaced_row["platform_user_id"]) if replaced_row else None

                conn.execute(
                    """
                    DELETE FROM platform_bindings
                    WHERE platform = ? AND hub_id = ? AND platform_user_id != ?
                    """,
                    (platform, hub_id, platform_user_id),
                )

                conn.execute(
                    """
                    INSERT INTO platform_bindings(
                        platform, platform_user_id, hub_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(platform, platform_user_id)
                    DO UPDATE SET
                        hub_id = excluded.hub_id,
                        updated_at = excluded.updated_at
                    """,
                    (platform, platform_user_id, hub_id, now, now),
                )
                conn.commit()

        logger.info(
            "强制绑定完成: platform=%s user=%s previous_hub=%s replaced_user=%s",
            platform,
            platform_user_id,
            previous_hub_id,
            replaced_user_id,
        )
        return {
            "previous_hub_id": previous_hub_id,
            "replaced_user_id": replaced_user_id,
        }

    async def create_magic_code(self, hub_id: str, ttl_seconds: int) -> str:
        now = int(time.time())
        expires_at = now + ttl_seconds

        async with self._lock:
            with self._connect() as conn:
                for _ in range(10):
                    code = secrets.token_hex(4).upper()
                    try:
                        conn.execute(
                            """
                            INSERT INTO magic_codes(code, hub_id, expires_at, used, created_at)
                            VALUES (?, ?, ?, 0, ?)
                            """,
                            (code, hub_id, expires_at, now),
                        )
                        conn.commit()
                        logger.info(
                            "创建魔法字符串成功: hub_id=%s expires_at=%s",
                            hub_id,
                            expires_at,
                        )
                        return code
                    except sqlite3.IntegrityError:
                        continue

        raise RuntimeError("生成魔法字符串失败，请重试")

    async def consume_magic_code(self, code: str) -> tuple[bool, str | None, str]:
        normalized = code.strip().upper()
        now = int(time.time())

        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT hub_id, expires_at, used
                    FROM magic_codes
                    WHERE code = ?
                    """,
                    (normalized,),
                ).fetchone()

                if not row:
                    return False, None, "魔法字符串无效"

                if int(row["used"]) == 1:
                    return False, None, "魔法字符串已被使用"

                if int(row["expires_at"]) < now:
                    return False, None, "魔法字符串已过期"

                conn.execute(
                    """
                    UPDATE magic_codes
                    SET used = 1, used_at = ?
                    WHERE code = ?
                    """,
                    (now, normalized),
                )
                conn.commit()

        logger.info("消费魔法字符串成功: code=%s", normalized)
        return True, str(row["hub_id"]), "ok"

    async def get_platform_user_id(self, platform: str, hub_id: str) -> str | None:
        async with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT platform_user_id
                    FROM platform_bindings
                    WHERE platform = ? AND hub_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (platform, hub_id),
                ).fetchone()

        return str(row["platform_user_id"]) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn


class BindingService:
    def __init__(self, store: BindingStore, magic_ttl_seconds: int = 600) -> None:
        self._store = store
        self._magic_ttl_seconds = magic_ttl_seconds

    async def initialize(self) -> None:
        await self._store.ensure_initialized()

    async def handle_bind_command(
        self,
        platform: str,
        platform_user_id: str,
        arg: str | None,
    ) -> str:
        normalized_arg = (arg or "").strip().upper()

        if not normalized_arg:
            hub_id = await self._store.get_hub_id(platform, platform_user_id)
            if not hub_id:
                hub_id = uuid.uuid4().hex
                await self._store.bind_platform(platform, platform_user_id, hub_id)

            code = await self._store.create_magic_code(hub_id, self._magic_ttl_seconds)
            logger.info(
                "生成绑定指令: platform=%s user=%s code=%s",
                platform,
                platform_user_id,
                code,
            )
            return (
                "已在当前平台建立身份绑定。\n"
                f"请在另一平台发送: /bind {code}\n"
                f"有效期: {self._magic_ttl_seconds // 60} 分钟"
            )

        ok, hub_id, reason = await self._store.consume_magic_code(normalized_arg)
        if not ok or not hub_id:
            logger.warning(
                "绑定失败: platform=%s user=%s code=%s reason=%s",
                platform,
                platform_user_id,
                normalized_arg,
                reason,
            )
            return f"绑定失败: {reason}"

        details = await self._store.force_bind_platform(platform, platform_user_id, hub_id)
        logger.info(
            "绑定成功(覆盖模式): platform=%s user=%s previous_hub=%s replaced_user=%s",
            platform,
            platform_user_id,
            details.get("previous_hub_id"),
            details.get("replaced_user_id"),
        )
        return "绑定成功，已更新当前平台身份映射"

    async def get_target_user_id(
        self,
        source_platform: str,
        source_user_id: str,
        target_platform: str,
    ) -> str | None:
        hub_id = await self._store.get_hub_id(source_platform, source_user_id)
        if not hub_id:
            logger.debug(
                "未找到源平台绑定: source_platform=%s source_user_id=%s",
                source_platform,
                source_user_id,
            )
            return None

        target_user_id = await self._store.get_platform_user_id(target_platform, hub_id)
        logger.debug(
            "绑定路由查询: source_platform=%s source_user_id=%s target_platform=%s hit=%s",
            source_platform,
            source_user_id,
            target_platform,
            bool(target_user_id),
        )
        return target_user_id
