"""Azure Functions queue worker for Slack interaction side effects."""

import base64
import json
import logging

import azure.functions as func

from simap_agent.feedback_store import build_feedback_record, save_feedback_record
from simap_agent.slack_interaction import post_thread_update


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
        posted = post_thread_update(interaction)
        logging.info("Slack thread update posted: %s", posted)
    except Exception:
        logging.exception("Could not post Slack thread update")


def _parse_queue_message(msg: func.QueueMessage) -> dict:
    raw = msg.get_body().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
