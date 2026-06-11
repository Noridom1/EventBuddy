from eventbuddy.integrations.llm.client import LLMGateway


class _FakeResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})]


class _FakeClient:
    def __init__(self):
        self.last_kwargs = None
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResp("hello world")


def test_chat_uses_default_model_and_returns_text():
    fake = _FakeClient()
    gw = LLMGateway(client=fake, chat_model="gemma-4-31b-it", summary_model="qwen-3-27b")
    out = gw.chat([{"role": "user", "content": "hi"}])
    assert out == "hello world"
    assert fake.last_kwargs["model"] == "gemma-4-31b-it"
