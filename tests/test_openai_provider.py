import json

from coding_platform.contracts import ToolResult
from coding_platform.openai_provider import OpenAIResponsesProvider


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.data).encode()


def test_response_tool_round_trip(monkeypatch):
    bodies = []
    responses = iter(
        [
            {
                "id": "response-1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "write_file",
                        "arguments": '{"path":"calculator.py","content":"pass"}',
                    }
                ],
            },
            {"id": "response-2", "output_text": "Done", "output": []},
        ]
    )

    def fake_urlopen(request, timeout):
        assert timeout == 90
        bodies.append(json.loads(request.data))
        return Response(next(responses))

    monkeypatch.setattr("coding_platform.openai_provider.urllib.request.urlopen", fake_urlopen)
    provider = OpenAIResponsesProvider("test-model", api_key="test-key")
    first = provider.next("create calculator", [])
    assert first.tool_calls[0].name == "write_file"
    result = ToolResult("call-1", True, 0, changed_files=["calculator.py"])
    second = provider.next("create calculator", [result])
    assert second.final_answer == "Done"
    assert bodies[1]["previous_response_id"] == "response-1"
    assert bodies[1]["input"][0]["type"] == "function_call_output"
    assert bodies[1]["input"][0]["call_id"] == "call-1"
    assert "test-key" not in json.dumps(bodies)
