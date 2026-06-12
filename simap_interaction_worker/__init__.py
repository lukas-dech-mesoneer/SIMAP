"""Azure Functions queue worker for Slack interaction side effects."""

import base64
import json
import logging
import os
from typing import Any

import azure.functions as func
import requests

from simap_agent.feedback_store import build_feedback_record, save_feedback_record
from simap_agent.project_store import load_project_context
from simap_agent.slack_client import format_slack_blocks
from simap_agent.slack_interaction import (
    INTERESTING_ACTION_ID,
    NOT_INTERESTING_ACTION_ID,
    post_thread_update,
)


def main(msg: func.QueueMessage) -> None:
    """Persist feedback and post Slack thread updates outside Slack's 3s timeout."""
    interaction = _parse_queue_message(msg)
    logging.info(
        "Processing Slack interaction event: action_id=%s project=%s user=%s",
        interaction.get("action_id"),
        interaction.get("project"),
        (interaction.get("user") or {}).get("id"),
    )
    try:
        record = build_feedback_record(interaction)
        save_feedback_record(record)
        logging.info("Stored Slack feedback: %s", record)
    except Exception:
        logging.exception("Could not store Slack feedback")

    try:
        _replace_buttons_with_status(interaction)
    except Exception:
        logging.exception("Could not update project message to remove buttons")

    try:
        posted = post_thread_update(interaction)
        logging.info("Slack thread update posted: %s", posted)
    except Exception:
        logging.exception("Could not post Slack thread update")


def _replace_buttons_with_status(interaction: dict[str, Any]) -> bool:
    """Update the original project message: replace action buttons with a feedback status line."""
    action_id = interaction.get("action_id")
    if action_id not in (INTERESTING_ACTION_ID, NOT_INTERESTING_ACTION_ID):
        return False

    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = (interaction.get("channel") or {}).get("id")
    message_ts = (interaction.get("message") or {}).get("ts")
    if not token or not channel_id or not message_ts:
        return False

    user_id = (interaction.get("user") or {}).get("id")
    actor = f"<@{user_id}>" if user_id else "Jemand"
    if action_id == INTERESTING_ACTION_ID:
        status = f":white_check_mark: {actor}: Interessant"
    else:
        status = f":x: {actor}: Nicht interessant"

    # Rebuild blocks from stored project data, remove buttons, add status.
    project_id = (interaction.get("project") or {}).get("project_id")
    context = load_project_context(project_id) if project_id else None
    enriched = (context or {}).get("enriched")
    if enriched:
        blocks = [b for b in format_slack_blocks(enriched) if b.get("type") != "actions"]
        status_block = {"type": "context", "elements": [{"type": "mrkdwn", "text": status}]}
        # Insert status before the trailing divider.
        if blocks and blocks[-1].get("type") == "divider":
            blocks.insert(-1, status_block)
        else:
            blocks.append(status_block)
    else:
        blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": status}]}]

    payload = {"channel": channel_id, "ts": message_ts, "text": status, "blocks": blocks}
    response = requests.post(
        "https://slack.com/api/chat.update",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"chat.update failed: {data.get('error')}")
    logging.info("Project message updated: buttons replaced with feedback status")
    return True


def _parse_queue_message(msg: func.QueueMessage) -> dict:
    raw = msg.get_body().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
