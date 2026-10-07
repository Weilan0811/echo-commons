import json


def assert_readable_model_calls(directory, *, invocation_id=None):
    started = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in directory.glob("*-model_call.started.json")
    ]
    completed = [
        json.loads(path.read_text(encoding="utf-8")) for path in directory.glob("*-model_call.json")
    ]
    calls = [
        call
        for call in completed
        if invocation_id is None or call["correlation"]["invocationId"] == str(invocation_id)
    ]
    assert calls
    for call in calls:
        matches = [
            (path, entry)
            for path, entry in started
            if entry["correlation"] == call["correlation"] and entry["route"] == call["route"]
        ]
        assert len(matches) == 1
        path, entry = matches[0]
        assert entry["sequence"] < call["sequence"]
        assert entry["input"] == call["input"]
        text = path.with_suffix(".txt").read_text(encoding="utf-8")
        provider = call["input"]["providerRequest"]
        for index, message in enumerate(provider["messages"], start=1):
            assert f"消息 {index} · {message['role']}" in text
            assert (message.get("content") or "") in text
            extra = {key: value for key, value in message.items() if key not in {"role", "content"}}
            if extra:
                assert json.dumps(extra, ensure_ascii=False, indent=2) in text
        assert json.dumps(provider.get("tools", []), ensure_ascii=False, indent=2) in text
        assert call["correlation"]["invocationId"] in text
