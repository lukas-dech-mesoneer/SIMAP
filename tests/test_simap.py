"""Basic tests for the SIMAP agent functions."""

import os
import json
import sys
import hashlib
import hmac
from urllib.parse import quote
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime, timezone
from types import SimpleNamespace
import importlib

# Ensure required env vars for config
os.environ.setdefault("SLACK_WEBHOOK_URL", "http://example.com")
os.environ.setdefault("OPENAI_API_KEY", "dummy")
os.environ.setdefault(
    "AZURE_OPENAI_ENDPOINT",
    "https://dataai-opai-openai-weu-001.cognitiveservices.azure.com/",
)
os.environ.setdefault("OPENAI_API_VERSION", "2025-01-01-preview")
os.environ.setdefault("APPLY_SCORE_THRESHOLD", "7")

import simap_agent.config as config
importlib.reload(config)

import simap_agent.main as main

import simap_agent.slack_client as slack_client
import simap_agent.simap_client as simap_client
import simap_agent.enricher as enricher
import simap_agent.posted_store as posted_store
import simap_agent.relevance as relevance
import simap_agent.slack_interaction as slack_interaction
import simap_agent.feedback_store as feedback_store
import simap_agent.detail_analysis as detail_analysis
import simap_agent.analysis_report as analysis_report
from simap_agent.analysis_queue import build_analysis_request
from simap_analysis_worker import _parse_queue_message
import slack_interaction as slack_http


def test_format_slack_blocks_basic():
    proj = {
        "team": "Engineering",
        "project": {
            "title_de": "Projekt",
            "customer": "Kunde",
            "projectNumber": "123",
            "projectId": "abc",
            "offerDeadline": "2024-12-31",
            "contract_start": "2025-01-15",
            "qna_deadline": "2024-12-01",
            "cpvCode": {"code": "48000000", "label_de": "Software"},
        },
        "apply_score": 7,
        "summary": "Kurzfassung",
        "missing_info": [],
    }
    blocks = slack_client.format_slack_blocks(proj)
    assert any(b.get("type") == "section" for b in blocks)
    assert any(b.get("type") == "context" for b in blocks)
    section_text = next(b for b in blocks if b.get("type") == "section")["text"]["text"]
    assert "Projekt" in section_text
    assert "Engineering" in section_text
    assert "Fehlende Infos" not in section_text
    assert "7/10" in section_text
    assert "Pruefen" in section_text
    actions = next(b for b in blocks if b.get("type") == "actions")
    assert [e["action_id"] for e in actions["elements"]] == [
        slack_interaction.INTERESTING_ACTION_ID,
        slack_interaction.NOT_INTERESTING_ACTION_ID,
    ]
    value = json.loads(actions["elements"][0]["value"])
    assert value == {
        "project_id": "abc",
        "project_number": "123",
        "offer_deadline": "2024-12-31",
        "qna_deadline": "2024-12-01",
        "contract_start": "2025-01-15",
    }


def test_format_slack_blocks_missing_info():
    proj = {
        "team": "Engineering",
        "project": {
            "title_de": "Projekt",
            "customer": "Kunde",
            "projectNumber": "123",
            "projectId": "abc",
            "offerDeadline": "2024-12-31",
            "contract_start": "2025-01-15",
            "qna_deadline": "2024-12-01",
            "cpvCode": {"code": "48000000", "label_de": "Software"},
        },
        "apply_score": 7,
        "summary": "Kurzfassung",
        "missing_info": ["Ort"],
    }
    blocks = slack_client.format_slack_blocks(proj)
    section_text = next(b for b in blocks if b.get("type") == "section")["text"]["text"]
    assert "Fehlend: Ort" in section_text


def test_format_slack_blocks_relevance_and_document_hints():
    proj = {
        "team": "Engineering",
        "project": {
            "title_de": "Workflow",
            "customer": "Kunde",
            "projectNumber": "123",
            "projectId": "abc",
            "cpvCode": {"code": "72000000", "label_de": "IT"},
        },
        "apply_score": 8,
        "raw_apply_score": 7,
        "score_adjustment": 1,
        "recommendation": "Top-Fit",
        "decision_note": "Starker Fit wegen Workflow.",
        "fit_reason_labels": ["Workflow & Prozessautomatisierung"],
        "risk_labels": ["Vendor-Partnerstatus/Zertifizierung prüfen"],
        "document_insights": ["Projektunterlagen auf SIMAP vorhanden"],
        "summary": "Kurzfassung",
        "missing_info": [],
    }

    blocks = slack_client.format_slack_blocks(proj)
    section_text = next(b for b in blocks if b.get("type") == "section")["text"]["text"]

    assert "Top-Fit" in section_text
    assert "LLM" not in section_text
    assert "Regel" not in section_text
    assert "Workflow & Prozessautomatisierung" in section_text
    assert "Projektunterlagen auf SIMAP vorhanden" in section_text
    assert "Vendor-Partnerstatus" in section_text


def test_verify_slack_signature_accepts_valid_request():
    body = b'payload={"type":"block_actions"}'
    timestamp = "1700000000"
    secret = "secret"
    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    signature = "v0=" + hmac.new(
        secret.encode("utf-8"),
        base,
        hashlib.sha256,
    ).hexdigest()

    assert slack_interaction.verify_slack_signature(
        body,
        timestamp,
        signature,
        signing_secret=secret,
        now=1700000000,
    )


def test_parse_interaction_payload_extracts_action_and_project():
    payload = {
        "actions": [
            {
                "action_id": slack_interaction.INTERESTING_ACTION_ID,
                "value": json.dumps({"project_id": "abc", "project_number": "123"}),
            }
        ],
        "user": {"id": "U1"},
        "channel": {"id": "C1"},
    }
    body = ("payload=" + quote(json.dumps(payload))).encode("utf-8")

    result = slack_interaction.parse_interaction_payload(body)

    assert result["action_id"] == slack_interaction.INTERESTING_ACTION_ID
    assert result["project"] == {"project_id": "abc", "project_number": "123"}
    assert result["user"] == {"id": "U1"}


def test_interaction_ack_text_mentions_decision():
    text = slack_interaction.interaction_ack_text(
        slack_interaction.NOT_INTERESTING_ACTION_ID,
        {"project_number": "123"},
    )

    assert "nicht interessant" in text
    assert "#123" in text


def test_feedback_store_writes_local_jsonl(monkeypatch, tmp_path):
    feedback_file = tmp_path / "feedback.jsonl"
    monkeypatch.setenv("SIMAP_FEEDBACK_FILE", str(feedback_file))
    interaction = {
        "action_id": slack_interaction.INTERESTING_ACTION_ID,
        "project": {"project_id": "abc", "project_number": "123"},
        "user": {"id": "U1", "username": "lukas"},
        "channel": {"id": "C1"},
        "message": {"ts": "1700000000.000100"},
    }

    record = feedback_store.build_feedback_record(interaction)
    feedback_store.save_feedback_record(record)

    saved = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert saved["event_type"] == "interesting"
    assert saved["project_id"] == "abc"
    assert saved["slack_user_id"] == "U1"


def test_analysis_prompt_contains_start_analysis_button():
    payload = slack_interaction._analysis_prompt_payload(
        "C1",
        "1700000000.000100",
        "U1",
        {"project_id": "abc", "project_number": "123"},
    )

    assert payload["thread_ts"] == "1700000000.000100"
    action = payload["blocks"][1]["elements"][0]
    assert action["action_id"] == slack_interaction.START_ANALYSIS_ACTION_ID
    assert json.loads(action["value"]) == {
        "project_id": "abc",
        "project_number": "123",
        "_origin_channel_id": "C1",
        "_origin_thread_ts": "1700000000.000100",
    }


def test_build_analysis_request_contains_thread_context():
    interaction = {
        "project": {
            "project_id": "abc",
            "project_number": "123",
            "offer_deadline": "2024-12-31",
            "qna_deadline": "2024-12-01",
            "contract_start": "2025-01-15",
        },
        "user": {"id": "U1"},
        "channel": {"id": "C1", "name": "simap"},
        "message": {"ts": "1700000001.000200", "thread_ts": "1700000000.000100"},
    }

    message = build_analysis_request(interaction)

    assert message["project_id"] == "abc"
    assert message["project_number"] == "123"
    assert message["offer_deadline"] == "2024-12-31"
    assert message["qna_deadline"] == "2024-12-01"
    assert message["contract_start"] == "2025-01-15"
    assert message["slack_channel_id"] == "C1"
    assert message["slack_thread_ts"] == "1700000000.000100"
    assert message["slack_message_ts"] == "1700000001.000200"


def test_build_analysis_request_uses_origin_thread_context_from_button_value():
    interaction = {
        "project": {
            "project_id": "abc",
            "project_number": "123",
            "_origin_channel_id": "C1",
            "_origin_thread_ts": "1700000000.000100",
        },
        "user": {"id": "U1"},
        "channel": {},
        "message": {"ts": "1700000002.000300"},
    }

    message = build_analysis_request(interaction)

    assert message["slack_channel_id"] == "C1"
    assert message["slack_thread_ts"] == "1700000000.000100"
    assert message["slack_message_ts"] == "1700000002.000300"


def test_update_analysis_request_message_removes_buttons(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(detail_analysis.requests, "post", fake_post)

    updated = detail_analysis.update_analysis_request_message(
        {
            "project_number": "123",
            "slack_channel_id": "C1",
            "slack_message_ts": "1700000001.000200",
        },
        analysis_posted=True,
    )

    assert updated is True
    assert calls[0]["url"] == "https://slack.com/api/chat.update"
    assert calls[0]["json"]["ts"] == "1700000001.000200"
    assert calls[0]["json"]["blocks"][0]["type"] == "section"
    assert "actions" not in {block.get("type") for block in calls[0]["json"]["blocks"]}


def test_analysis_worker_parses_plain_or_base64_queue_message():
    payload = {"project_id": "abc", "slack_thread_ts": "1.2"}

    class Message:
        def __init__(self, body: bytes):
            self.body = body

        def get_body(self):
            return self.body

    assert _parse_queue_message(Message(json.dumps(payload).encode("utf-8"))) == payload
    encoded = __import__("base64").b64encode(json.dumps(payload).encode("utf-8"))
    assert _parse_queue_message(Message(encoded)) == payload


def test_slack_http_queues_interesting_event(monkeypatch):
    interaction = {
        "action_id": slack_interaction.INTERESTING_ACTION_ID,
        "project": {"project_id": "abc", "project_number": "123"},
        "user": {"id": "U1"},
        "channel": {"id": "C1"},
        "message": {"ts": "1.2"},
    }

    class Request:
        headers = {}

        def get_body(self):
            return b"body"

    class Out:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    monkeypatch.setattr(slack_http, "verify_slack_signature", lambda *args, **kwargs: True)
    monkeypatch.setattr(slack_http, "parse_interaction_payload", lambda body: interaction)
    interaction_event = Out()
    analysis_request = Out()

    response = slack_http.main(Request(), interaction_event, analysis_request)

    assert response.status_code == 200
    assert json.loads(interaction_event.value)["action_id"] == slack_interaction.INTERESTING_ACTION_ID
    assert analysis_request.value is None


def test_slack_http_queues_start_analysis_request(monkeypatch):
    interaction = {
        "action_id": slack_interaction.START_ANALYSIS_ACTION_ID,
        "project": {
            "project_id": "abc",
            "project_number": "123",
            "_origin_channel_id": "C1",
            "_origin_thread_ts": "1.2",
        },
        "user": {"id": "U1"},
        "channel": {},
        "message": {"ts": "2.3"},
    }

    class Request:
        headers = {}

        def get_body(self):
            return b"body"

    class Out:
        def __init__(self):
            self.value = None

        def set(self, value):
            self.value = value

    monkeypatch.setattr(slack_http, "verify_slack_signature", lambda *args, **kwargs: True)
    monkeypatch.setattr(slack_http, "parse_interaction_payload", lambda body: interaction)
    interaction_event = Out()
    analysis_request = Out()

    response = slack_http.main(Request(), interaction_event, analysis_request)

    queued = json.loads(analysis_request.value)
    assert response.status_code == 200
    assert interaction_event.value is None
    assert queued["project_id"] == "abc"
    assert queued["slack_channel_id"] == "C1"
    assert queued["slack_thread_ts"] == "1.2"


def test_enrich_missing_info(monkeypatch):
    detail = {"id": "1"}
    profile = {}

    fake_resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    function_call=SimpleNamespace(
                        arguments=json.dumps(
                            {
                                "summary": "s",
                                "project": {
                                    "title_de": "T",
                                    "customer": "C",
                                    "location": "L",
                                    "projectNumber": "PN",
                                    "projectId": None,
                                    "publicationDate": "2024-01-01",
                                    "offerDeadline": "2024-01-10",
                                    "contract_start": "2024-02-01",
                                    "qna_deadline": None,
                                    "cpvCode": {"code": "48000000", "label_de": "SW"},
                                },
                                "team": "Engineering",
                                "apply_score": 5,
                                "missing_info": [],
                            }
                        )
                    )
                )
            )
        ]
    )

    monkeypatch.setattr(
        enricher.openai_client.chat.completions,
        "create",
        lambda **kwargs: fake_resp,
    )
    monkeypatch.setattr(enricher, "summarize_criteria", lambda crit, name: "")

    result = enricher.enrich(detail, profile)
    assert sorted(result["missing_info"]) == [
        "Eignungskriterien",
        "ID",
        "Q&A",
        "Zuschlagskriterien",
    ]
    assert result["raw_apply_score"] == 5


def test_build_document_insights_from_simap_flags():
    detail = {
        "hasProjectDocuments": True,
        "criteria": {
            "qualificationCriteriaSelection": "criteria_in_documents",
            "awardCriteriaSelection": "criteria_in_documents",
        },
    }
    data = {
        "qualificationCriteriaInDocuments": True,
        "awardCriteriaAsPDF": True,
        "qualificationCriteria": [{"title": {"de": "Referenzen"}}],
        "awardCriteria": [{"title": {"de": "Preis"}}],
    }

    insights = enricher._build_document_insights(detail, data)

    assert "Projektunterlagen auf SIMAP vorhanden" in insights
    assert "Eignungskriterien liegen in den Unterlagen" in insights
    assert "Zuschlagskriterien liegen als PDF vor" in insights
    assert "1 Eignungskriterien direkt extrahiert" in insights


def test_relevance_adjustment_penalizes_license_support_procurement():
    detail = {
        "title": {"de": "Red Hat Subscription/Wartung und Support"},
        "description": {
            "de": "Beschaffung von Lizenzen, Wartung und Support. Anbieterin benoetigt Premier tier Partner Status."
        },
    }
    enriched = {"apply_score": 7, "summary": "Reine Subscription-Beschaffung"}

    result = relevance.apply_relevance_adjustment(detail, enriched)

    assert result["apply_score"] < 7
    assert "Pure license/subscription procurement" in result["disqualifiers"]
    assert "Operations/support-heavy scope" in result["disqualifiers"]
    assert "Vendor partner requirement" in result["disqualifiers"]


def test_relevance_adjustment_boosts_mesoneer_core_scope():
    detail = {
        "title": {"de": "Digitaler Schaden-Workflow"},
        "description": {
            "de": "Entwicklung und Integration eines Workflow mit Schnittstellen, Datenplattform und API."
        },
    }
    enriched = {"apply_score": 6, "summary": "Workflow- und Integrationsprojekt"}

    result = relevance.apply_relevance_adjustment(detail, enriched)

    assert result["apply_score"] > 6
    assert "Workflow/process automation" in result["fit_reasons"]
    assert "Custom engineering/integration" in result["fit_reasons"]


def test_relevance_caps_generic_industry_context_below_posting_threshold():
    detail = {
        "title": {"de": "IT-Dienstleistungen fuer Krankenkasse"},
        "description": {"de": "Beratung und Betrieb einer bestehenden Standardsoftware."},
    }
    enriched = {"apply_score": 7, "summary": "Breite IT-Ausschreibung im Gesundheitswesen"}

    result = relevance.apply_relevance_adjustment(detail, enriched)

    assert result["apply_score"] < 7


def test_relevance_caps_documents_only_scope_without_delivery_fit():
    detail = {
        "title": {"de": "Digitale Plattform"},
        "criteria": {
            "qualificationCriteriaSelection": "criteria_in_documents",
            "awardCriteriaSelection": "criteria_in_documents",
        },
    }
    enriched = {
        "apply_score": 7,
        "summary": "Leistungsumfang und Kriterien sind den Unterlagen zu entnehmen.",
    }

    result = relevance.apply_relevance_adjustment(detail, enriched)

    assert result["apply_score"] <= 5
    assert "Scope only in documents" in result["disqualifiers"]


def test_fetch_project_summaries_pagination(monkeypatch):
    pages = [
        {
            "projects": [{"id": "1"}],
            "pagination": {"lastItem": "cursor1", "itemsPerPage": 1},
        },
        {
            "projects": [{"id": "2"}],
            "pagination": {"lastItem": None, "itemsPerPage": 1},
        },
    ]
    calls = []

    def fake_call(endpoint, params=None):
        calls.append((endpoint, params))
        return pages.pop(0) if pages else None

    monkeypatch.setattr(simap_client, "call", fake_call)

    result = simap_client.fetch_project_summaries(["48000000"], max_pages=3)
    assert len(result) == 2
    assert len(calls) == 2


def test_fetch_project_details_filters(monkeypatch):
    summaries = [
        {"pubType": "tender", "id": "1", "publicationId": "p1"},
        {"pubType": "notice", "id": "2", "publicationId": "p2"},
        {"pubType": "advance_notice", "id": "3", "publicationId": "p3"},
    ]
    called = []

    def fake_call(endpoint, params=None):
        called.append(endpoint)
        return {"endpoint": endpoint}

    monkeypatch.setattr(simap_client, "call", fake_call)

    result = simap_client.fetch_project_details(summaries)
    assert len(result) == 2
    exp1 = simap_client.config.SIMAP_DETAIL_ENDPOINT_TEMPLATE.format(
        projectId="1", publicationId="p1"
    )
    exp2 = simap_client.config.SIMAP_DETAIL_ENDPOINT_TEMPLATE.format(
        projectId="3", publicationId="p3"
    )
    assert called == [exp1, exp2]
    assert result == [
        {"endpoint": exp1, "_simap_project_id": "1", "_simap_publication_id": "p1"},
        {"endpoint": exp2, "_simap_project_id": "3", "_simap_publication_id": "p3"},
    ]


def test_main_filters_apply_score(monkeypatch):
    calls = []

    monkeypatch.setattr(main.config, "POST_BELOW_THRESHOLD", False)
    monkeypatch.setattr(main, "fetch_project_summaries", lambda cpv=None: ["s"])
    monkeypatch.setattr(
        main,
        "fetch_project_details",
        lambda summaries: [
            {"projectNumber": "1"},
            {"projectNumber": "2"},
        ],
    )
    monkeypatch.setattr(
        main,
        "enrich_batch",
        lambda details, profile: [
            {"apply_score": 6, "project": {"projectNumber": "1"}},
            {"apply_score": 8, "project": {"projectNumber": "2"}},
        ],
    )
    monkeypatch.setattr(main, "format_slack_blocks", lambda data: [])
    monkeypatch.setattr(main, "post_blocks", lambda blocks: calls.append(blocks))

    main.main()

    assert len(calls) == 1


def test_main_can_post_below_threshold_in_test_mode(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(tmp_path / "posted.json"))
    monkeypatch.setattr(main.config, "POST_BELOW_THRESHOLD", True)
    monkeypatch.setattr(main, "fetch_project_summaries", lambda cpv=None: [{"id": "1"}])
    monkeypatch.setattr(main, "fetch_project_details", lambda summaries: [{"projectNumber": "1"}])
    monkeypatch.setattr(
        main,
        "enrich_batch",
        lambda details, profile: [{"apply_score": 1, "project": {"projectNumber": "1"}}],
    )
    monkeypatch.setattr(main, "format_slack_blocks", lambda data: [])
    monkeypatch.setattr(main, "post_blocks", lambda blocks: calls.append(blocks))

    main.main()

    assert len(calls) == 1


def test_main_skips_already_posted_summary(monkeypatch, tmp_path):
    posted_file = tmp_path / "posted_projects.json"
    posted_store.save_posted_keys(str(posted_file), {"1"})
    fetched = []

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(posted_file))
    monkeypatch.setattr(main.config, "REPOST_ALREADY_POSTED", False)
    monkeypatch.setattr(
        main,
        "fetch_project_summaries",
        lambda cpv=None: [
            {"id": "1", "publicationId": "p1"},
            {"id": "2", "publicationId": "p2"},
        ],
    )
    monkeypatch.setattr(main, "fetch_project_details", lambda summaries: fetched.extend(summaries) or [])
    monkeypatch.setattr(main, "enrich_batch", lambda details, profile: [])

    main.main()

    assert fetched == [{"id": "2", "publicationId": "p2"}]


def test_main_skips_duplicate_summaries_in_same_run(monkeypatch, tmp_path):
    posted_file = tmp_path / "posted_projects.json"
    fetched = []

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(posted_file))
    monkeypatch.setattr(main.config, "REPOST_ALREADY_POSTED", False)
    monkeypatch.setattr(main.config, "DEDUPLICATION_SCOPE", "project")
    monkeypatch.setattr(
        main,
        "fetch_project_summaries",
        lambda cpv=None: [
            {"id": "1", "publicationId": "p1"},
            {"id": "1", "publicationId": "p2"},
            {"id": "2", "publicationId": "p3"},
        ],
    )
    monkeypatch.setattr(main, "fetch_project_details", lambda summaries: fetched.extend(summaries) or [])
    monkeypatch.setattr(main, "enrich_batch", lambda details, profile: [])

    main.main()

    assert fetched == [
        {"id": "1", "publicationId": "p1"},
        {"id": "2", "publicationId": "p3"},
    ]


def test_main_can_repost_already_posted_summary(monkeypatch, tmp_path):
    posted_file = tmp_path / "posted_projects.json"
    posted_store.save_posted_keys(str(posted_file), {"1"})
    fetched = []

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(posted_file))
    monkeypatch.setattr(main.config, "REPOST_ALREADY_POSTED", True)
    monkeypatch.setattr(
        main,
        "fetch_project_summaries",
        lambda cpv=None: [
            {"id": "1", "publicationId": "p1"},
            {"id": "2", "publicationId": "p2"},
        ],
    )
    monkeypatch.setattr(main, "fetch_project_details", lambda summaries: fetched.extend(summaries) or [])
    monkeypatch.setattr(main, "enrich_batch", lambda details, profile: [])

    main.main()

    assert fetched == [
        {"id": "1", "publicationId": "p1"},
        {"id": "2", "publicationId": "p2"},
    ]


def test_main_marks_successfully_posted_publication(monkeypatch, tmp_path):
    posted_file = tmp_path / "posted_projects.json"

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(posted_file))
    monkeypatch.setattr(main, "fetch_project_summaries", lambda cpv=None: [{"id": "1", "publicationId": "p1"}])
    monkeypatch.setattr(
        main,
        "fetch_project_details",
        lambda summaries: [{"projectNumber": "1", "_simap_project_id": "1", "_simap_publication_id": "p1"}],
    )
    monkeypatch.setattr(
        main,
        "enrich_batch",
        lambda details, profile: [{"apply_score": 8, "project": {"projectNumber": "1"}}],
    )
    monkeypatch.setattr(main, "format_slack_blocks", lambda data: [])
    monkeypatch.setattr(main, "post_blocks", lambda blocks: None)

    main.main()

    assert posted_store.load_posted_keys(str(posted_file)) == {"1"}


def test_main_can_deduplicate_by_publication(monkeypatch, tmp_path):
    posted_file = tmp_path / "posted_projects.json"

    monkeypatch.setattr(main.config, "POSTED_PROJECTS_FILE", str(posted_file))
    monkeypatch.setattr(main.config, "DEDUPLICATION_SCOPE", "publication")
    monkeypatch.setattr(main, "fetch_project_summaries", lambda cpv=None: [{"id": "1", "publicationId": "p1"}])
    monkeypatch.setattr(
        main,
        "fetch_project_details",
        lambda summaries: [{"projectNumber": "1", "_simap_project_id": "1", "_simap_publication_id": "p1"}],
    )
    monkeypatch.setattr(
        main,
        "enrich_batch",
        lambda details, profile: [{"apply_score": 8, "project": {"projectNumber": "1"}}],
    )
    monkeypatch.setattr(main, "format_slack_blocks", lambda data: [])
    monkeypatch.setattr(main, "post_blocks", lambda blocks: None)

    main.main()

    assert posted_store.load_posted_keys(str(posted_file)) == {"1:p1"}


def test_posted_store_prunes_entries_older_than_retention():
    entries = {
        "old": "2024-12-31T00:00:00+00:00",
        "fresh": "2025-12-31T00:00:00+00:00",
        "legacy-without-date": None,
    }

    result = posted_store.prune_posted_entries(
        entries,
        retention_days=365,
        now=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert result == {
        "fresh": "2025-12-31T00:00:00+00:00",
        "legacy-without-date": None,
    }


def test_posted_store_supports_azure_blob_paths(monkeypatch):
    stored = {}

    def fake_get_json_blob(container, blob_name):
        assert container == "simap-state"
        assert blob_name == "posted_projects.json"
        return stored.get((container, blob_name))

    def fake_put_json_blob(container, blob_name, data):
        stored[(container, blob_name)] = data

    monkeypatch.setattr(posted_store, "get_json_blob", fake_get_json_blob)
    monkeypatch.setattr(posted_store, "put_json_blob", fake_put_json_blob)

    path = "azure://simap-state/posted_projects.json"
    posted_store.save_posted_keys(path, {"1", "2"})

    assert posted_store.load_posted_keys(path) == {"1", "2"}
    assert set(stored[("simap-state", "posted_projects.json")]["posted_keys"]) == {"1", "2"}


def test_posted_store_falls_back_to_legacy_azure_function_file(monkeypatch, tmp_path):
    legacy_file = tmp_path / "home" / "data" / "posted_projects.json"
    posted_store.save_posted_keys(str(legacy_file), {"legacy"})

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("POSTED_PROJECTS_LEGACY_FILE", raising=False)
    monkeypatch.setattr(posted_store, "get_json_blob", lambda container, blob_name: None)

    path = "azure://simap-state/posted_projects.json"

    assert posted_store.load_posted_keys(path) == {"legacy"}


def test_detail_analysis_prompt_includes_internal_reference_pack(tmp_path, monkeypatch):
    reference_pack = tmp_path / "internal_reference_pack.md"
    reference_pack.write_text(
        "# Internal Reference Pack\n\n## Customer And Project References\n- Reference Alpha",
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "INTERNAL_REFERENCE_PACK_FILE", str(reference_pack))
    prompt = detail_analysis._build_analysis_prompt(
        {"project_id": "abc"},
        detail_analysis._load_internal_reference_pack(),
    )

    assert "SCOTSMAN" in prompt
    assert '"score"' in prompt
    assert '"total_score"' in prompt
    assert "Reference Alpha" in prompt


def test_detail_analysis_request_metadata_falls_back_to_project_context(monkeypatch):
    context = {
        "detail": {"offerDeadline": "2026-07-21"},
        "enriched": {
            "project": {
                "offerDeadline": "2026-07-22",
                "qna_deadline": "2026-06-29",
                "contract_start": "2028-01-01",
            }
        },
    }
    monkeypatch.setattr(detail_analysis, "load_project_context", lambda project_id: context)

    request = detail_analysis._request_with_context_metadata(
        {"project_id": "abc", "project_number": "123"}
    )

    assert request["offer_deadline"] == "2026-07-22"
    assert request["qna_deadline"] == "2026-06-29"
    assert request["contract_start"] == "2028-01-01"


def test_analysis_report_renders_summary_and_html():
    report = analysis_report.normalize_analysis(
        {
            "title": "SCOTSMAN Bid-Qualifizierung Test",
            "decision": "NO-GO",
            "total_score": 10,
            "decision_reason": "Mehrere K.o.-Kriterien.",
            "scorecard": [
                {
                    "letter": "S",
                    "criterion": "Solution",
                    "description": "Credible solution?",
                    "score": 0,
                    "risk": "sehr hoch",
                    "comment": "Kein Fit.",
                }
            ],
            "internal_evidence": ["Reference Alpha"],
            "contacts": [{"name": "Nelli Arnold", "role": "Lead Sales", "reason": "Bid Check"}],
            "next_steps": ["Bid stoppen."],
        },
        {
            "offer_deadline": "2026-07-21",
            "qna_deadline": "2026-06-29",
            "contract_start": "2028-01-01",
        },
    )

    summary = analysis_report.slack_summary_text(report, {"html_url": "https://example.com/report.html"})
    html = analysis_report.render_html_report(report)

    assert "*SCOTSMAN:* NO-GO - 10/32" in summary
    assert "HTML Report" in summary
    assert "fonts.googleapis.com/css2?family=Open+Sans" in html
    assert "linear-gradient(315deg,#2E1A47" in html
    assert "class=\"decision risk\"" in html
    assert "Q&amp;A bis: 29.06.2026" in html
    assert "Frist Einreichung: 21.07.2026" in html
    assert "Start: 01.01.2028" in html
    assert "SCOTSMAN-Bewertung" in html
    assert "Score (0-4)" in html
    assert "class=\"chip s-risk\">0</span>" in html
    assert "Reference Alpha" in html
    assert "<th style=\"width:200px\">Person</th>" in html


def test_analysis_report_merges_empty_metadata_from_request():
    report = analysis_report.normalize_analysis(
        {
            "title": "SCOTSMAN Bid-Qualifizierung Test",
            "decision": "NO-GO",
            "total_score": 11,
            "decision_reason": "Klarer No-Fit.",
            "metadata": {},
        },
        {
            "offer_deadline": "2026-07-21",
            "qna_deadline": "2026-06-29",
            "contract_start": "2028-01-01",
        },
    )
    html = analysis_report.render_html_report(report)

    assert "Format: mesoneer CI" not in html
    assert "Q&amp;A bis: 29.06.2026" in html
    assert "Frist Einreichung: 21.07.2026" in html
    assert "Start: 01.01.2028" in html

