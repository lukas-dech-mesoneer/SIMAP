"""Persistence for Slack project feedback."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simap_agent.azure_storage import append_jsonl
from simap_agent.slack_interaction import (
    INTERESTING_ACTION_ID,
    NOT_INTERESTING_ACTION_ID,
    START_ANALYSIS_ACTION_ID,
)

DEFAULT_CONTAINER = "simap-feedback"
DEFAULT_BLOB = "feedback.jsonl"


def build_feedback_record(interaction: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized feedback record for storage."""
    action_id = interaction.get("action_id")
    project = interaction.get("project") or {}
    user = interaction.get("user") or {}
    channel = interaction.get("channel") or {}
    message = interaction.get("message") or {}
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_type": _event_type(action_id),
        "action_id": action_id,
        "project_id": project.get("project_id"),
        "project_number": project.get("project_number"),
        "slack_user_id": user.get("id"),
        "slack_user_name": user.get("username") or user.get("name"),
        "slack_channel_id": channel.get("id"),
        "slack_channel_name": channel.get("name"),
        "slack_message_ts": message.get("ts"),
        "response_url_present": bool(interaction.get("response_url")),
    }


def save_feedback_record(record: dict[str, Any]) -> None:
    """Append one feedback record to local file or Azure Blob Storage."""
    local_file = os.getenv("SIMAP_FEEDBACK_FILE")
    if local_file:
        _append_local(local_file, record)
        return

    container = os.getenv("SIMAP_FEEDBACK_CONTAINER", DEFAULT_CONTAINER)
    blob_name = os.getenv("SIMAP_FEEDBACK_BLOB", DEFAULT_BLOB)
    append_jsonl(container, blob_name, record)


def _append_local(path: str, record: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def _event_type(action_id: str | None) -> str:
    if action_id == INTERESTING_ACTION_ID:
        return "interesting"
    if action_id == NOT_INTERESTING_ACTION_ID:
        return "not_interesting"
    if action_id == START_ANALYSIS_ACTION_ID:
        return "start_analysis"
    return "unknown"
