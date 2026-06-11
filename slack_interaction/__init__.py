"""Azure Functions HTTP trigger for Slack button interactions."""

import json
import logging

import azure.functions as func

from simap_agent.analysis_queue import build_analysis_request
from simap_agent.slack_interaction import (
    START_ANALYSIS_ACTION_ID,
    interaction_ack_text,
    parse_interaction_payload,
    verify_slack_signature,
)


def main(
    req: func.HttpRequest,
    interactionEvent: func.Out[str],
    analysisRequest: func.Out[str],
) -> func.HttpResponse:
    """Acknowledge Slack quickly and move all side effects to queues."""
    body = req.get_body()
    timestamp = req.headers.get("X-Slack-Request-Timestamp")
    signature = req.headers.get("X-Slack-Signature")

    if not verify_slack_signature(body, timestamp, signature):
        logging.warning("Rejected Slack interaction with invalid signature")
        return func.HttpResponse("Invalid Slack signature", status_code=401)

    try:
        interaction = parse_interaction_payload(body)
    except (ValueError, json.JSONDecodeError):
        logging.exception("Invalid Slack interaction payload")
        return func.HttpResponse("Invalid Slack payload", status_code=400)

    action_id = interaction.get("action_id")
    project = interaction.get("project") or {}
    logging.info(
        "Slack interaction received: action_id=%s project=%s user=%s",
        action_id,
        project,
        (interaction.get("user") or {}).get("id"),
    )

    if action_id == START_ANALYSIS_ACTION_ID:
        message = build_analysis_request(interaction)
        analysisRequest.set(json.dumps(message, separators=(",", ":")))
        logging.info("Queued SIMAP analysis request: %s", message)
    else:
        interactionEvent.set(json.dumps(interaction, separators=(",", ":")))
        logging.info("Queued Slack interaction event")

    return _ack_response(action_id, project)


def _ack_response(action_id: str | None, project: dict) -> func.HttpResponse:
    response = {
        "response_type": "ephemeral",
        "text": interaction_ack_text(action_id, project),
    }
    return func.HttpResponse(
        json.dumps(response, separators=(",", ":")),
        status_code=200,
        mimetype="application/json",
    )
