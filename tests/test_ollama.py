import json

import httpx

from dockai.config import Settings
from dockai.llm.base import ChatMessage
from dockai.llm.ollama import OllamaProvider


def test_ollama_parses_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "list_containers",
                            "arguments": {"all_containers": False},
                        }
                    }
                ],
            }
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="http://test")
    provider = OllamaProvider(client=client, model="llama3.1")
    msg = provider.chat([ChatMessage(role="user", content="hi")], tools=[])
    assert msg.tool_calls[0].name == "list_containers"
    assert msg.tool_calls[0].arguments == {"all_containers": False}


def test_ollama_parses_string_arguments():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_containers",
                                "arguments": json.dumps({"keyword": "flink"}),
                            }
                        }
                    ],
                }
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://test"
    )
    msg = OllamaProvider(client=client).chat(
        [ChatMessage(role="user", content="find flink")], tools=[]
    )
    assert msg.tool_calls[0].arguments == {"keyword": "flink"}


def test_ollama_provider_uses_split_timeout():
    settings = Settings(
        ollama_host="http://127.0.0.1:11434",
        ollama_model="qwen2.5:3b",
        ollama_timeout=120.0,
        ollama_health_timeout=10.0,
        config_path=None,
    )
    provider = OllamaProvider(settings=settings)
    try:
        timeout = provider._client.timeout
        assert timeout.connect is not None
        assert timeout.read is not None
        assert float(timeout.connect) <= 10.0
        assert float(timeout.read) == 120.0
    finally:
        provider.close()
