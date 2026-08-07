from __future__ import annotations

import json

import httpx

from aleph.llm.qwen import QwenProvider


def test_qwen_structured_requests_disable_hidden_thinking_by_default() -> None:
    requests: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "fixture",
                "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 3},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = QwenProvider(base_url="http://model.test/v1", client=client)
    response = provider.complete(
        "Return the status.",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    )

    assert response.schema_valid is True
    assert response.parsed == {"ok": True}
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert requests[0]["response_format"]["type"] == "json_schema"
