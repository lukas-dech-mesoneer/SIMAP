"""Load configuration from the environment."""

import json
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env only for local development. Azure Functions sets FUNCTIONS_WORKER_RUNTIME.
if not os.getenv("FUNCTIONS_WORKER_RUNTIME"):
    load_dotenv(override=True)
    logging.debug("Environment variables loaded from .env file for local development.")

logger.debug("Environment variables loaded")

# Base URL and endpoints for SIMAP
SIMAP_BASE_URL = os.getenv("SIMAP_BASE_URL", "https://simap.ch")
SIMAP_SEARCH_ENDPOINT = os.getenv(
    "SIMAP_SEARCH_ENDPOINT", "/api/publications/v2/project/project-search"
)
SIMAP_DETAIL_ENDPOINT_TEMPLATE = os.getenv(
    "SIMAP_DETAIL_ENDPOINT_TEMPLATE",
    "/api/publications/v1/project/{projectId}/publication-details/{publicationId}",
)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
AZURE_OPENAI_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://dataai-opai-openai-weu-001.cognitiveservices.azure.com/",
)

OPENAI_API_VERSION = os.getenv("OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_OPENAI_DEPLOYMENT = os.getenv(
    "AZURE_OPENAI_DEPLOYMENT",
    os.getenv("OPENAI_MODEL", "gpt-5"),
)
COMPANY_PROFILE_FILE = os.getenv("COMPANY_PROFILE_FILE", "company_profile.json")
INTERNAL_REFERENCE_PACK_FILE = os.getenv(
    "INTERNAL_REFERENCE_PACK_FILE", "internal_reference_pack.md"
)
CPV_CODES = os.getenv("CPV_CODES", "48000000,72000000").split(",")
APPLY_SCORE_THRESHOLD = int(os.getenv("APPLY_SCORE_THRESHOLD", "6"))

_default_posted_projects_file = "posted_projects.json"
if os.getenv("FUNCTIONS_WORKER_RUNTIME") and os.getenv("HOME"):
    _default_posted_projects_file = os.path.join(
        os.getenv("HOME", ""), "data", "posted_projects.json"
    )
POSTED_PROJECTS_FILE = os.getenv("POSTED_PROJECTS_FILE", _default_posted_projects_file)
DEDUPLICATION_SCOPE = os.getenv("DEDUPLICATION_SCOPE", "project")
POSTED_PROJECTS_RETENTION_DAYS = int(os.getenv("POSTED_PROJECTS_RETENTION_DAYS", "365"))
REPOST_ALREADY_POSTED = os.getenv("REPOST_ALREADY_POSTED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
POST_BELOW_THRESHOLD = os.getenv("POST_BELOW_THRESHOLD", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
logger.debug("Slack webhook configured: %s", bool(SLACK_WEBHOOK_URL))

try:
    with open(COMPANY_PROFILE_FILE, "r", encoding="utf-8") as f:
        COMPANY_PROFILE = json.load(f)
    logger.debug("Company profile loaded from %s", COMPANY_PROFILE_FILE)
except FileNotFoundError:
    logger.warning("Company profile file %s not found", COMPANY_PROFILE_FILE)
    COMPANY_PROFILE = {}

_required = {
    "SLACK_WEBHOOK_URL": SLACK_WEBHOOK_URL,
    "OPENAI_API_KEY": OPENAI_API_KEY,
}
_missing = [key for key, value in _required.items() if not value]
if _missing:
    raise EnvironmentError(f"Missing environment variables: {', '.join(_missing)}")
