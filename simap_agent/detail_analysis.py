"""Generate and post deeper SIMAP project analysis."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

from simap_agent import config
from simap_agent.analysis_report import (
    normalize_analysis,
    render_docx_report,
    render_html_report,
    slack_summary_text,
)
from simap_agent.azure_storage import blob_read_url, put_blob_bytes, put_json_blob
from simap_agent.enricher import openai_client
from simap_agent.project_store import load_project_context

ANALYSIS_RESULT_CONTAINER = "simap-analysis-results"


def run_detail_analysis(request: dict[str, Any]) -> dict[str, Any]:
    """Return a structured German analysis for a queued SIMAP project."""
    project_id = request.get("project_id")
    if not project_id:
        logger.warning("run_detail_analysis: no project_id in request %s", request)
        return _missing_context_analysis(request)
    context = load_project_context(project_id)
    if not context:
        logger.warning("run_detail_analysis: no context found for project_id=%s", project_id)
        return _missing_context_analysis(request)

    report_request = _request_with_context_metadata(request, context)
    internal_reference_pack = _load_internal_reference_pack()
    prompt = _build_analysis_prompt(context, internal_reference_pack)
    response = openai_client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "Du bist Senior Bid Manager und RFP Analyst fuer Mesoneer. "
                    "Bewerte streng, konkret und handlungsorientiert auf Deutsch. "
                    "Nutze nur die gegebenen Projektdaten und markiere Unsicherheiten klar."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content.strip()
    try:
        parsed = _parse_analysis_json(content)
    except (json.JSONDecodeError, ValueError):
        parsed = {
            "title": f"SCOTSMAN Bid-Qualifizierung Projekt #{report_request.get('project_number') or project_id}",
            "decision": "ACTION REQUIRED",
            "total_score": 0,
            "decision_reason": "Die Analyse konnte nicht strukturiert geparst werden; bitte Report manuell pruefen.",
            "scorecard": [],
            "internal_evidence": [],
            "contacts": [],
            "next_steps": [content[:1200]],
        }
    return normalize_analysis(parsed, report_request)


def post_analysis_result(
    request: dict[str, Any],
    analysis: dict[str, Any] | str,
    report_links: dict[str, str] | None = None,
) -> bool:
    """Post analysis result to the Slack thread."""
    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = request.get("slack_channel_id")
    thread_ts = request.get("slack_thread_ts")
    if not token or not channel_id or not thread_ts:
        return False

    report = normalize_analysis(analysis, _request_with_context_metadata(request))
    text = _truncate_for_slack(slack_summary_text(report, report_links))
    payload = {
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {data.get('error')}")
    return True


def save_analysis_result(
    request: dict[str, Any],
    analysis: dict[str, Any] | str,
    slack_posted: bool,
    report_links: dict[str, str] | None = None,
) -> dict[str, str]:
    """Persist an analysis result for audit/debugging."""
    project_id = request.get("project_id") or "unknown"
    report_request = _request_with_context_metadata(request)
    report = normalize_analysis(analysis, report_request)
    base_name = f"{project_id}"
    links = dict(report_links or {})

    html_blob_name = f"{base_name}.html"
    put_blob_bytes(
        ANALYSIS_RESULT_CONTAINER,
        html_blob_name,
        render_html_report(report).encode("utf-8"),
        "text/html; charset=utf-8",
    )
    links["html_url"] = blob_read_url(ANALYSIS_RESULT_CONTAINER, html_blob_name)

    docx_data = render_docx_report(report)
    if docx_data:
        docx_blob_name = f"{base_name}.docx"
        put_blob_bytes(
            ANALYSIS_RESULT_CONTAINER,
            docx_blob_name,
            docx_data,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        links["docx_url"] = blob_read_url(ANALYSIS_RESULT_CONTAINER, docx_blob_name)

    put_json_blob(
        ANALYSIS_RESULT_CONTAINER,
        f"{base_name}.json",
        {
            "request": request,
            "report_request": report_request,
            "analysis": report,
            "slack_posted": slack_posted,
            "report_links": links,
        },
    )
    return links


def update_analysis_status_started(request: dict[str, Any]) -> bool:
    """Update the 'Analyse starten' button message to show analysis is running.

    Preserves the original 'X findet Projekt interessant' context and removes
    the button so users cannot trigger a duplicate analysis.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = request.get("slack_channel_id")
    message_ts = request.get("slack_message_ts")
    if not token or not channel_id or not message_ts:
        return False

    text = _analysis_status_text(request, ":hourglass_flowing_sand: Analyse laeuft ... (ca. 2-3 Minuten)")
    return _slack_update_message(token, channel_id, message_ts, text)


def update_analysis_request_message(request: dict[str, Any], analysis_posted: bool) -> bool:
    """Update the analysis prompt message with the final status (no button)."""
    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = request.get("slack_channel_id")
    message_ts = request.get("slack_message_ts")
    if not token or not channel_id or not message_ts:
        return False

    if analysis_posted:
        status = ":white_check_mark: Detailanalyse abgeschlossen — Ergebnisse sind als Antwort gepostet."
    else:
        status = ":warning: Analyse verarbeitet, konnte aber nicht in Slack gepostet werden. Bitte Logs pruefen."
    text = _analysis_status_text(request, status)
    return _slack_update_message(token, channel_id, message_ts, text)


def _analysis_status_text(request: dict[str, Any], status_line: str) -> str:
    """Build a status message that preserves the 'X findet Projekt interessant' header."""
    user_id = request.get("slack_user_id")
    project_number = request.get("project_number") or request.get("project_id") or "unbekannt"
    actor = f"<@{user_id}>" if user_id else "Jemand"
    return f"{actor} findet Projekt *#{project_number}* interessant.\n{status_line}"


def _slack_update_message(token: str, channel_id: str, message_ts: str, text: str) -> bool:
    payload = {
        "channel": channel_id,
        "ts": message_ts,
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }
    response = requests.post(
        "https://slack.com/api/chat.update",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.update failed: {data.get('error')}")
    return True


def _load_internal_reference_pack() -> str:
    path = Path(config.INTERNAL_REFERENCE_PACK_FILE)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _build_analysis_prompt(context: dict[str, Any], internal_reference_pack: str = "") -> str:
    internal_context = (
        internal_reference_pack.strip()
        if internal_reference_pack.strip()
        else "Kein interner Referenz-Pack vorhanden. Interne Referenzen und Ansprechpartner als offene Punkte markieren."
    )
    return (
        "Erstelle eine knappe, entscheidungsorientierte Bid-Analyse fuer dieses SIMAP Projekt.\n"
        "Keine Einleitung, kein allgemeines Bla-bla, keine langen Erklaerungen. Maximal 2200 Zeichen.\n\n"
        "Bewerte exakt nach dem Mesoneer SCOTSMAN Standardprozess. "
        "Jedes Kriterium wird anhand der aktuell verfuegbaren Evidenz und vordefinierter Standards mit 0 bis 4 bewertet.\n\n"
        "Bewertungsskala:\n"
        "0 = No-Go / keine tragfaehige Evidenz / klarer schlechter Fit\n"
        "1 = sehr schwach / hohes Risiko / nur mit starken Korrekturmassnahmen\n"
        "2 = unklar oder mittel / relevante offene Punkte\n"
        "3 = gut / glaubwuerdig mit ueberschaubaren Risiken\n"
        "4 = sehr stark / klare Evidenz und hoher Fit\n\n"
        "SCOTSMAN Kriterien und Standardfragen:\n"
        "S Solution: Do we have a credible solution that meets the requirement?\n"
        "C Competition: How do we stack up against the competition? Who are they?\n"
        "O Originality: Do we have a unique proposition that the customer likes?\n"
        "T Timescales: Are the timescales for the bid manageable for us?\n"
        "S Size: Is the opportunity the right size (not too big, not too small)?\n"
        "M Money: Can we price our solution within the customer's budget?\n"
        "A Authority: Do we know who makes the selection decision, and how?\n"
        "N Need: Does the customer have a burning need for a solution?\n\n"
        "Entscheidungsregeln:\n"
        "- GO: Gesamtpunktzahl 22+.\n"
        "- NO-GO: eine Bewertung von 0 oder 1 in einem Bereich ODER Gesamtpunktzahl <16.\n"
        "- ACTION REQUIRED: Gesamtpunktzahl 16-21, mit konkreten naechsten Aktionen.\n\n"
        "Antworte ausschliesslich als valides JSON ohne Markdown-Fence. Schema:\n"
        "{\n"
        '  "title": "SCOTSMAN Bid-Qualifizierung ...",\n'
        '  "decision": "GO|NO-GO|ACTION REQUIRED",\n'
        '  "total_score": 0,\n'
        '  "decision_reason": "ein knapper Satz",\n'
        '  "scorecard": [\n'
        '    {"letter":"S","criterion":"Solution","description":"Credible solution?","score":0,"risk":"sehr hoch|hoch|mittel|niedrig","comment":"kurz"}\n'
        "  ],\n"
        '  "internal_evidence": ["max. 3 Referenzen mit Quelle/Link/Person"],\n'
        '  "contacts": [{"name":"Name","role":"Rolle","reason":"warum anfragen"}],\n'
        '  "next_steps": ["max. 3 konkrete Aktionen"]\n'
        "}\n\n"
        "Die scorecard muss exakt 8 Eintraege enthalten: Solution, Competition, Originality, Timescales, Size, Money, Authority, Need.\n"
        "Regeln fuer interne Informationen:\n"
        "- Erfinde keine Referenzen, Links, Kunden, Personen oder Skills.\n"
        "- Nutze INTERNAL_REFERENCE_PACK am Ende fuer Interne Evidenz und Ansprechpartner.\n"
        "- Wenn der interne Referenz-Pack nur TODO/Platzhalter oder keine passende Evidenz enthaelt, schreibe 'keine belastbare interne Evidenz gefunden'.\n"
        "- Verwende interne Ansprechpartner nur, wenn sie im Referenz-Pack vorkommen oder direkt aus einer Referenz ableitbar sind.\n\n"
        "COMPANY_PROFILE=\n"
        + json.dumps(config.COMPANY_PROFILE, ensure_ascii=False, indent=2)
        + "\n\nINTERNAL_REFERENCE_PACK=\n"
        + internal_context
        + "\n\nPROJECT_CONTEXT=\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def _parse_analysis_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def _request_with_context_metadata(
    request: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill report deadline metadata from saved project context when Slack payload lacks it."""
    result = dict(request)
    if all(result.get(key) for key in ("offer_deadline", "qna_deadline", "contract_start")):
        return result

    project_id = result.get("project_id")
    if context is None and project_id:
        context = load_project_context(project_id)
    if not isinstance(context, dict):
        return result

    project = (context.get("enriched") or {}).get("project") or {}
    detail = context.get("detail") or {}
    fallbacks = {
        "offer_deadline": project.get("offerDeadline") or detail.get("offerDeadline"),
        "qna_deadline": project.get("qna_deadline") or detail.get("qna_deadline"),
        "contract_start": project.get("contract_start") or detail.get("contract_start"),
    }
    for key, value in fallbacks.items():
        if value and not result.get(key):
            result[key] = value
    return result


def _missing_context_analysis(request: dict[str, Any]) -> dict[str, Any]:
    project_number = request.get("project_number") or request.get("project_id") or "unbekannt"
    return {
        "title": f"SCOTSMAN Bid-Qualifizierung Projekt #{project_number}",
        "decision": "ACTION REQUIRED",
        "total_score": 0,
        "decision_reason": (
            "Kein gespeicherter Projektkontext gefunden. "
            "Bitte Ausschreibung erneut posten und dann 'Analyse starten' klicken."
        ),
        "scorecard": [],
        "internal_evidence": [],
        "contacts": [],
        "next_steps": ["Ausschreibung erneut posten, dann 'Analyse starten' klicken."],
    }


def _truncate_for_slack(text: str, limit: int = 2900) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 30].rstrip() + "\n... gekuerzt"
