"""Track SIMAP publications that were already posted to Slack."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


def deduplication_key(project: Dict[str, Any], scope: str = "project") -> str | None:
    """Return a stable deduplication key for a SIMAP project or publication."""
    if not isinstance(project, dict):
        return None
    project_id = project.get("_simap_project_id") or project.get("id") or project.get("projectId")
    publication_id = project.get("_simap_publication_id") or project.get("publicationId")
    if scope == "publication":
        if project_id and publication_id:
            return f"{project_id}:{publication_id}"
        return None
    if project_id:
        return str(project_id)
    if publication_id:
        return str(publication_id)
    return None


def publication_key(project: Dict[str, Any]) -> str | None:
    """Return a stable key for a SIMAP publication."""
    if not isinstance(project, dict):
        return None
    project_id = project.get("_simap_project_id") or project.get("id") or project.get("projectId")
    publication_id = project.get("_simap_publication_id") or project.get("publicationId")
    if project_id and publication_id:
        return f"{project_id}:{publication_id}"
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_posted_at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_posted_entries(path: str) -> Dict[str, str | None]:
    """Load already posted keys with optional timestamps from disk."""
    store_path = Path(path)
    if not store_path.exists():
        return {}
    try:
        with store_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read posted projects store %s", store_path)
        return {}

    if isinstance(data, list):
        return {str(item): None for item in data}
    if isinstance(data, dict):
        items = data.get("posted_keys", data.get("posted_publications", []))
        if isinstance(items, list):
            return {str(item): None for item in items}
        if isinstance(items, dict):
            return {str(key): value if isinstance(value, str) else None for key, value in items.items()}
    logger.warning("Ignoring posted projects store with unexpected format: %s", store_path)
    return {}


def prune_posted_entries(
    entries: Dict[str, str | None], retention_days: int, now: datetime | None = None
) -> Dict[str, str | None]:
    """Return entries that are still within retention."""
    if retention_days <= 0:
        return dict(entries)

    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    kept: Dict[str, str | None] = {}
    for key, posted_at in entries.items():
        parsed = _parse_posted_at(posted_at)
        if parsed is None or parsed > cutoff:
            kept[key] = posted_at
    return kept


def load_posted_keys(path: str, retention_days: int = 0) -> Set[str]:
    """Load already posted keys from disk."""
    entries = load_posted_entries(path)
    entries = prune_posted_entries(entries, retention_days)
    return set(entries)


def save_posted_keys(path: str, keys: Set[str], retention_days: int = 0) -> None:
    """Persist posted keys to disk with timestamps."""
    store_path = Path(path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    existing = prune_posted_entries(load_posted_entries(path), retention_days)
    now = _now_iso()
    entries = {key: existing.get(key) or now for key in sorted(keys)}
    payload = {"posted_keys": entries}
    with store_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
