"""Store enriched SIMAP project context for later analysis."""

from __future__ import annotations

import logging
from typing import Any

from simap_agent.azure_storage import get_json_blob, put_json_blob

logger = logging.getLogger(__name__)

PROJECT_CONTEXT_CONTAINER = "simap-projects"


def project_context_blob_name(project_id: str) -> str:
    return f"{project_id}.json"


def save_project_context(detail: dict[str, Any], enriched: dict[str, Any]) -> None:
    project = enriched.get("project") or {}
    project_id = project.get("projectId") or detail.get("_simap_project_id") or detail.get("id")
    if not project_id:
        logger.warning("save_project_context: no project_id found, skipping")
        return
    payload = {
        "project_id": project_id,
        "project_number": project.get("projectNumber") or detail.get("projectNumber"),
        "detail": detail,
        "enriched": enriched,
    }
    put_json_blob(PROJECT_CONTEXT_CONTAINER, project_context_blob_name(str(project_id)), payload)
    logger.info("Saved project context for project_id=%s", project_id)


def load_project_context(project_id: str) -> dict[str, Any] | None:
    if not project_id:
        return None
    result = get_json_blob(PROJECT_CONTEXT_CONTAINER, project_context_blob_name(str(project_id)))
    if result is None:
        logger.warning("No project context found for project_id=%s", project_id)
    return result
