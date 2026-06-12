"""Client helpers for retrieving project data from SIMAP."""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from simap_agent import config

logger = logging.getLogger(__name__)


def call(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Perform a GET request against the SIMAP API."""
    url = f"{config.SIMAP_BASE_URL}{endpoint}"
    logger.debug("Requesting %s with params %s", url, params)
    try:
        resp = requests.get(url, params=params, timeout=10)
        logger.debug("Response status: %s", resp.status_code)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Request to %s failed: %s", url, exc)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON from %s: %s", url, exc)
    return None


def fetch_project_summaries(cpv: List[str], lang: str = "de", max_pages: int = 100) -> List[Dict[str, Any]]:
    """Return recent project summaries filtered by CPV codes."""
    logger.info("Fetching project summaries")
    summaries: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        params = {
            "lang": lang,
            "processTypes": "open",
            "cpvCodes": cpv,
            "newestPublicationFrom": (datetime.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
        }
        if cursor:
            params["lastItem"] = cursor
        logger.debug("Calling summary search page with cursor %s", cursor)
        data = call(config.SIMAP_SEARCH_ENDPOINT, params)
        if not data or "projects" not in data:
            break
        projects = data["projects"]
        summaries.extend(projects)
        pagination = data.get("pagination", {}) or {}
        cursor = pagination.get("lastItem")
        if not cursor or len(projects) < pagination.get("itemsPerPage", len(projects)):
            break
    logger.info("Fetched %d project summaries", len(summaries))
    return summaries


def fetch_project_details(summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch detail information for the given project summaries."""
    logger.info("Fetching details for %d projects", len(summaries))
    details: List[Dict[str, Any]] = []
    for s in summaries:
        pub_type = (s.get("pubType") or "").lower()
        if pub_type not in ("tender", "advance_notice"):
            logger.debug("Skipping project %s with pubType %s", s.get("id"), pub_type)
            continue

        pid = s.get("id")
        pub = s.get("publicationId")
        if not pid or not pub:
            continue

        logger.debug("Fetching detail for project %s", pid)
        endpoint = config.SIMAP_DETAIL_ENDPOINT_TEMPLATE.format(projectId=pid, publicationId=pub)
        data = call(endpoint)
        if data:
            data.setdefault("_simap_project_id", pid)
            data.setdefault("_simap_publication_id", pub)
            details.append(data)
        else:
            logger.warning("No detail returned for project %s", pid)
        time.sleep(0.5)

    logger.info("Fetched details for %d/%d projects", len(details), len(summaries))
    return details
