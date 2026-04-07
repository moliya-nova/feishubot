from __future__ import annotations

import json
from typing import Any

import httpx


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._tenant_access_token: str | None = None

    async def _refresh_tenant_access_token(self) -> str:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"failed to get tenant_access_token: {data}")

        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError("tenant_access_token missing in response")

        self._tenant_access_token = token
        return token

    async def get_tenant_access_token(self) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        return await self._refresh_tenant_access_token()

    async def send_text_message(self, receive_id: str, text: str, receive_id_type: str = "open_id") -> dict[str, Any]:
        token = await self.get_tenant_access_token()
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {"Authorization": f"Bearer {token}"}
        params = {"receive_id_type": receive_id_type}
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=headers, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"failed to send feishu message: {data}")

        return data
