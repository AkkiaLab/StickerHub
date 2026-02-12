import json
import logging

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

    async def send(self, asset: StickerAsset, target_user_id: str) -> None:
        logger.debug(
            "准备发送图片到飞书: receive_id=%s file=%s mime=%s size=%s",
            target_user_id,
            asset.file_name,
            asset.mime_type,
            len(asset.content),
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            token = await self._get_tenant_token(client)
            image_key = await self._upload_image(client, token, asset)
            await self._send_image_message(client, token, image_key, target_user_id)

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
