from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from feishubot.ai.core.errors import ProviderNotFoundError
from feishubot.ai.orchestrator import AgentLoop
from feishubot.ai.prompts import build_system_prompt
from feishubot.ai.providers import ModelProvider, create_provider
from feishubot.ai.tools import ToolRuntime
from feishubot.config import settings
from feishubot.feishu import FeishuClient

app = FastAPI(title="FeishuBot", version="0.1.0")

feishu_client = FeishuClient(
    app_id=settings.feishu_app_id,
    app_secret=settings.feishu_app_secret,
)


def get_model_provider() -> ModelProvider:
    active = settings.active_llm_config()
    try:
        return create_provider(active)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str | None = None
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    provider: str
    model: str
    reply: str


def _coerce_first_value(values: list[str] | None) -> str | None:
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    normalized = str(value).strip()
    return normalized or None


def _decode_request_body(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="request body must be valid utf-8") from exc


async def _extract_chat_request(request: Request) -> ChatRequest:
    message: str | None = _coerce_first_value(request.query_params.getlist("message"))
    if message is None:
        message = _coerce_first_value(request.query_params.getlist("text"))
    if message is None:
        message = _coerce_first_value(request.query_params.getlist("prompt"))

    user_id = _coerce_first_value(request.query_params.getlist("user_id"))
    system_prompt = _coerce_first_value(request.query_params.getlist("system_prompt"))

    body = await request.body()
    if body:
        content_type = request.headers.get("content-type", "").lower()
        if "application/json" in content_type:
            try:
                payload = json.loads(_decode_request_body(body))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid JSON body") from exc

            if isinstance(payload, dict):
                message = (
                    _normalize_text(payload.get("message"))
                    or _normalize_text(payload.get("text"))
                    or _normalize_text(payload.get("prompt"))
                    or message
                )
                user_id = _normalize_text(payload.get("user_id")) or user_id
                system_prompt = _normalize_text(payload.get("system_prompt")) or system_prompt
            elif isinstance(payload, str):
                message = _normalize_text(payload) or message
        elif "application/x-www-form-urlencoded" in content_type:
            form_values = parse_qs(_decode_request_body(body), keep_blank_values=True)
            message = (
                _coerce_first_value(form_values.get("message"))
                or _coerce_first_value(form_values.get("text"))
                or _coerce_first_value(form_values.get("prompt"))
                or message
            )
            user_id = _coerce_first_value(form_values.get("user_id")) or user_id
            system_prompt = _coerce_first_value(form_values.get("system_prompt")) or system_prompt
        elif message is None:
            raw_text = _decode_request_body(body).strip()
            if raw_text:
                message = raw_text

    if message is None:
        raise HTTPException(status_code=422, detail="message is required")

    return ChatRequest(message=message, user_id=user_id, system_prompt=system_prompt)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.api_route("/api/chat", methods=["GET", "POST"], response_model=ChatResponse)
@app.api_route("/api/llm/chat", methods=["GET", "POST"], response_model=ChatResponse)
async def chat_with_llm(request: Request) -> ChatResponse:
    payload = await _extract_chat_request(request)
    active = settings.active_llm_config()
    model_provider = get_model_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=build_system_prompt(
            active.system_prompt, payload.system_prompt, include_core=False
        ),
    )
    reply = await agent_loop.run(user_input=payload.message, user_id=payload.user_id)

    return ChatResponse(
        provider=active.provider,
        model=active.model,
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

    model_provider = get_model_provider()
    agent_loop = AgentLoop(
        model_provider=model_provider,
        tool_runtime=ToolRuntime(),
        system_prompt=build_system_prompt(
            settings.active_llm_config().system_prompt, include_core=False
        ),
    )
    reply = await agent_loop.run(user_input=text, user_id=user_open_id)

    # For private/group chat replies, send by chat_id. Adjust receive_id_type if needed.
    if chat_id:
        await feishu_client.send_text_message(
            receive_id=chat_id, text=reply, receive_id_type="chat_id"
        )

    return {"ok": True}
