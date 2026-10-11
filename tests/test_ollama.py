import json

import httpx

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
