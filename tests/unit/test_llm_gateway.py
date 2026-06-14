import pytest

from eventbuddy.common.errors import LLMError
from eventbuddy.integrations.llm.client import LLMGateway


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]


class _FakeClient:
    def __init__(self, raises=False):
        self.last_kwargs = None
        self._raises = raises
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if self._raises:
            raise RuntimeError("boom")
        return _FakeResp("hello world")


def test_chat_uses_default_model_and_returns_text():
    fake = _FakeClient()
    gw = LLMGateway(client=fake, chat_model="gemma-4-31b-it", summary_model="qwen-3-27b")
    out = gw.chat([{"role": "user", "content": "hi"}])
    assert out == "hello world"
    assert fake.last_kwargs["model"] == "gemma-4-31b-it"


def test_describe_image_builds_multimodal_payload_for_vision_model():
    fake = _FakeClient()
    gw = LLMGateway(
        client=fake, chat_model="qwen-chat", summary_model="qwen-sum",
        vision_model="google/gemma-4-31b-it",
    )
    out = gw.describe_image(b"\x89PNG", "image/png", "What is this?")
    assert out == "hello world"
    # The vision model is used — NOT the chat model.
    assert fake.last_kwargs["model"] == "google/gemma-4-31b-it"
    content = fake.last_kwargs["messages"][0]["content"]
    kinds = {part["type"] for part in content}
    assert kinds == {"text", "image_url"}
    img = next(p for p in content if p["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")


def test_describe_image_uses_explicit_model_override():
    fake = _FakeClient()
    gw = LLMGateway(client=fake, vision_model="google/gemma-4-31b-it")
    gw.describe_image(b"x", "image/jpeg", "read", model="gemini/gemini-2.5-pro")
    assert fake.last_kwargs["model"] == "gemini/gemini-2.5-pro"


def test_describe_image_error_degrades_to_llmerror():
    gw = LLMGateway(client=_FakeClient(raises=True), vision_model="v")
    with pytest.raises(LLMError):
        gw.describe_image(b"x", "image/png", "read")
