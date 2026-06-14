from eventbuddy.capabilities.forms_sync import FormsResponseSync
from eventbuddy.ingestion.parsers import ParsedDoc


class _Graph:
    def resolve_share_url(self, url):
        return ("drive1", "item1")

    def get_drive_item_content(self, drive_id, item_id):
        return (b"", "responses.xlsx", "application/xlsx")


class _Repo:
    def __init__(self, existing=None):
        self.existing = set(existing or [])
        self.added = []

    def respondent_ids(self, event_id):
        return set(self.existing)

    def add(self, event_id, *, respondent_id, raw_payload, sentiment=None, themes=None):
        self.added.append((respondent_id, raw_payload, sentiment, themes))


class _Analyzer:
    def analyze(self, comment):
        return ("positive", ["content"]) if "great" in comment.lower() else ("neutral", [])


def _parse_returning(rows):
    return lambda filename, content: ParsedDoc(kind="xlsx", filename=filename, rows=rows)


def test_sync_ingests_new_rows_with_analysis():
    repo = _Repo()
    rows = [
        {"Email": "a@x.com", "Rating": "5", "Comment": "great session"},
        {"Email": "b@x.com", "Rating": 2, "Comment": "too long"},
    ]
    sync = FormsResponseSync(_Graph(), repo, _Analyzer(), parse=_parse_returning(rows))
    n = sync.sync(event_id="ev1", workbook_url="https://share/wb.xlsx")
    assert n == 2
    first = repo.added[0]
    assert first[0] == "a@x.com"
    assert first[1]["rating"] == 5
    assert first[2] == "positive"
    assert first[3] == {"tags": ["content"]}


def test_sync_dedups_against_existing():
    repo = _Repo(existing={"a@x.com"})
    rows = [{"Email": "a@x.com", "Rating": 5, "Comment": "great"},
            {"Email": "c@x.com", "Rating": 4, "Comment": "good"}]
    n = FormsResponseSync(_Graph(), repo, _Analyzer(),
                          parse=_parse_returning(rows)).sync(event_id="ev1", workbook_url="u")
    assert n == 1
    assert repo.added[0][0] == "c@x.com"


def test_sync_no_url_is_noop():
    repo = _Repo()
    assert FormsResponseSync(_Graph(), repo, _Analyzer()).sync(event_id="ev1", workbook_url="") == 0
    assert repo.added == []


def test_sync_degrades_on_graph_error():
    class _Boom:
        def resolve_share_url(self, url):
            raise RuntimeError("graph down")

    repo = _Repo()
    n = FormsResponseSync(_Boom(), repo, _Analyzer()).sync(event_id="ev1", workbook_url="u")
    assert n == 0
    assert repo.added == []
