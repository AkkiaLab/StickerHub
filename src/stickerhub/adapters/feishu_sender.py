import json
import logging
from typing import Literal

import httpx

from stickerhub.core.models import StickerAsset

logger = logging.getLogger(__name__)


class FeishuSender:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._base_url = "https://open.feishu.cn/open-apis"

    async def send(
        self, asset: StickerAsset, target_mode: Literal["bot", "webhook"], target: str
    ) -> None:
        # 避免在日志中暴露 webhook URL 中的敏感 token
        safe_target = target if target_mode == "bot" else _mask_webhook_url(target)
        logger.debug(
            "准备发送图片到飞书: mode=%s target=%s file=%s mime=%s size=%s",
            target_mode,
            safe_target,
            asset.file_name,
            asset.mime_type,
            len(asset.content),
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._get_tenant_token(client)
            image_key = await self._upload_image(client, token, asset)
            if target_mode == "bot":
                await self._send_image_message(client, token, image_key, target)
                return
            if target_mode == "webhook":
                await self._send_webhook_image(client, image_key=image_key, webhook_url=target)
                return
            raise RuntimeError(f"不支持的飞书目标类型: {target_mode}")

    async def send_text(
        self,
        text: str,
        receive_id: str,
        receive_id_type: str = "open_id",
    ) -> None:
        logger.debug(
            "准备发送飞书文本: receive_id_type=%s receive_id=%s",
            receive_id_type,
            receive_id,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._get_tenant_token(client)
            response = await client.post(
                f"{self._base_url}/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "receive_id": receive_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                },
            )
            payload = response.json()
            if response.status_code != 200 or payload.get("code") != 0:
                raise RuntimeError(f"发送飞书文本消息失败: {payload}")
            logger.info("飞书文本消息已发送: receive_id=%s", receive_id)

    async def send_webhook_text(self, text: str, webhook_url: str) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await self._send_webhook_message(
                client,
                webhook_url=webhook_url,
                message={
                    "msg_type": "text",
                    "content": {"text": text},
                },
            )
        logger.info("飞书 webhook 文本消息已发送")

    async def _get_tenant_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{self._base_url}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": self._app_id,
                "app_secret": self._app_secret,
            },
        )
        payload = response.json()
        if response.status_code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"获取飞书 tenant_access_token 失败: {payload}")
        token = payload.get("tenant_access_token")
        if not token:
            raise RuntimeError("飞书 tenant_access_token 为空")
        logger.debug("飞书 tenant_access_token 获取成功")
        return token

    async def _upload_image(
        self,
        client: httpx.AsyncClient,
        token: str,
        asset: StickerAsset,
    ) -> str:
        response = await client.post(
            f"{self._base_url}/im/v1/images",
            headers={"Authorization": f"Bearer {token}"},
            files={
                "image_type": (None, "message"),
                "image": (asset.file_name, asset.content, asset.mime_type),
            },
        )

        payload = response.json()
        if response.status_code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"上传飞书图片失败: {payload}")

        image_key = (payload.get("data") or {}).get("image_key")
        if not image_key:
            raise RuntimeError("飞书 image_key 为空")
        logger.debug("飞书图片上传成功: image_key=%s", image_key)
        return image_key

    async def _send_image_message(
        self,
        client: httpx.AsyncClient,
        token: str,
        image_key: str,
        receive_id: str,
    ) -> None:
        response = await client.post(
            f"{self._base_url}/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": receive_id,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
        )
        payload = response.json()
        if response.status_code != 200 or payload.get("code") != 0:
            raise RuntimeError(f"发送飞书消息失败: {payload}")

        logger.info("素材已发送到飞书: receive_id=%s", receive_id)

    async def _send_webhook_image(
        self,
        client: httpx.AsyncClient,
        image_key: str,
        webhook_url: str,
    ) -> None:
        await self._send_webhook_message(
            client,
            webhook_url=webhook_url,
            message={
                "msg_type": "image",
                "content": {"image_key": image_key},
            },
        )
        logger.info("素材已发送到飞书 webhook")

    async def _send_webhook_message(
        self,
        client: httpx.AsyncClient,
        webhook_url: str,
        message: dict[str, object],
    ) -> None:
        response = await client.post(
            webhook_url,
            headers={"Content-Type": "application/json"},
            json=message,
        )
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {"raw_body": response.text}

        if response.status_code != 200:
            raise RuntimeError(
                "发送飞书 webhook 消息失败: " f"status={response.status_code} payload={payload}"
            )

        status_code = payload.get("StatusCode")
        code = payload.get("code")
        status_ok = status_code in (None, 0, "0")
        code_ok = code in (None, 0, "0")
        if not status_ok or not code_ok:
            raise RuntimeError(f"发送飞书 webhook 消息失败: {payload}")


PATH_PREFIX_LENGTH = 20
PATH_SUFFIX_LENGTH = 8
PATH_MASK_THRESHOLD = PATH_PREFIX_LENGTH + PATH_SUFFIX_LENGTH


def _mask_webhook_url(webhook_url: str) -> str:
    """脱敏 webhook URL，仅保留 host 和末尾部分，避免泄露敏感 token"""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(webhook_url)
        if parsed.path and len(parsed.path) > PATH_MASK_THRESHOLD:
            masked_path = f"{parsed.path[:PATH_PREFIX_LENGTH]}...{parsed.path[-PATH_SUFFIX_LENGTH:]}"
        else:
            masked_path = parsed.path
        return f"{parsed.scheme}://{parsed.netloc}{masked_path}"
    except Exception:  # noqa: BLE001
        return "[webhook_url_masked]"
