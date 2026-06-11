"""Utility functions for posting formatted messages to Slack."""

import logging
import json
from datetime import datetime
from typing import Any, Dict, List

import requests

from simap_agent import config
from simap_agent.slack_interaction import (
    INTERESTING_ACTION_ID,
    NOT_INTERESTING_ACTION_ID,
)

logger = logging.getLogger(__name__)

MAX_SECTION_TEXT = 2900


def fmt_date(value: str | None, fmt: str) -> str:
    """Return formatted date or fallback."""
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime(fmt)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").strftime(fmt)
        except ValueError:
            return value


def truncate_text(value: str, limit: int = MAX_SECTION_TEXT) -> str:
    """Return text capped to Slack section limits."""
    if len(value) <= limit:
        return value
    return value[: limit - 20].rstrip() + "\n... gekuerzt"


def join_items(items: List[str], limit: int = 4) -> str:
    """Return a compact comma-separated list for Slack."""
    if not items:
        return "Keine"
    return ", ".join(str(item) for item in items[:limit])


def format_button_value(pr: Dict[str, Any]) -> str:
    """Return compact project metadata for Slack interaction payloads."""
    return json.dumps(
        {
            "project_id": pr.get("projectId") or pr.get("id"),
            "project_number": pr.get("projectNumber"),
            "offer_deadline": pr.get("offerDeadline"),
            "qna_deadline": pr.get("qna_deadline"),
            "contract_start": pr.get("contract_start"),
        },
        separators=(",", ":"),
    )


def format_slack_blocks(proj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return Slack blocks for a project dictionary."""
    team = proj.get("team")
    pr = proj.get("project", {})
    title = pr.get("title_de", "-")
    customer = pr.get("customer", "-")
    score = proj.get("apply_score", 0)
    summary = proj.get("summary", "-")
    project_number = pr.get("projectNumber", "-")
    project_id = pr.get("projectId", "-")
    offer_dl_raw = pr.get("offerDeadline")
    start_raw = pr.get("contract_start")
    qa_dl_raw = pr.get("qna_deadline")
    cpv = pr.get("cpvCode", {}) or {}
    cpv_code = cpv.get("code", "-")
    cpv_label = cpv.get("label_de", "-")
    missing = proj.get("missing_info") or []
    fit_reasons = proj.get("fit_reason_labels") or proj.get("fit_reasons") or []
    risk_labels = proj.get("risk_labels") or proj.get("disqualifiers") or []
    document_insights = proj.get("document_insights") or []
    recommendation = proj.get("recommendation") or "Pruefen"
    decision_note = proj.get("decision_note")

    offer_dl = fmt_date(offer_dl_raw, "%d.%m.%Y")
    qa_dl = fmt_date(qa_dl_raw, "%d.%m.%Y")
    start = fmt_date(start_raw, "%d.%m.%Y")

    main_text = (
        f"\n:rocket: *Team: {team}*  *#{project_number}*\n"
        f"\n:file_folder: *Projekt:* {title} / {customer}\n"
        f"\n:star: *Fit:* *{score}/10*   *{recommendation}*\n"
        f"\n:page_facing_up: *Zusammenfassung:*\n>{summary}\n\n"
        f":calendar:   -   *Q&A:* {qa_dl}   -   *Frist:* {offer_dl}   -   *Start:* {start}\n"
        f"\n:pushpin: *CPV:* `{cpv_code}` - {cpv_label}\n"
    )

    if decision_note:
        main_text += f"\n:dart: *Einschaetzung:* {decision_note}\n"
    if fit_reasons:
        main_text += f"\n:white_check_mark: *Fit-Signale:* {join_items(fit_reasons)}\n"
    if risk_labels:
        main_text += f"\n:warning: *Risiken/Abzuege:* {join_items(risk_labels)}\n"
    if document_insights:
        main_text += f"\n:bookmark: *Dokumente/Kriterien:* {join_items(document_insights, 5)}\n"
    if missing:
        main_text += f"\n:mag: *Fehlende Infos:* {join_items(missing, 6)}\n"

    criteria_text = _criteria_text(proj)

    blocks = [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": truncate_text(main_text)}},
    ]
    if criteria_text:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": truncate_text(criteria_text)},
            }
        )
    blocks.extend(
        [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"<https://www.simap.ch/de/project-detail/{project_id}#ausschreibung"
                            "|Vollstaendige Ausschreibung>"
                        ),
                    }
                ],
            },
            {
                "type": "actions",
                "block_id": f"simap_project_actions_{project_number}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Interessant", "emoji": True},
                        "style": "primary",
                        "value": format_button_value(pr),
                        "action_id": INTERESTING_ACTION_ID,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Nicht interessant",
                            "emoji": True,
                        },
                        "style": "danger",
                        "value": format_button_value(pr),
                        "action_id": NOT_INTERESTING_ACTION_ID,
                    },
                ],
            },
            {"type": "divider"},
        ]
    )
    return blocks


def _criteria_text(proj: Dict[str, Any]) -> str:
    text = ""
    qual_summary = proj.get("qualificationCriteriaSummary")
    qual = proj.get("qualificationCriteria") or []
    qual_in_docs = _truthy_flag(proj.get("qualificationCriteriaInDocuments"))
    qual_as_pdf = _truthy_flag(proj.get("qualificationCriteriaAsPDF"))

    if qual_summary:
        text += f"\n:bookmark_tabs: *Eignungskriterien:*\n{qual_summary}\n"
    elif qual:
        text += ":bookmark_tabs: *Eignungskriterien:*"
        for criteria in qual:
            title = (criteria.get("title") or {}).get("de")
            if not title:
                continue
            desc = (criteria.get("description") or {}).get("de") or ""
            text += f"\n- *{title}*"
            if desc:
                text += f" - {desc}"
        text += "\n"
    elif qual_as_pdf:
        text += ":bookmark_tabs: *Eignungskriterien:*\nKriterien sind als PDF hinterlegt\n"
    elif qual_in_docs:
        text += ":bookmark_tabs: *Eignungskriterien:*\nKriterien sind in den Dokumenten hinterlegt\n"

    award_summary = proj.get("awardCriteriaSummary")
    award = proj.get("awardCriteria") or []
    award_in_docs = _truthy_flag(proj.get("awardCriteriaInDocuments"))
    award_as_pdf = _truthy_flag(proj.get("awardCriteriaAsPDF"))

    if award_summary:
        text += f"\n:trophy: *Zuschlagskriterien:*\n{award_summary}\n"
    elif award:
        text += ":trophy: *Zuschlagskriterien:*"
        for criteria in award:
            title = (criteria.get("title") or {}).get("de")
            if not title:
                continue
            weight = criteria.get("weighting")
            text += f"\n- *{title}*"
            if weight is not None:
                text += f" - Gewichtung {weight}%"
        text += "\n"
    elif award_as_pdf:
        text += ":trophy: *Zuschlagskriterien:*\nKriterien sind als PDF hinterlegt\n"
    elif award_in_docs:
        text += ":trophy: *Zuschlagskriterien:*\nKriterien sind in den Dokumenten hinterlegt\n"

    return text.strip()


def _truthy_flag(value: Any) -> bool:
    if value is True:
        return True
    if not isinstance(value, str):
        return False
    return value.lower() in {"yes", "true", "criteria_in_documents", "criteria_as_pdf"}


def post_blocks(blocks: List[Dict[str, Any]]) -> None:
    """Send Slack message blocks."""
    logger.debug("Sending Slack blocks")
    fallback = ""
    for block in blocks:
        if block.get("type") == "section" and block.get("text"):
            fallback = block["text"].get("text", "")
            break
    payload = {"text": fallback[:150], "blocks": blocks}
    response = requests.post(
        config.SLACK_WEBHOOK_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    logger.debug("Slack response status: %s", response.status_code)
    response.raise_for_status()


def post_message(text: str) -> None:
    logger.debug("Sending Slack message")
    response = requests.post(config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    logger.debug("Slack response status: %s", response.status_code)
    response.raise_for_status()
