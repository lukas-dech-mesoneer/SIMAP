"""Functions that call OpenAI to enrich SIMAP project data."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from openai import AzureOpenAI

from simap_agent import config
from simap_agent.relevance import apply_relevance_adjustment

logger = logging.getLogger(__name__)

openai_client = AzureOpenAI(
    api_key=config.OPENAI_API_KEY,
    azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
    api_version=config.OPENAI_API_VERSION,
    timeout=60.0,
)


def summarize_criteria(criteria: List[Dict[str, Any]], name: str) -> str:
    """Return short German bullet summary for criteria via OpenAI."""
    if not criteria:
        return ""
    logger.debug("Summarizing %s via OpenAI", name)
    resp = openai_client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": f"""Fasse die folgenden {name} in kurzen Stichpunkten auf deutsch zusammen. 
                Eignungskriterien und Zuschlagskriterien sollten in jeweils weniger als 300 Zeichen zusammengefasst werden.
                Mache es so kurz wie möglich, sodass ein erste Überblick gewährt wird fasse es gerne sinnhaft zusammen.
                Verwende KEIN Markdown oder HTML, sondern nur reinen Text es kann ansonten leider nicht angezeigt werden.
                Sollten mehr Infos nötig sein Schreibe in deiner Nachricht das weitere Kriterien auf SIMAP zu finden sind"""
            },
            {"role": "user", "content": json.dumps(criteria, ensure_ascii=False, indent=2)},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

ENRICH_FUNC = [
    {
        "name": "enrich_project",
        "description": (
            "Analysiere ein SIMAP-Projekt: kurze Zusammenfassung, deutsche Felder extrahieren, "
            "Team zuordnen (Products, Engineering, Data&AI), "
            "Apply-Score 1-10 vergeben (1=klar irrelevant, 5=unklar/extern, 6=prüfenswert mit Engineering-Anteil, "
            "7-8=guter Fit, 9-10=sehr starker Fit; max. 5 wenn Kriterien nur extern einsehbar, max. 4 bei reiner Lizenz-/Supportbeschaffung), "
            "fehlende Felder als MissingInfo auflisten."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "project": {
                    "type": "object",
                    "properties": {
                        "title_de": {"type": "string"},
                        "customer": {"type": "string"},
                        "location": {"type": "string"},
                        "projectNumber": {"type": "string"},
                        "projectId": {"type": "string"},
                        "publicationDate": {"type": "string"},
                        "offerDeadline": {"type": "string"},
                        "contract_start": {"type": "string"},
                        "qna_deadline": {"type": "string"},
                        "cpvCode": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "label_de": {"type": "string"},
                            },
                            "required": ["code", "label_de"],
                        },
                    },
                    "required": [
                        "qna_deadline",
                        "title_de",
                        "customer",
                        "location",
                        "projectId",
                        "publicationDate",
                        "offerDeadline",
                        "contract_start",
                        "cpvCode",
                        "projectNumber",
                    ],
                },
                "team": {"type": "string", "enum": ["Products", "Engineering", "Data&AI"]},
                "apply_score": {"type": "integer"},
                "fit_reasons": {"type": "array", "items": {"type": "string"}},
                "disqualifiers": {"type": "array", "items": {"type": "string"}},
                "missing_info": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["summary", "project", "team", "apply_score", "missing_info"],
        },
    }
]


TARGET_KEYS = [
    "title_de",
    "customer",
    "location",
    "publicationDate",
    "offerDeadline",
    "contract_start",
    "cpvCode",
    "qna_deadline",
    "projectId",
]

# Mapping of keys to human readable labels that should be
# reported as missing information in Slack. Only these
# entries are considered when building the "missing_info"
# list.
MISSING_INFO_FIELDS = {
    "projectId": "ID",
    "qna_deadline": "Q&A",
    "qualificationCriteria": "Eignungskriterien",
    "awardCriteria": "Zuschlagskriterien",
}


def _flag_enabled(value: Any) -> bool:
    if value is True:
        return True
    if not isinstance(value, str):
        return False
    return value.lower() in {"yes", "true", "criteria_in_documents", "criteria_as_pdf"}


def _build_document_insights(detail: Dict[str, Any], data: Dict[str, Any]) -> List[str]:
    insights: List[str] = []
    criteria_block = detail.get("criteria") or {}

    if detail.get("hasProjectDocuments") is True:
        insights.append("Projektunterlagen auf SIMAP vorhanden")

    if _flag_enabled(data.get("qualificationCriteriaInDocuments")):
        insights.append("Eignungskriterien liegen in den Unterlagen")
    if _flag_enabled(data.get("qualificationCriteriaAsPDF")):
        insights.append("Eignungskriterien liegen als PDF vor")
    if _flag_enabled(data.get("awardCriteriaInDocuments")):
        insights.append("Zuschlagskriterien liegen in den Unterlagen")
    if _flag_enabled(data.get("awardCriteriaAsPDF")):
        insights.append("Zuschlagskriterien liegen als PDF vor")

    qual_count = len(data.get("qualificationCriteria") or [])
    award_count = len(data.get("awardCriteria") or [])
    if qual_count:
        insights.append(f"{qual_count} Eignungskriterien direkt extrahiert")
    if award_count:
        insights.append(f"{award_count} Zuschlagskriterien direkt extrahiert")

    if criteria_block.get("qualificationCriteriaSelection") == "criteria_in_documents":
        insights.append("Eignung muss in Dokumenten geprüft werden")
    if criteria_block.get("awardCriteriaSelection") == "criteria_in_documents":
        insights.append("Zuschlag muss in Dokumenten geprüft werden")

    return list(dict.fromkeys(insights))


def enrich(detail: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single project using OpenAI."""
    system_content = (
        "Du bist RFP-Analyst fuer Mesoneer AG. Analysiere streng und vergib den Apply-Score nach dieser Skala:\n"
        "1-2 = klar nicht relevant (falsche Branche, Hardware, reine Infrastruktur)\n"
        "3-4 = schwacher Fit (Lizenz-/Subscription-Beschaffung, reine Wartung/Betrieb/Support)\n"
        "5   = unklar oder grenzwertig (Kriterien extern, Leistungsumfang nicht beurteilbar)\n"
        "6   = prüfenswert mit konkretem Entwicklungs- oder Integrationsanteil\n"
        "7-8 = guter Fit (Softwareentwicklung, Workflow-Automatisierung, Data/AI, Digitalisierung klar beschrieben)\n"
        "9-10 = sehr starker Fit mit mehreren nachgewiesenen Mesoneer-Kernkompetenzen\n\n"
        "Mesoneer-Kernkompetenzen (Hinweis fuer Score 7+):\n"
        "- Digital Trust: elektronische Signatur, eID, KYC, Onboarding, Identitaet\n"
        "- Workflow/BPM: Prozessautomatisierung, Camunda, Axon Ivy, RPA, UiPath, Low-Code\n"
        "- Data & AI: Datenplattform, Data Engineering, Datenarchitektur, KI-Anwendung, Anonymisierung\n"
        "- Custom Engineering: Individualsoftware, Systemintegration, Fachapplikation, API-Integration\n"
        "- Bevorzugte Branchen: Finanzdienstleistungen, Versicherung, Gesundheitswesen, öffentliche Verwaltung\n\n"
        "Strikte Regeln:\n"
        "- Score 7+ nur wenn mind. eine Kernkompetenz als expliziter Leistungsbestandteil beschrieben ist.\n"
        "- Sind Leistungsumfang, Eignungs- und Zuschlagskriterien nur in externen Unterlagen: max. Score 5.\n"
        "- Reine Lizenz-, Subscription-, Hardware-, Hosting-, Betriebs- oder Supportbeschaffungen: max. Score 4.\n"
        "- Vendor-Partnerstufen oder Zertifizierungen als Muss-Kriterium: Score reduzieren.\n"
        "- Personalleasing oder reine Strategieberatung ohne Umsetzungsverantwortung: max. Score 3.\n"
        "Gib kurze fit_reasons und disqualifiers zur Score-Begruendung aus."
    )
    logger.debug("Calling OpenAI for project %s", detail.get("id"))
    resp = openai_client.chat.completions.create(
        model=config.AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": "PROJECT_JSON =\n"
                + json.dumps(detail, ensure_ascii=False, indent=2)
                + "\n\nCOMPANY_PROFILE =\n"
                + json.dumps(profile, ensure_ascii=False, indent=2),
            },
        ],
        functions=ENRICH_FUNC,
        function_call={"name": "enrich_project"},
        temperature=0.2,
    )
    args = resp.choices[0].message.function_call.arguments
    logger.debug("OpenAI response received for project %s", detail.get("id"))
    data = json.loads(args)
    proj = data.get("project", {})
    for k in TARGET_KEYS:
        proj.setdefault(k, None)

    # Collect qualification and award criteria from top level, lots or criteria block
    criteria_block = detail.get("criteria") or {}

    qual = detail.get("qualificationCriteria") or criteria_block.get("qualificationCriteria") or []
    if not qual:
        for lot in detail.get("lots", []):
            lot_criteria = lot.get("criteria") or {}
            qual.extend(lot.get("qualificationCriteria") or lot_criteria.get("qualificationCriteria") or [])

    qual_in_docs = detail.get("qualificationCriteriaInDocuments")
    if qual_in_docs is None:
        qual_in_docs = criteria_block.get("qualificationCriteriaInDocuments")

    qual_as_pdf = detail.get("qualificationCriteriaAsPDF")
    if qual_as_pdf is None:
        qual_as_pdf = criteria_block.get("qualificationCriteriaAsPDF")

    qual_sel = criteria_block.get("qualificationCriteriaSelection")
    if qual_sel == "criteria_in_documents":
        qual_in_docs = True
    elif qual_sel == "criteria_as_pdf":
        qual_as_pdf = True

    qual_note = criteria_block.get("qualificationCriteriaNote") or detail.get("qualificationCriteriaNote")
    if qual_in_docs is not None:
        data["qualificationCriteriaInDocuments"] = qual_in_docs
    if qual_as_pdf is not None:
        data["qualificationCriteriaAsPDF"] = qual_as_pdf
    if qual:
        data["qualificationCriteria"] = qual
        data["qualificationCriteriaSummary"] = summarize_criteria(qual, "Eignungskriterien")
    elif qual_note:
        # use German note as summary if present
        summary = (qual_note.get("de") or "").strip()
        if summary:
            data["qualificationCriteriaSummary"] = summary

    award = detail.get("awardCriteria") or criteria_block.get("awardCriteria") or []
    if not award:
        for lot in detail.get("lots", []):
            lot_criteria = lot.get("criteria") or {}
            award.extend(lot.get("awardCriteria") or lot_criteria.get("awardCriteria") or [])

    award_in_docs = detail.get("awardCriteriaInDocuments")
    if award_in_docs is None:
        award_in_docs = criteria_block.get("awardCriteriaInDocuments")

    award_as_pdf = detail.get("awardCriteriaAsPDF")
    if award_as_pdf is None:
        award_as_pdf = criteria_block.get("awardCriteriaAsPDF")

    award_sel = criteria_block.get("awardCriteriaSelection")
    if award_sel == "criteria_in_documents":
        award_in_docs = True
    elif award_sel == "criteria_as_pdf":
        award_as_pdf = True

    award_note = criteria_block.get("awardCriteriaNote") or detail.get("awardCriteriaNote")
    if award_in_docs is not None:
        data["awardCriteriaInDocuments"] = award_in_docs
    if award_as_pdf is not None:
        data["awardCriteriaAsPDF"] = award_as_pdf
    if award:
        data["awardCriteria"] = award
        data["awardCriteriaSummary"] = summarize_criteria(award, "Zuschlagskriterien")
    elif award_note:
        summary = (award_note.get("de") or "").strip()
        if summary:
            data["awardCriteriaSummary"] = summary


    # Build missing_info list only from fields we expect in Slack.
    missing: List[str] = []
    # project-level checks
    if not proj.get("projectId"):
        missing.append(MISSING_INFO_FIELDS["projectId"])
    if not proj.get("qna_deadline"):
        missing.append(MISSING_INFO_FIELDS["qna_deadline"])
    # qualification criteria
    if not (
        data.get("qualificationCriteria")
        or data.get("qualificationCriteriaInDocuments")
        or data.get("qualificationCriteriaAsPDF")
        or data.get("qualificationCriteriaSummary")
    ):
        missing.append(MISSING_INFO_FIELDS["qualificationCriteria"])
    # award criteria
    if not (
        data.get("awardCriteria")
        or data.get("awardCriteriaInDocuments")
        or data.get("awardCriteriaAsPDF")
        or data.get("awardCriteriaSummary")
    ):
        missing.append(MISSING_INFO_FIELDS["awardCriteria"])

    data["missing_info"] = missing
    data["document_insights"] = _build_document_insights(detail, data)

    return apply_relevance_adjustment(detail, data)


def enrich_batch(details: List[Dict[str, Any]], profile: Dict[str, Any], max_workers: int = 3) -> List[Dict[str, Any]]:
    """Run :func:`enrich` for a list of project details in parallel."""
    results: List[Any] = [None] * len(details)

    def _enrich_one(index: int, detail: Dict[str, Any]) -> tuple:
        logger.info("Enriching project %s", detail.get("id"))
        return index, enrich(detail, profile)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_enrich_one, i, d): i for i, d in enumerate(details)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                idx, result = future.result()
                results[idx] = result
            except Exception:
                logger.exception("Failed to enrich project %s — skipping", details[i].get("id"))

    return [r for r in results if r is not None]
