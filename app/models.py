"""Pydantic schemas for the OpenAI-compatible surface.

Request models permit unknown fields: the middleware forwards the client's
payload upstream, so parameters it does not model must survive the round trip.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """One entry of the ``messages`` array. ``content`` is deliberately loose —
    OpenAI accepts a string or a list of content parts."""

    role: str
    content: Any = None

    model_config = ConfigDict(extra="allow")


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None

    model_config = ConfigDict(extra="allow", protected_namespaces=())


class ModelObject(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str = "openai"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelObject]


class ErrorBody(BaseModel):
    message: str
    type: str
    code: str | None = None
    param: str | None = None


class ErrorEnvelope(BaseModel):
    """OpenAI's error shape. Open WebUI surfaces ``message`` to the user, so
    anything worth reading must go there."""

    error: ErrorBody = Field(...)
