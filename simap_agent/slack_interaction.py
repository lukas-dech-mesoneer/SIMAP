"""Slack interactivity request handling."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any
from urllib.parse import parse_qs

INTERESTING_ACTION_ID = "simap_project_interesting"
NOT_INTERESTING_ACTION_ID = "simap_project_not_interesting"
START_ANALYSIS_ACTION_ID = "simap_project_start_analysis"

logger = logging.getLogger(__name__)


def verify_slack_signature(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    signing_secret: str | None = None,
    now: int | None = None,
) -> bool:
    """Return whether a request was signed by Slack."""
    secret = signing_secret or os.getenv("SLACK_SIGNING_SECRET")
    if not secret or not timestamp or not signature:
        return False

    try:
        request_ts = int(timestamp)
    except ValueError:
        return False

    current_ts = int(time.time() if now is None else now)
    if abs(current_ts - request_ts) > 60 * 5:
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    return hmac.compare_digest(expected, signature)


def parse_interaction_payload(body: bytes) -> dict[str, Any]:
    """Parse Slack's form-encoded interaction payload."""
    form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    payload_values = form.get("payload")
    if not payload_values:
        raise ValueError("Missing Slack payload")

    payload = json.loads(payload_values[0])
    actions = payload.get("actions") or []
    if not actions:
        raise ValueError("Missing Slack action")

    action = actions[0]
    value = action.get("value")
    project_value = json.loads(value) if value else {}
    return {
        "action_id": action.get("action_id"),
        "project": project_value,
        "user": payload.get("user") or {},
        "channel": payload.get("channel") or {},
        "message": payload.get("message") or {},
        "response_url": payload.get("response_url"),
    }


def interaction_ack_text(action_id: str | None, project: dict[str, Any]) -> str:
    """Return a short acknowledgement text for Slack."""
    project_number = project.get("project_number") or project.get("project_id") or "unbekannt"
    if action_id == INTERESTING_ACTION_ID:
        return f"Feedback erfasst: Projekt #{project_number} ist interessant."
    if action_id == NOT_INTERESTING_ACTION_ID:
        return f"Feedback erfasst: Projekt #{project_number} ist nicht interessant."
    if action_id == START_ANALYSIS_ACTION_ID:
        return f"Analyse fuer Projekt #{project_number} wurde gestartet. Das dauert ca. 2-3 Minuten."
    return f"Feedback erfasst: Projekt #{project_number}."


def should_post_analysis_prompt(action_id: str | None) -> bool:
    """Return whether a thread message with the analysis button should be posted."""
    return action_id == INTERESTING_ACTION_ID


def post_thread_update(interaction: dict[str, Any]) -> bool:
    """Post a Slack thread update if a bot token is configured."""
    import requests

    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        logger.warning("Skipping Slack thread update because SLACK_BOT_TOKEN is not configured")
        return False

    action_id = interaction.get("action_id")
    project = interaction.get("project") or {}
    channel_id = (interaction.get("channel") or {}).get("id")
    message_ts = (interaction.get("message") or {}).get("ts")
    user_id = (interaction.get("user") or {}).get("id")
    if not channel_id or not message_ts:
        logger.warning(
            "Skipping Slack thread update because channel_id or message_ts is missing: channel_id=%s message_ts=%s",
            channel_id,
            message_ts,
        )
        return False

    if action_id == INTERESTING_ACTION_ID:
        payload = _analysis_prompt_payload(channel_id, message_ts, user_id, project)
    elif action_id == NOT_INTERESTING_ACTION_ID:
        payload = _feedback_note_payload(
            channel_id,
            message_ts,
            f"<@{user_id}> hat dieses Projekt als *nicht interessant* markiert."
            if user_id
            else "Dieses Projekt wurde als *nicht interessant* markiert.",
        )
    elif action_id == START_ANALYSIS_ACTION_ID:
        payload = _feedback_note_payload(
            channel_id,
            message_ts,
            f"<@{user_id}> hat die Detailanalyse gestartet. Das dauert ca. 2-3 Minuten."
            if user_id
            else "Die Detailanalyse wurde gestartet. Das dauert ca. 2-3 Minuten.",
        )
    else:
        logger.warning("Skipping Slack thread update for unsupported action_id=%s", action_id)
        return False

    logger.info("Posting Slack thread update: action_id=%s channel=%s thread_ts=%s", action_id, channel_id, message_ts)
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {data.get('error')} response={data}")
    return True


def _analysis_prompt_payload(
    channel_id: str,
    thread_ts: str,
    user_id: str | None,
    project: dict[str, Any],
) -> dict[str, Any]:
    project_number = project.get("project_number") or project.get("project_id") or "unbekannt"
    actor = f"<@{user_id}>" if user_id else "Jemand"
    return {
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": f"{actor} findet Projekt #{project_number} interessant. Detailanalyse starten?",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{actor} findet Projekt *#{project_number}* interessant. Detailanalyse starten?",
                },
            },
            {
                "type": "actions",
                "block_id": f"simap_analysis_actions_{project_number}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Analyse starten", "emoji": True},
                        "style": "primary",
                        "value": json.dumps(project, separators=(",", ":")),
                        "action_id": START_ANALYSIS_ACTION_ID,
                    }
                ],
            },
        ],
    }


def _feedback_note_payload(channel_id: str, thread_ts: str, text: str) -> dict[str, Any]:
    return {
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }
