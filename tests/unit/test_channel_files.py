from eventbuddy.capabilities.channel_files import ChannelFilesService
from eventbuddy.ingestion.pipeline import IngestResult


class _Graph:
    def get_channel_files_folder(self, team_id, channel_id):
        return ("drv1", "folder1")

    def list_children(self, drive_id, item_id):
        return [{"id": "f1", "name": "guests.xlsx"},
                {"id": "sub", "name": "archive", "folder": {}},  # skipped
                {"id": "f2", "name": "agenda.docx"}]

    def resolve_share_url(self, url):
        return ("drvShare", "itemLink")


class _Pipeline:
    def __init__(self):
        self.ingested = []

    def ingest(self, *, drive_id, item_id, event_id):
        self.ingested.append((drive_id, item_id, event_id))
        return IngestResult(documents=1, members_added=2, tasks_added=1, invited_proposed=2)


def test_sync_channel_ingests_files_skips_folders():
    pipe = _Pipeline()
    svc = ChannelFilesService(_Graph(), pipe, team_id="team")
    summary = svc.sync_channel(event_id="ev1", channel_id="chan")
    assert [i[1] for i in pipe.ingested] == ["f1", "f2"]  # folder 'sub' skipped
    assert summary["files_ingested"] == 2
    assert summary["members_added"] == 4
    assert summary["tasks_added"] == 2
    assert summary["invited_proposed"] == 4


def test_ingest_link_resolves_and_ingests_single():
    pipe = _Pipeline()
    svc = ChannelFilesService(_Graph(), pipe, team_id="team")
    summary = svc.ingest_link(event_id="ev1", url="https://share/x.xlsx")
    assert pipe.ingested == [("drvShare", "itemLink", "ev1")]
    assert summary["files_ingested"] == 1
