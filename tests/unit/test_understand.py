"""Impl 5 — generic file understanding (summary + doc_type), text + vision paths."""
from eventbuddy.common.errors import LLMError
from eventbuddy.ingestion.parsers import ParsedDoc
from eventbuddy.ingestion.understand import understand


class _LLM:
    def __init__(self, reply):
        self._reply = reply
        self.called = False

    def chat(self, messages, model=None):
        self.called = True
        return self._reply


class _Vision:
    def __init__(self, reply="A poster advertising the keynote.", raises=False):
        self._reply = reply
        self._raises = raises
        self.called = False

    def describe_image(self, image_bytes, mime, instruction, *, model=None):
        self.called = True
        if self._raises:
            raise LLMError("vision down")
        return self._reply


def test_understand_text_classifies_and_summarizes():
    llm = _LLM('{"summary": "A reusable sponsor email.", "doc_type": "template"}')
    out = understand(ParsedDoc(kind="docx", filename="t.docx", text="Dear {name}..."), llm=llm)
    assert out == {"summary": "A reusable sponsor email.", "doc_type": "template"}


def test_understand_text_malformed_degrades_to_other():
    out = understand(
        ParsedDoc(kind="docx", filename="t.docx", text="hi"), llm=_LLM("not json"))
    assert out["doc_type"] == "other"


def test_understand_text_unknown_type_falls_back_to_other():
    llm = _LLM('{"summary": "x", "doc_type": "spaceship"}')
    out = understand(ParsedDoc(kind="pdf", filename="p.pdf", text="x"), llm=llm)
    assert out["doc_type"] == "other"


def test_understand_empty_text_no_llm_call():
    llm = _LLM("{}")
    out = understand(ParsedDoc(kind="docx", filename="t.docx", text="   "), llm=llm)
    assert llm.called is False
    assert out == {"summary": "", "doc_type": "other"}


def test_understand_image_uses_vision():
    vision = _Vision()
    out = understand(
        ParsedDoc(kind="image", filename="f.png", raw_bytes=b"x", mime="image/png"),
        llm=_LLM("{}"), vision=vision)
    assert vision.called is True
    assert out == {"summary": "A poster advertising the keynote.", "doc_type": "image"}


def test_understand_image_without_vision_degrades():
    out = understand(
        ParsedDoc(kind="image", filename="f.png", raw_bytes=b"x", mime="image/png"),
        llm=_LLM("{}"), vision=None)
    assert out["doc_type"] == "image"
    assert "vision not configured" in out["summary"]


def test_understand_image_vision_error_degrades():
    out = understand(
        ParsedDoc(kind="image", filename="f.png", raw_bytes=b"x", mime="image/png"),
        llm=_LLM("{}"), vision=_Vision(raises=True))
    assert out["doc_type"] == "image"
    assert out["summary"].startswith("(image")
