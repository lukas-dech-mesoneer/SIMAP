"""Track SIMAP publications that were already posted to Slack."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Set

from simap_agent.azure_storage import get_json_blob, put_json_blob

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


def _azure_blob_path(path: str) -> tuple[str, str] | None:
    prefix = "azure://"
    if not path.startswith(prefix):
        return None
    value = path[len(prefix) :]
    container, separator, blob_name = value.partition("/")
    if not container or not separator or not blob_name:
        raise ValueError(f"Invalid Azure blob path: {path}")
    return container, blob_name


def _entries_from_payload(data: Any, store_name: str) -> Dict[str, str | None]:
    if isinstance(data, list):
        return {str(item): None for item in data}
    if isinstance(data, dict):
        items = data.get("posted_keys", data.get("posted_publications", []))
        if isinstance(items, list):
            return {str(item): None for item in items}
        if isinstance(items, dict):
            return {str(key): value if isinstance(value, str) else None for key, value in items.items()}
    logger.warning("Ignoring posted projects store with unexpected format: %s", store_name)
    return {}


def _load_file_entries(path: str) -> Dict[str, str | None]:
    store_path = Path(path)
    if not store_path.exists():
        return {}
    try:
        with store_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read posted projects store %s", store_path)
        return {}

    return _entries_from_payload(data, str(store_path))


def _legacy_azure_function_file() -> str | None:
    explicit = os.getenv("POSTED_PROJECTS_LEGACY_FILE")
    if explicit:
        return explicit
    home = os.getenv("HOME")
    if not home:
        return None
    return os.path.join(home, "data", "posted_projects.json")


def load_posted_entries(path: str) -> Dict[str, str | None]:
    """Load already posted keys with optional timestamps from disk."""
    azure_path = _azure_blob_path(path)
    if azure_path:
        container, blob_name = azure_path
        try:
            data = get_json_blob(container, blob_name)
        except Exception:
            logger.exception("Could not read posted projects store %s", path)
            return {}
        if data is None:
            legacy_file = _legacy_azure_function_file()
            if legacy_file:
                legacy_entries = _load_file_entries(legacy_file)
                if legacy_entries:
                    logger.info(
                        "Loaded %d posted project keys from legacy file %s",
                        len(legacy_entries),
                        legacy_file,
                    )
                    return legacy_entries
            return {}
        return _entries_from_payload(data, path)

    return _load_file_entries(path)


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
    existing = prune_posted_entries(load_posted_entries(path), retention_days)
    now = _now_iso()
    entries = {key: existing.get(key) or now for key in sorted(keys)}
    payload = {"posted_keys": entries}
    azure_path = _azure_blob_path(path)
    if azure_path:
        container, blob_name = azure_path
        put_json_blob(container, blob_name, payload)
        return

    store_path = Path(path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with store_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
