from eventbuddy.ingestion.extractor import Extractor
from eventbuddy.ingestion.parsers import ParsedDoc


class _LLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, model=None):
        self.calls += 1
        return self.reply


def _doc(text="some content"):
    return ParsedDoc(kind="xlsx", filename="f.xlsx", text=text)


def test_structure_parses_members_and_tasks():
    reply = ('{"members": [{"email": "a@x.com", "display_name": "A", "role": "member"}], '
             '"tasks": [{"task_name": "Book room", "assignee_email": "a@x.com", '
             '"due_date": null}]}')
    out = Extractor(_LLM(reply)).structure(_doc())
    assert out["members"][0]["email"] == "a@x.com"
    assert out["tasks"][0]["task_name"] == "Book room"


def test_structure_drops_members_without_email():
    reply = '{"members": [{"display_name": "No Email"}], "tasks": []}'
    out = Extractor(_LLM(reply)).structure(_doc())
    assert out["members"] == []


def test_structure_bad_json_returns_empty():
    out = Extractor(_LLM("sorry, here is the data...")).structure(_doc())
    assert out == {"members": [], "tasks": []}


def test_structure_skips_llm_on_empty_text():
    llm = _LLM("{}")
    out = Extractor(llm).structure(_doc(text=""))
    assert out == {"members": [], "tasks": []}
    assert llm.calls == 0
