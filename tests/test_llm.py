"""Provider switch in llm.py: each adapter's request and reply shape, offline (httpx.post is faked)."""

import json

import httpx
import pytest

from gstagent import llm

IMAGE = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
TEXT = {"type": "text", "text": "Read this bill."}
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no real .env leaks in
    for k in ("LLM_PROVIDER", "LLM_MODEL", *llm.KEYS.values()):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def fake_post(reply, status=200):
    sent = []

    def post(url, headers, json, timeout):
        sent.append({"url": url, "headers": headers, "body": json})
        return httpx.Response(status, json=reply, request=httpx.Request("POST", url))
    return post, sent


def test_gemini_is_the_default_and_sends_image_and_schema(env):
    env.setenv("GEMINI_API_KEY", "g-key")
    post, sent = fake_post({"status": "completed", "steps": [
        {"type": "thought", "content": []},
        {"type": "model_output", "content": [{"type": "text", "text": '{"a": "x"}'}]}]})
    env.setattr(llm.httpx, "post", post)
    assert llm.ask_json([IMAGE, TEXT], SCHEMA) == '{"a": "x"}'
    s = sent[0]
    assert s["url"].endswith("/v1beta/interactions") and s["headers"] == {"x-goog-api-key": "g-key"}
    assert s["body"]["model"] == llm.GEMINI_MODELS[0] and s["body"]["store"] is False
    assert s["body"]["input"] == [{"type": "image", "data": "QUJD", "mime_type": "image/png"}, TEXT]
    assert s["body"]["response_format"]["schema"] == SCHEMA


def test_gemini_falls_back_to_the_next_free_model_when_busy(env):
    env.setenv("GEMINI_API_KEY", "g")
    sent = []

    def post(url, headers, json, timeout):
        sent.append(json["model"])
        if len(sent) == 1:
            return httpx.Response(503, json={"error": {"message": "high demand"}}, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "{}"}]}]})
    env.setattr(llm.httpx, "post", post)
    assert llm.ask_json([TEXT], SCHEMA) == "{}" and sent == list(llm.GEMINI_MODELS[:2])


def test_groq_picks_the_vision_model_only_for_images(env):
    env.setenv("LLM_PROVIDER", "groq")
    env.setenv("GROQ_API_KEY", "q-key")
    post, sent = fake_post({"choices": [{"finish_reason": "stop", "message": {"content": '{"a": "y"}'}}]})
    env.setattr(llm.httpx, "post", post)
    assert llm.ask_json([IMAGE, TEXT], SCHEMA) == '{"a": "y"}'
    llm.ask_json([TEXT], SCHEMA)
    assert [s["body"]["model"] for s in sent] == [llm.GROQ_VISION_MODEL, llm.GROQ_TEXT_MODEL]
    assert sent[0]["headers"] == {"Authorization": "Bearer q-key"}
    assert sent[0]["body"]["messages"][0]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert sent[0]["body"]["response_format"]["json_schema"] == {"name": "reply", "strict": True, "schema": SCHEMA}


def test_key_and_model_come_from_dotenv(env, tmp_path):
    (tmp_path / ".env").write_text('# my keys\nLLM_PROVIDER=groq   # free\nGROQ_API_KEY="from-file"\n'
                                   'GEMINI_API_KEY=\nLLM_MODEL=m1\n')
    post, sent = fake_post({"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]})
    env.setattr(llm.httpx, "post", post)
    llm.ask_json([TEXT], SCHEMA)
    assert sent[0]["headers"]["Authorization"] == "Bearer from-file" and sent[0]["body"]["model"] == "m1"


def test_missing_or_refused_key_is_no_credentials(env):
    with pytest.raises(llm.NoCredentials, match="GEMINI_API_KEY"):
        llm.ask_json([TEXT], SCHEMA)
    env.setenv("GEMINI_API_KEY", "bad")
    env.setattr(llm.httpx, "post", fake_post({"error": {}}, status=403)[0])
    with pytest.raises(llm.NoCredentials):
        llm.ask_json([TEXT], SCHEMA)


@pytest.mark.parametrize("reply,status", [
    ({"error": {"message": "quota"}}, 429),                           # free-tier rate limit
    ({"status": "incomplete", "steps": []}, 200),                     # did not finish
    ({"status": "completed", "steps": []}, 200),                      # no text
])
def test_gemini_failures_are_llm_errors(env, reply, status):
    env.setenv("GEMINI_API_KEY", "g")
    env.setattr(llm.httpx, "post", fake_post(reply, status)[0])
    with pytest.raises(llm.LLMError):
        llm.ask_json([TEXT], SCHEMA)


def test_network_failure_and_unknown_provider_are_llm_errors(env):
    env.setenv("GEMINI_API_KEY", "g")

    def down(*a, **k):
        raise httpx.ConnectError("no network")
    env.setattr(llm.httpx, "post", down)
    with pytest.raises(llm.LLMError, match="could not reach gemini"):
        llm.ask_json([TEXT], SCHEMA)
    env.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(llm.LLMError, match="use one of"):
        llm.ask_json([TEXT], SCHEMA)


def test_bill_schema_fits_groq_strict_mode():
    from gstagent.extract import SCHEMA as BILL  # strict mode: every field required, no extra fields

    def strict(s):
        return s.get("type") != "object" or (s["additionalProperties"] is False
                                             and set(s["required"]) == set(s["properties"])
                                             and all(strict(v) for v in s["properties"].values()))
    assert strict(BILL) and json.dumps(BILL)


def test_busy_gemini_falls_back_to_groq_when_its_key_is_set(env):
    env.setenv("GEMINI_API_KEY", "g")
    env.setenv("GROQ_API_KEY", "q")
    env.setenv("LLM_MODEL", "gemini-3.6-flash")   # names a Gemini model; must not be sent to Groq
    sent = []

    def post(url, headers, json, timeout):
        sent.append((url.split("/")[2], json["model"]))
        req = httpx.Request("POST", url)
        if "googleapis" in url:
            return httpx.Response(429, json={"error": {"message": "quota"}}, request=req)
        return httpx.Response(200, request=req, json={"choices": [{"finish_reason": "stop",
                                                                   "message": {"content": '{"a": "z"}'}}]})
    env.setattr(llm.httpx, "post", post)
    assert llm.ask_json([TEXT], SCHEMA) == '{"a": "z"}'
    assert sent == [("generativelanguage.googleapis.com", "gemini-3.6-flash"),
                    ("api.groq.com", llm.GROQ_TEXT_MODEL)]


def test_without_a_groq_key_busy_gemini_is_still_an_error(env):
    env.setenv("GEMINI_API_KEY", "g")
    env.setattr(llm.httpx, "post", fake_post({"error": {}}, status=503)[0])
    with pytest.raises(llm.Busy):
        llm.ask_json([TEXT], SCHEMA)
