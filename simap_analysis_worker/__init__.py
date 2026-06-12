"""Azure Functions queue worker for SIMAP detail analysis."""

import base64
import json
import logging

import azure.functions as func

from simap_agent.detail_analysis import (
    post_analysis_result,
    run_detail_analysis,
    save_analysis_result,
    update_analysis_request_message,
    update_analysis_status_started,
)


def main(msg: func.QueueMessage) -> None:
    """Run detail analysis for a queued Slack request."""
    request = _parse_queue_message(msg)
    logging.info("Starting SIMAP detail analysis: %s", request)
    try:
        started = update_analysis_status_started(request)
        logging.info("Analysis started status update sent: %s", started)
    except Exception:
        logging.exception("Could not update analysis status to started")
    try:
        analysis = run_detail_analysis(request)
    except Exception as exc:
        logging.exception("Could not generate SIMAP detail analysis")
        analysis = {
            "title": f"SCOTSMAN Bid-Qualifizierung Projekt #{request.get('project_number') or request.get('project_id') or 'unbekannt'}",
            "decision": "ACTION REQUIRED",
            "total_score": 0,
            "decision_reason": f"Detailanalyse fehlgeschlagen: {type(exc).__name__}.",
            "scorecard": [],
            "internal_evidence": [],
            "contacts": [],
            "next_steps": ["Logs pruefen und Analyse erneut starten."],
        }
    posted = False
    report_links = {}
    try:
        report_links = save_analysis_result(request, analysis, posted)
    except Exception:
        logging.exception("Could not save SIMAP detail analysis reports")
    try:
        posted = post_analysis_result(request, analysis, report_links)
    except Exception:
        logging.exception("Could not post SIMAP detail analysis to Slack")
    try:
        report_links = save_analysis_result(request, analysis, posted, report_links)
    except Exception:
        logging.exception("Could not update SIMAP detail analysis metadata")
    try:
        updated = update_analysis_request_message(request, posted)
        logging.info("SIMAP analysis request message updated: %s", updated)
    except Exception:
        logging.exception("Could not update SIMAP analysis request message")
    logging.info("SIMAP detail analysis completed. Slack posted: %s", posted)


def _parse_queue_message(msg: func.QueueMessage) -> dict:
    raw = msg.get_body().decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
