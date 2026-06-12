"""Utility functions for posting formatted messages to Slack."""

import logging
import json
import os
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
    fit_reasons = proj.get("fit_reason_labels") or []
    risk_labels = proj.get("risk_labels") or []
    document_insights = proj.get("document_insights") or []
    recommendation = proj.get("recommendation") or "Prüfen"

    offer_dl = fmt_date(offer_dl_raw, "%d.%m.%Y")
    qa_dl = fmt_date(qa_dl_raw, "%d.%m.%Y")
    start = fmt_date(start_raw, "%d.%m.%Y")

    date_parts = []
    if qa_dl != "-":
        date_parts.append(f"Q&A: {qa_dl}")
    if offer_dl != "-":
        date_parts.append(f"Frist: {offer_dl}")
    if start != "-":
        date_parts.append(f"Start: {start}")
    dates = " · ".join(date_parts) or "-"

    main_text = (
        f":rocket: *#{project_number} · {team}*\n"
        f"*{title}*\n"
        f"{customer}\n"
        f"\n:star: *{score}/10 — {recommendation}*\n"
        f"{truncate_text(summary, 500)}\n"
        f"\n:calendar: {dates}\n"
        f":pushpin: `{cpv_code}` {cpv_label}\n"
    )

    if fit_reasons:
        main_text += f"\n:white_check_mark: {' · '.join(fit_reasons[:3])}\n"
    if risk_labels:
        main_text += f":warning: {' · '.join(risk_labels[:3])}\n"
    if document_insights:
        main_text += f":bookmark: {', '.join(document_insights[:3])}\n"
    if missing:
        main_text += f":mag: Fehlend: {', '.join(missing[:4])}\n"

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
    parts = []

    qual_summary = proj.get("qualificationCriteriaSummary")
    qual = proj.get("qualificationCriteria") or []

    qual_lines = []
    for c in qual:
        title = (c.get("title") or {}).get("de")
        if not title:
            continue
        desc = (c.get("description") or {}).get("de") or ""
        line = f"- *{title}*"
        if desc:
            line += f" - {desc}"
        qual_lines.append(line)

    if qual_lines:
        parts.append(":bookmark_tabs: *Eignungskriterien:*\n" + "\n".join(qual_lines))
    elif qual_summary and not _is_external_reference(qual_summary):
        parts.append(f":bookmark_tabs: *Eignungskriterien:*\n{qual_summary}")

    award_summary = proj.get("awardCriteriaSummary")
    award = proj.get("awardCriteria") or []

    award_lines = []
    for c in award:
        title = (c.get("title") or {}).get("de")
        if not title:
            continue
        weight = c.get("weighting")
        line = f"- *{title}*"
        if weight is not None:
            line += f" - Gewichtung {weight}%"
        award_lines.append(line)

    if award_lines:
        parts.append(":trophy: *Zuschlagskriterien:*\n" + "\n".join(award_lines))
    elif award_summary and not _is_external_reference(award_summary):
        parts.append(f":trophy: *Zuschlagskriterien:*\n{award_summary}")

    return "\n\n".join(parts)


def _is_external_reference(text: str) -> bool:
    """Return True when criteria text just points to an external document."""
    t = text.lower()
    return "http" in t or "suisseoffer" in t or t.startswith("siehe")


def post_blocks(blocks: List[Dict[str, Any]]) -> None:
    """Send Slack message blocks.

    Uses chat.postMessage (bot token) when SLACK_CHANNEL_ID is configured — this
    allows the message to be updated later (e.g. to remove buttons after a click).
    Falls back to the incoming webhook when SLACK_CHANNEL_ID is absent.
    """
    token = os.getenv("SLACK_BOT_TOKEN")
    channel_id = config.SLACK_CHANNEL_ID
    if token and channel_id:
        _post_blocks_bot(token, channel_id, blocks)
    else:
        _post_blocks_webhook(blocks)


def _post_blocks_bot(token: str, channel_id: str, blocks: List[Dict[str, Any]]) -> None:
    fallback = next(
        (b["text"]["text"][:150] for b in blocks if b.get("type") == "section" and b.get("text")),
        "",
    )
    payload = {"channel": channel_id, "text": fallback, "blocks": blocks, "unfurl_links": False, "unfurl_media": False}
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {data.get('error')}")
    logger.debug("Posted via bot token, ts=%s", data.get("ts"))


def _post_blocks_webhook(blocks: List[Dict[str, Any]]) -> None:
    fallback = next(
        (b["text"]["text"][:150] for b in blocks if b.get("type") == "section" and b.get("text")),
        "",
    )
    payload = {"text": fallback, "blocks": blocks}
    response = requests.post(
        config.SLACK_WEBHOOK_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    logger.debug("Slack webhook response status: %s", response.status_code)
    response.raise_for_status()


