"""Deterministic relevance scoring for SIMAP projects."""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, Iterable, List, Tuple


REASON_LABELS = {
    "Mesoneer core domain": "Digital Trust / Onboarding / Signatur",
    "Workflow/process automation": "Workflow & Prozessautomatisierung",
    "Data/AI scope": "Daten, KI oder Analytics",
    "Custom engineering/integration": "Individualsoftware / Integration",
    "Cloud/software technology fit": "Technologie-Fit",
}

RISK_LABELS = {
    "Pure license/subscription procurement": "Lizenz-/Subscription-Fokus",
    "Operations/support-heavy scope": "Betrieb/Wartung/Support stark",
    "Infrastructure/hardware scope": "Infrastruktur/Hardware-Fokus",
    "Vendor partner requirement": "Vendor-Partnerstatus/Zertifizierung prüfen",
    "Scanning/archive-only scope": "Scanning/Archivierung ohne klaren Software-Fit",
}


POSITIVE_SIGNALS: List[Tuple[str, Tuple[str, ...], int]] = [
    (
        "Mesoneer core domain",
        (
            "kyc",
            "onboarding",
            "identifikation",
            "identitaet",
            "elektronische signatur",
            "signatur",
            "digitale unterschrift",
            "digital trust",
            "trusted digital transaction",
            "digitales onboarding",
            "digitale identifikation",
            "autoident",
            "videoident",
            "qes",
            "e-id",
            "digital credentials",
            "digitale nachweise",
            "smart data",
            "fraud prevention",
            "compliance check",
            "compliancecheck",
        ),
        3,
    ),
    (
        "Workflow/process automation",
        (
            "workflow",
            "case management",
            "prozessautomatisierung",
            "prozess automation",
            "dynamische formulare",
            "dynamische vertrage",
            "dynamische verträge",
            "bpmn",
            "camunda",
            "axon ivy",
            "flowable",
            "rpa",
            "power automate",
        ),
        3,
    ),
    (
        "Data/AI scope",
        (
            "datenplattform",
            "data platform",
            "data engineering",
            "data streaming",
            "data governance",
            "analytics",
            "machine learning",
            "genai",
            "kuenstliche intelligenz",
            "kunstliche intelligenz",
            "künstliche intelligenz",
            "ki-anwendung",
            "ai-anwendung",
            "ki-agent",
            "ai agent",
        ),
        3,
    ),
    (
        "Custom engineering/integration",
        (
            "individualsoftware",
            "fachapplikation",
            "softwareentwicklung",
            "entwicklung",
            "integration",
            "systemintegration",
            "schnittstelle",
            "api",
            "api gateway",
            "migration",
            "plattform",
            "legacy",
            "modernisierung",
            "modernization",
        ),
        2,
    ),
    (
        "Cloud/software technology fit",
        (
            "azure",
            "python",
            "java",
            "kafka",
            "kafka connect",
            "kafka streams",
            "apache flink",
            "event sourcing",
            "cqrs",
            "event-driven",
            "ereignisgesteuert",
            "cloud",
            "microservice",
            "container",
        ),
        1,
    ),
]


NEGATIVE_SIGNALS: List[Tuple[str, Tuple[str, ...], int]] = [
    (
        "Pure license/subscription procurement",
        (
            "subscription",
            "subscriptions",
            "lizenz",
            "lizenzen",
            "lizenzierung",
            "softwarepaket",
            "standardsoftware",
            "reseller",
        ),
        -3,
    ),
    (
        "Operations/support-heavy scope",
        (
            "wartung",
            "support",
            "betrieb",
            "managed service",
            "service desk",
            "hosting",
        ),
        -2,
    ),
    (
        "Infrastructure/hardware scope",
        (
            "hardware",
            "drucker",
            "telefonie",
            "netzwerk",
            "server",
            "storage",
            "arbeitsplatz",
            "clients",
        ),
        -3,
    ),
    (
        "Vendor partner requirement",
        (
            "partner status",
            "premier tier",
            "zertifikat",
            "zertifizierung",
            "autorisiert",
        ),
        -2,
    ),
    (
        "Scanning/archive-only scope",
        (
            "scanning",
            "scan",
            "archivierung",
            "akten",
            "physisches archiv",
        ),
        -2,
    ),
]


def project_text(detail: Dict[str, Any], enriched: Dict[str, Any] | None = None) -> str:
    """Return a normalized text corpus for project relevance checks."""
    parts: List[str] = []

    def collect(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            parts.append(value)
            return
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
            return
        if isinstance(value, list):
            for item in value:
                collect(item)

    collect(detail)
    if enriched:
        collect(enriched.get("summary"))
        collect(enriched.get("project"))

    text = " ".join(parts)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = text.lower()
    return re.sub(r"\s+", " ", text).strip()


def _matches(text: str, patterns: Iterable[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def relevance_adjustment(detail: Dict[str, Any], enriched: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate score adjustment, reasons, and disqualifiers."""
    text = project_text(detail, enriched)
    reasons: List[str] = []
    disqualifiers: List[str] = []
    adjustment = 0

    for label, patterns, points in POSITIVE_SIGNALS:
        if _matches(text, patterns):
            reasons.append(label)
            adjustment += points

    for label, patterns, points in NEGATIVE_SIGNALS:
        if _matches(text, patterns):
            disqualifiers.append(label)
            adjustment += points

    return {
        "score_adjustment": adjustment,
        "fit_reasons": reasons,
        "disqualifiers": disqualifiers,
    }


def apply_relevance_adjustment(detail: Dict[str, Any], enriched: Dict[str, Any]) -> Dict[str, Any]:
    """Apply deterministic relevance checks to an LLM-enriched project."""
    result = dict(enriched)
    base_score = int(result.get("apply_score") or 0)
    adjustment = relevance_adjustment(detail, result)
    adjusted_score = max(1, min(10, base_score + adjustment["score_adjustment"]))
    adjusted_score = _apply_caps(adjusted_score, adjustment["fit_reasons"], adjustment["disqualifiers"])

    result["raw_apply_score"] = base_score
    result["apply_score"] = adjusted_score
    result["score_adjustment"] = adjustment["score_adjustment"]
    result["fit_reasons"] = _dedupe(
        list(result.get("fit_reasons") or []) + adjustment["fit_reasons"]
    )
    result["disqualifiers"] = _dedupe(
        list(result.get("disqualifiers") or []) + adjustment["disqualifiers"]
    )
    result["fit_reason_labels"] = _map_labels(result["fit_reasons"], REASON_LABELS)
    result["risk_labels"] = _map_labels(result["disqualifiers"], RISK_LABELS)
    result["recommendation"] = _recommendation(adjusted_score, result["risk_labels"])
    result["decision_note"] = _decision_note(result)
    return result


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _map_labels(values: Iterable[str], labels: Dict[str, str]) -> List[str]:
    return _dedupe(labels.get(value, value) for value in values)


def _recommendation(score: int, risks: List[str]) -> str:
    if score >= 8:
        return "Top-Fit"
    if score >= 6:
        return "Pruefen"
    if risks:
        return "Eher nicht"
    return "Niedrige Prioritaet"


def _decision_note(result: Dict[str, Any]) -> str:
    score = int(result.get("apply_score") or 0)
    reasons = result.get("fit_reason_labels") or []
    risks = result.get("risk_labels") or []
    if score >= 8 and reasons:
        return f"Starker Fit wegen {', '.join(reasons[:2])}."
    if score >= 6:
        note = "Interessant, aber bitte kurz pruefen"
        if risks:
            note += f": {', '.join(risks[:2])}."
        elif reasons:
            note += f": {', '.join(reasons[:2])}."
        else:
            note += "."
        return note
    if risks:
        return f"Wahrscheinlich nicht relevant wegen {', '.join(risks[:2])}."
    return "Wenig klare Mesoneer-Signale gefunden."


def _apply_caps(score: int, fit_reasons: List[str], disqualifiers: List[str]) -> int:
    """Prevent weak-fit procurement types from passing due to broad IT terms."""
    disqualifier_set = set(disqualifiers)
    fit_reason_set = set(fit_reasons)

    if {
        "Pure license/subscription procurement",
        "Operations/support-heavy scope",
    }.issubset(disqualifier_set) and not (
        "Workflow/process automation" in fit_reason_set
        or "Data/AI scope" in fit_reason_set
        or "Mesoneer core domain" in fit_reason_set
    ):
        score = min(score, 4)

    if "Infrastructure/hardware scope" in disqualifier_set:
        score = min(score, 4)

    if (
        "Scanning/archive-only scope" in disqualifier_set
        and "Data/AI scope" not in fit_reason_set
        and "Mesoneer core domain" not in fit_reason_set
    ):
        score = min(score, 5)

    return score
