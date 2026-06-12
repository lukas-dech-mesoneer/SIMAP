"""Deterministic relevance scoring for SIMAP projects."""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, Iterable, List, Tuple


REASON_LABELS = {
    "Mesoneer core domain": "Digital Trust / KYC / eSignatur",
    "Workflow/process automation": "Workflow & Prozessautomatisierung",
    "Data/AI scope": "Daten, KI oder Datenarchitektur",
    "Custom engineering/integration": "Individualsoftware / Integration",
    "Cloud/software technology fit": "Technologie-Fit",
    "Preferred industry context": "Bevorzugte Branche",
}

RISK_LABELS = {
    "Pure license/subscription procurement": "Lizenz-/Subscription-Fokus",
    "Operations/support-heavy scope": "Betrieb/Wartung-lastig",
    "Infrastructure/hardware scope": "Infrastruktur/Hardware-Fokus",
    "Vendor partner requirement": "Vendor-Partnerstatus prüfen",
    "Scanning/archive-only scope": "Scanning/Archivierung ohne Software-Fit",
    "Staff leasing or generic consulting": "Personalleasing / reine Beratung",
    "Scope only in documents": "Scope/Kriterien nur in Unterlagen",
}


POSITIVE_SIGNALS: List[Tuple[str, Tuple[str, ...], int]] = [
    (
        # Highly specific Mesoneer products and core capabilities.
        # "signatur" and "onboarding" removed — too broad in German.
        "Mesoneer core domain",
        (
            # Identity & KYC
            "kyc",
            "identifikation",
            "digitale identifikation",
            "identitaet",
            "autoident",
            "videoident",
            "qes",
            "e-id",
            "eid",
            # Electronic signature (specific forms only)
            "elektronische signatur",
            "e-signatur",
            "qualifizierte signatur",
            "digitale unterschrift",
            "signaturloesung",
            # Digital trust
            "digital trust",
            "trusted digital transaction",
            "vertrauensdienste",
            "digitale vertrauensdienste",
            # Digital onboarding (specific)
            "digitales onboarding",
            "kundenonboarding",
            "customer journey",
            "digitale kundenjourneys",
            "digitale kundenbeziehung",
            # Digital credentials / smart data
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
            "dynamische vertraege",
            "dynamische verträge",
            "bpmn",
            "camunda",
            "axon ivy",
            "flowable",
            "rpa",
            "uipath",
            "power automate",
            "low-code",
            "lowcode",
            "no-code",
            "nocode",
        ),
        3,
    ),
    (
        # "analytics" removed — too broad (Excel dashboards also match).
        "Data/AI scope",
        (
            "datenplattform",
            "data platform",
            "data engineering",
            "datenarchitektur",
            "data architecture",
            "data streaming",
            "data governance",
            "machine learning",
            "genai",
            "kuenstliche intelligenz",
            "kunstliche intelligenz",
            "kuenstlicher intelligenz",
            "künstliche intelligenz",
            "ki-anwendung",
            "ai-anwendung",
            "ki-agent",
            "ai agent",
            "ki-gestützt",
            "ki-basiert",
            "anonymisierung",
            "echtzeitdaten",
            "echtzeit-daten",
            "real-time data",
        ),
        3,
    ),
    (
        # "entwicklung", "api", "plattform", "integration" removed — appear in nearly every IT tender.
        # Use specific compound terms instead.
        "Custom engineering/integration",
        (
            "individualsoftware",
            "fachapplikation",
            "softwareentwicklung",
            "applikationsentwicklung",
            "systemintegration",
            "schnittstelle",
            "schnittstellen",
            "api gateway",
            "api-integration",
            "api-entwicklung",
            "datenmigration",
            "applikationsmigration",
            "softwaremigration",
            "legacy",
            "modernisierung",
            "modernization",
        ),
        2,
    ),
    (
        # Generic tech stack — only specific tools, not broad terms like "cloud", "java", "python".
        "Cloud/software technology fit",
        (
            "azure",
            "kafka",
            "kafka connect",
            "kafka streams",
            "apache flink",
            "event sourcing",
            "cqrs",
            "event-driven",
            "ereignisgesteuert",
            "microservice",
            "kubernetes",
        ),
        1,
    ),
    (
        # Preferred client sectors give a small bonus — not a deal-maker but a tie-breaker.
        # "versicherung" alone omitted — substring-matches boilerplate like "Versicherungsnachweis".
        "Preferred industry context",
        (
            "finanzdienstleistungen",
            "banken",
            "versicherungsunternehmen",
            "krankenversicherung",
            "krankenkasse",
            "gesundheitswesen",
            "spital",
            "klinik",
            "regulierte branche",
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
            "volumenlizenz",
        ),
        -3,
    ),
    (
        # "support" removed — often a minor clause in otherwise valid projects.
        # "scan" removed — "security scan" / "vulnerability scan" can be Mesoneer-relevant.
        "Operations/support-heavy scope",
        (
            "wartung",
            "betrieb",
            "managed service",
            "service desk",
            "hosting",
            "servicevertrag",
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
        # "zertifizierung" removed — ambiguous (digital certification processes can be Mesoneer-relevant).
        # "autorisiert" removed — too rare and ambiguous.
        "Vendor partner requirement",
        (
            "partner status",
            "premier tier",
            "zertifikat als muss",
            "partnerschaftsnachweis",
        ),
        -2,
    ),
    (
        "Scanning/archive-only scope",
        (
            "scanning",
            "archivierung",
            "akten",
            "physisches archiv",
            "dokumentenlogistik",
        ),
        -2,
    ),
    (
        "Staff leasing or generic consulting",
        (
            "personalleasing",
            "personalvermittlung",
            "arbeitnehmerueberlassung",
            "zeitarbeit",
            "ressourcenvermittlung",
            "strategieberatung ohne umsetzung",
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
    positive_adj = 0
    negative_adj = 0

    for label, patterns, points in POSITIVE_SIGNALS:
        if _matches(text, patterns):
            reasons.append(label)
            positive_adj += points

    for label, patterns, points in NEGATIVE_SIGNALS:
        if _matches(text, patterns):
            disqualifiers.append(label)
            negative_adj += points

    if _scope_only_in_documents(detail, enriched):
        disqualifiers.append("Scope only in documents")
        negative_adj -= 1

    # Cap positive stacking at +4 so keyword abundance can't push a weak project to 10.
    # Negative signals are not capped — a clear no-go should always pull the score down.
    adjustment = min(positive_adj, 4) + negative_adj

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
    return _dedupe(labels[value] for value in values if value in labels)


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


_STRONG_FIT_SIGNALS = {
    "Mesoneer core domain",
    "Workflow/process automation",
    "Data/AI scope",
    "Custom engineering/integration",
}


def _apply_caps(score: int, fit_reasons: List[str], disqualifiers: List[str]) -> int:
    """Prevent weak-fit procurement types from passing due to broad IT terms."""
    disqualifier_set = set(disqualifiers)
    fit_reason_set = set(fit_reasons)
    has_strong_fit = bool(_STRONG_FIT_SIGNALS & fit_reason_set)
    has_delivery_fit = bool(
        {
            "Mesoneer core domain",
            "Workflow/process automation",
            "Data/AI scope",
        }
        & fit_reason_set
    )

    if not has_strong_fit:
        score = min(score, 6)

    # Procurement-only: cap at 5 even without operations signal.
    # Requires a concrete engineering/AI/core-domain signal to exceed this.
    if "Pure license/subscription procurement" in disqualifier_set:
        score = min(score, 6 if has_delivery_fit else 4)

    # Procurement + operations with no engineering counter-signal: hard cap at 4.
    if {
        "Pure license/subscription procurement",
        "Operations/support-heavy scope",
    }.issubset(disqualifier_set):
        score = min(score, 4)

    if "Infrastructure/hardware scope" in disqualifier_set:
        score = min(score, 4)

    if "Vendor partner requirement" in disqualifier_set and not has_delivery_fit:
        score = min(score, 4)

    if "Staff leasing or generic consulting" in disqualifier_set and not has_delivery_fit:
        score = min(score, 5)

    if "Scope only in documents" in disqualifier_set and not has_delivery_fit:
        score = min(score, 5)

    if (
        "Scanning/archive-only scope" in disqualifier_set
        and "Data/AI scope" not in fit_reason_set
        and "Mesoneer core domain" not in fit_reason_set
    ):
        score = min(score, 5)

    return score


def _scope_only_in_documents(detail: Dict[str, Any], enriched: Dict[str, Any]) -> bool:
    """Return True when SIMAP exposes criteria/scope only via external documents."""
    criteria = detail.get("criteria") or {}
    document_flags = (
        detail.get("qualificationCriteriaInDocuments"),
        detail.get("awardCriteriaInDocuments"),
        criteria.get("qualificationCriteriaInDocuments"),
        criteria.get("awardCriteriaInDocuments"),
        criteria.get("qualificationCriteriaSelection") == "criteria_in_documents",
        criteria.get("awardCriteriaSelection") == "criteria_in_documents",
        enriched.get("qualificationCriteriaInDocuments"),
        enriched.get("awardCriteriaInDocuments"),
    )
    has_direct_criteria = bool(
        detail.get("qualificationCriteria")
        or detail.get("awardCriteria")
        or criteria.get("qualificationCriteria")
        or criteria.get("awardCriteria")
        or enriched.get("qualificationCriteria")
        or enriched.get("awardCriteria")
    )
    return any(value is True for value in document_flags) and not has_direct_criteria
