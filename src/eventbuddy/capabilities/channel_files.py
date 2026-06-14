"""On-demand pull of a Teams channel's SharePoint files (architecture §7.2).

Complements the Graph file webhook: the organizer can ask the agent to ingest whatever is
already in the channel's document library (or a pasted link), without a live subscription.
Same parse → structure → upsert → propose pipeline, different trigger."""
from eventbuddy.common.logging import get_logger

log = get_logger("capabilities.channel_files")


class ChannelFilesService:
    def __init__(self, graph, pipeline, *, team_id: str):
        self.graph = graph
        self.pipeline = pipeline
        self.team_id = team_id

    def sync_channel(self, *, event_id: str, channel_id: str) -> dict:
        """Ingest every file currently in the channel's SharePoint folder. Idempotent — the
        pipeline skips drive items already ingested."""
        drive_id, folder_id = self.graph.get_channel_files_folder(self.team_id, channel_id)
        children = self.graph.list_children(drive_id, folder_id)
        return self._ingest_items(event_id, drive_id, children)

    def ingest_link(self, *, event_id: str, url: str) -> dict:
        """Resolve a SharePoint/OneDrive sharing link and ingest that single file."""
        drive_id, item_id = self.graph.resolve_share_url(url)
        res = self.pipeline.ingest(drive_id=drive_id, item_id=item_id, event_id=event_id)
        return _summarize([res])

    def _ingest_items(self, event_id: str, drive_id: str, children: list[dict]) -> dict:
        results = []
        for child in children:
            if child.get("folder") is not None:
                continue  # skip subfolders (flat ingest for v1)
            results.append(self.pipeline.ingest(
                drive_id=drive_id, item_id=child["id"], event_id=event_id))
        return _summarize(results)


def _summarize(results: list) -> dict:
    return {
        "files_ingested": sum(1 for r in results if r and r.documents),
        "members_added": sum(r.members_added for r in results if r),
        "tasks_added": sum(r.tasks_added for r in results if r),
        "invited_proposed": sum(r.invited_proposed for r in results if r),
        "skipped": sum(1 for r in results if r and r.skipped),
    }
