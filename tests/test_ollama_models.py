import httpx

from dockai.llm.ollama import OllamaNotFoundError, list_ollama_models


def test_list_ollama_models_parses_tags():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        body = {"models": [{"name": "b:latest"}, {"name": "a:7b"}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(base_url="http://127.0.0.1:11434", transport=transport)
    assert list_ollama_models("http://127.0.0.1:11434", client=client) == [
        "a:7b",
        "b:latest",
    ]


def test_list_ollama_models_not_found():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(503, text="down")
    )
    client = httpx.Client(base_url="http://127.0.0.1:11434", transport=transport)
    try:
        list_ollama_models("http://127.0.0.1:11434", client=client)
    except OllamaNotFoundError as exc:
        assert "Ollama not found" in str(exc)
    else:
        raise AssertionError("expected OllamaNotFoundError")
