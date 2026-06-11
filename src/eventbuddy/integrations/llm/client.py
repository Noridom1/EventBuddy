from openai import OpenAI

from eventbuddy.config import settings


class LLMGateway:
    """Single abstraction over the GreenNode MaaS OpenAI-compatible endpoint."""

    def __init__(self, client=None, chat_model: str | None = None, summary_model: str | None = None):
        self._client = client or OpenAI(
            base_url=settings.agentbase_llm_base_url,
            api_key=settings.agentbase_llm_api_key,
        )
        self._chat_model = chat_model or settings.llm_chat_model
        self._summary_model = summary_model or settings.llm_summary_model

    def chat(self, messages: list[dict], model: str | None = None) -> str:
        resp = self._client.chat.completions.create(
            model=model or self._chat_model, messages=messages
        )
        return resp.choices[0].message.content

    def summarize(self, text: str, instruction: str) -> str:
        return self.chat(
            [{"role": "system", "content": instruction}, {"role": "user", "content": text}],
            model=self._summary_model,
        )
