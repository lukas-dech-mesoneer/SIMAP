"""Queue messages for asynchronous SIMAP detail analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

ANALYSIS_QUEUE_NAME = "simap-analysis-requests"


def build_analysis_request(interaction: dict[str, Any]) -> dict[str, Any]:
    project = interaction.get("project") or {}
    user = interaction.get("user") or {}
    channel = interaction.get("channel") or {}
    message = interaction.get("message") or {}
    channel_id = channel.get("id") or project.get("_origin_channel_id")
    thread_ts = project.get("_origin_thread_ts") or message.get("thread_ts") or message.get("ts")
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project.get("project_id"),
        "project_number": project.get("project_number"),
        "offer_deadline": project.get("offer_deadline"),
        "qna_deadline": project.get("qna_deadline"),
        "contract_start": project.get("contract_start"),
        "slack_user_id": user.get("id"),
        "slack_channel_id": channel_id,
        "slack_channel_name": channel.get("name"),
        "slack_thread_ts": thread_ts,
        "slack_message_ts": message.get("ts"),
    }


def enqueue_analysis_request(interaction: dict[str, Any]) -> dict[str, Any]:
    from simap_agent.azure_storage import enqueue_json

    message = build_analysis_request(interaction)
    enqueue_json(ANALYSIS_QUEUE_NAME, message)
    return message
