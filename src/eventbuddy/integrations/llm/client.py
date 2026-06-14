import base64

from openai import OpenAI

from eventbuddy.common.errors import LLMError
from eventbuddy.config import settings


class LLMGateway:
    """Single abstraction over the GreenNode MaaS OpenAI-compatible endpoint."""

    def __init__(
        self, client=None, chat_model: str | None = None, summary_model: str | None = None,
        vision_model: str | None = None,
    ):
        self._client = client or OpenAI(
            base_url=settings.agentbase_llm_base_url,
            api_key=settings.agentbase_llm_api_key,
        )
        self._chat_model = chat_model or settings.llm_chat_model
        self._summary_model = summary_model or settings.llm_summary_model
        self._vision_model = vision_model or settings.llm_vision_model

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

    def describe_image(
        self, image_bytes: bytes, mime: str, instruction: str, *, model: str | None = None
    ) -> str:
        """Read an image with a vision model (Impl 5). Base64-encodes the bytes into a data URI
        and sends the OpenAI multimodal `content` array to a SEPARATE vision model — the text
        chat brain is never used for this. Returns the model's text. Raises `LLMError` on any
        failure so the caller degrades (never returns garbage as if it had read the image)."""
        data_uri = f"data:{mime or 'image/png'};base64,{base64.b64encode(image_bytes).decode()}"
        try:
            resp = self._client.chat.completions.create(
                model=model or self._vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }],
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # noqa: BLE001 — normalize to a typed error the caller catches
            raise LLMError(f"vision call failed: {type(e).__name__}: {e}") from e
