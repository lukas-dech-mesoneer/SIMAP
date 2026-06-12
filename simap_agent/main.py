"""Entry point for running the SIMAP pipeline."""

import logging
import os
import sys

# Ensure package imports work when executed directly
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from simap_agent import config
from simap_agent.simap_client import fetch_project_summaries, fetch_project_details
from simap_agent.enricher import enrich_batch
from simap_agent.posted_store import deduplication_key, load_posted_keys, save_posted_keys
from simap_agent.project_store import save_project_context
from simap_agent.slack_client import format_slack_blocks, post_blocks

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger(__name__)

COMPANY_PROFILE = config.COMPANY_PROFILE
VALID_CPV = config.CPV_CODES


def main() -> None:
    """Fetch recent projects, enrich them and post to Slack."""
    logger.info("Starting SIMAP pipeline")
    logger.debug("Slack webhook configured: %s", bool(config.SLACK_WEBHOOK_URL))

    summaries = fetch_project_summaries(cpv=VALID_CPV)
    logger.debug("Fetched %d summaries", len(summaries))

    posted_keys = load_posted_keys(
        config.POSTED_PROJECTS_FILE, config.POSTED_PROJECTS_RETENTION_DAYS
    )
    try:
        save_posted_keys(
            config.POSTED_PROJECTS_FILE,
            posted_keys,
            config.POSTED_PROJECTS_RETENTION_DAYS,
        )
    except Exception:
        logger.exception("Could not prune posted projects store")

    if config.REPOST_ALREADY_POSTED:
        logger.warning("Repost test mode enabled; already posted projects will not be skipped")
        new_summaries = summaries
    else:
        new_summaries = []
        seen_keys = set(posted_keys)
        for summary in summaries:
            key = deduplication_key(summary, config.DEDUPLICATION_SCOPE)
            if key and key in seen_keys:
                logger.info("Skipping already posted %s %s", config.DEDUPLICATION_SCOPE, key)
                continue
            new_summaries.append(summary)
            if key:
                seen_keys.add(key)
        logger.debug("Filtered %d already posted summaries", len(summaries) - len(new_summaries))

    details = fetch_project_details(new_summaries)
    logger.debug("Fetched %d project details", len(details))

    logger.info("Enriching projects via OpenAI")
    enriched = enrich_batch(details, COMPANY_PROFILE)
    for det, enrich_data in zip(details, enriched):
        score = enrich_data.get("apply_score", 0)
        if score < config.APPLY_SCORE_THRESHOLD and not config.POST_BELOW_THRESHOLD:
            logger.info(
                "Skipping project #%s due to low score %s",
                det.get("projectNumber"),
                score,
            )
            continue
        if score < config.APPLY_SCORE_THRESHOLD and config.POST_BELOW_THRESHOLD:
            logger.warning(
                "Posting project #%s despite low score %s because threshold test mode is enabled",
                det.get("projectNumber"),
                score,
            )
        logger.info("Posting project #%s to Slack", det.get("projectNumber"))
        blocks = format_slack_blocks(enrich_data)
        logger.debug("Slack blocks: %s", blocks)
        try:
            post_blocks(blocks)
        except Exception:
            logger.exception("Failed to post message to Slack")
            continue
        try:
            save_project_context(det, enrich_data)
        except Exception:
            logger.exception("Slack post succeeded, but could not save project context")

        key = deduplication_key(det, config.DEDUPLICATION_SCOPE)
        if key:
            try:
                posted_keys.add(key)
                save_posted_keys(
                    config.POSTED_PROJECTS_FILE,
                    posted_keys,
                    config.POSTED_PROJECTS_RETENTION_DAYS,
                )
            except Exception:
                logger.exception("Slack post succeeded, but could not save posted key %s", key)
        logger.info("Slack post succeeded")

    logger.info("Run completed")


if __name__ == "__main__":
    main()
