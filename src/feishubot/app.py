from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from feishubot.config import settings
from feishubot.feishu import FeishuClient
from feishubot.llm_client import EchoLLMClient, LLMClient, OpenAICompatibleLLMClient

app = FastAPI(title="FeishuBot", version="0.1.0")

feishu_client = FeishuClient(
    app_id=settings.feishu_app_id,
    app_secret=settings.feishu_app_secret,
)


def get_llm_client() -> LLMClient:
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            chat_path=settings.llm_chat_path,
            timeout_seconds=settings.llm_timeout_seconds,
            default_system_prompt=settings.llm_system_prompt,
        )
    if settings.llm_provider == "echo":
        return EchoLLMClient()
    raise HTTPException(status_code=500, detail=f"unsupported LLM provider: {settings.llm_provider}")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str | None = None
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    provider: str
    model: str
    reply: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/llm/chat", response_model=ChatResponse)
async def chat_with_llm(payload: ChatRequest) -> ChatResponse:
    llm_client = get_llm_client()

    if isinstance(llm_client, OpenAICompatibleLLMClient) and payload.system_prompt:
        reply = await llm_client.generate_reply_with_system_prompt(
            prompt=payload.message,
            system_prompt=payload.system_prompt,
            user_id=payload.user_id,
        )
    else:
        reply = await llm_client.generate_reply(prompt=payload.message, user_id=payload.user_id)

    return ChatResponse(
        provider=settings.llm_provider,
        model=settings.llm_model,
        reply=reply,
    )


@app.post("/webhook/feishu/events")
async def handle_feishu_events(request: Request) -> dict[str, Any]:
    body = await request.json()

    # URL verification handshake required by Feishu event subscription.
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    # Optional verification token check.
    if settings.feishu_verification_token:
        token = body.get("token")
        if token != settings.feishu_verification_token:
            raise HTTPException(status_code=401, detail="invalid verification token")

    event = body.get("event", {})
    message = event.get("message", {})
    sender = event.get("sender", {})

    raw_content = message.get("content", "")
    text = raw_content
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
            if isinstance(parsed, dict):
                text = parsed.get("text") or raw_content
        except json.JSONDecodeError:
            text = raw_content

    if not text:
        return {"ok": True, "ignored": "empty message content"}

    user_open_id = sender.get("sender_id", {}).get("open_id")
    chat_id = event.get("message", {}).get("chat_id")

    llm_client = get_llm_client()
    reply = await llm_client.generate_reply(prompt=text, user_id=user_open_id)

    # For private chat or group where bot can directly send by chat_id, adjust receive_id_type as needed.
    if chat_id:
        await feishu_client.send_text_message(receive_id=chat_id, text=reply, receive_id_type="chat_id")

    return {"ok": True}
