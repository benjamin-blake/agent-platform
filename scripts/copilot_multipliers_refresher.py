"""DEPRECATED: Copilot multiplier tracking is no longer needed under Bedrock.

Refresh GitHub Copilot model multipliers from official documentation.
Retained for rollback only. The active cost model is per-token pricing
via Gemini CLI (Gemini BYOK).

Exit codes:
    0: Success, metadata updated (discrepancies are logged but non-blocking)
    1: Fetch or parse error
    2: YAML I/O error
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

DOCS_URL = "https://docs.github.com/en/copilot/concepts/billing/copilot-requests#model-multipliers"
CONFIG_PATH = Path("config/agent/copilot/model_multipliers.yaml")

TIMEOUT = 30


def fetch_docs_page() -> str:
    """Fetch the GitHub Copilot billing documentation page.

    Returns:
        HTML content of the page.

    Raises:
        requests.RequestException: If fetch fails.
    """
    logger.info(f"Fetching {DOCS_URL}...")
    try:
        resp = requests.get(DOCS_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch documentation: {e}")
        raise


def parse_multipliers_from_html(html: str) -> dict[str, float]:
    """Parse model multipliers from HTML tables.

    Looks for tables containing model names and multiplier values.
    Expects format: "Model Name" in first column, multiplier (0.0, 0.25, etc.)
    in second column.

    Args:
        html: HTML content of the documentation page.

    Returns:
        Dict mapping model name to multiplier value (normalized with hyphens).
        Returns empty dict if no tables found.

    Raises:
        Exception: If parsing fails critically.
    """
    multipliers: dict[str, float] = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        logger.info(f"Found {len(tables)} table(s) in HTML")

        for table_idx, table in enumerate(tables):
            rows = table.find_all("tr")
            logger.debug(f"Table {table_idx + 1} has {len(rows)} row(s)")

            for row_idx, row in enumerate(rows):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue

                model_cell = cells[0].get_text(strip=True)
                multiplier_cell = cells[1].get_text(strip=True)

                model_name = model_cell.lower().strip()
                if not model_name or model_name in (
                    "model",
                    "model name",
                    "name",
                ):
                    continue

                # Normalize model name: replace spaces and parentheses with hyphens
                model_name = re.sub(r"[\s()]+", "-", model_name)
                model_name = re.sub(r"-+", "-", model_name)
                model_name = model_name.strip("-")

                multiplier_str = multiplier_cell.strip()
                try:
                    multiplier = float(multiplier_str)
                    multipliers[model_name] = multiplier
                    logger.debug(f"Parsed: {model_name} → {multiplier} (table {table_idx + 1}, row {row_idx + 1})")
                except ValueError:
                    logger.debug(f"Skipped non-numeric multiplier: {model_name} = {multiplier_str}")

        logger.info(f"Extracted {len(multipliers)} model(s) from HTML")
        return multipliers

    except Exception as e:
        logger.error(f"Error parsing HTML: {e}")
        raise


def load_config() -> dict:
    """Load current YAML config.

    Returns:
        dict with keys: metadata, default_multiplier, multipliers.
        Returns empty dict if file not found.
    """
    if not CONFIG_PATH.exists():
        logger.warning(f"Config not found: {CONFIG_PATH}")
        return {}

    try:
        content = CONFIG_PATH.read_text(encoding="utf-8")
        return yaml.safe_load(content) or {}
    except Exception as e:
        logger.error(f"Error loading YAML: {e}")
        raise


def compare_multipliers(
    parsed: dict[str, float],
    config: dict,
) -> tuple[bool, list[str]]:
    """Compare parsed multipliers against config.

    Args:
        parsed: Model→multiplier dict from HTML.
        config: Loaded YAML config dict.

    Returns:
        Tuple of (all_match, discrepancies) where all_match is True if
        all parsed models match the config (by name and value),
        and discrepancies is a list of human-readable mismatch descriptions.
    """
    current_multipliers = config.get("multipliers", {})
    discrepancies: list[str] = []

    for model_name, parsed_value in parsed.items():
        if model_name not in current_multipliers:
            discrepancies.append(f"Model {model_name} found in docs but not in config")
        else:
            current_value = current_multipliers[model_name]
            if abs(current_value - parsed_value) > 1e-6:
                discrepancies.append(f"Model {model_name}: config={current_value}, docs={parsed_value}")

    for model_name, config_value in current_multipliers.items():
        if model_name not in parsed:
            discrepancies.append(f"Model {model_name} in config but not found in docs")

    all_match = len(discrepancies) == 0
    return all_match, discrepancies


def update_metadata(config: dict) -> dict:
    """Update metadata in config: last_verified and next_review.

    Sets last_verified to today and next_review to 30 days ahead.

    Args:
        config: YAML config dict to update.

    Returns:
        Updated config dict.
    """
    today = datetime.now(timezone.utc).date()
    next_review = today + timedelta(days=30)

    if "metadata" not in config:
        config["metadata"] = {}

    config["metadata"]["last_verified"] = str(today)
    config["metadata"]["next_review"] = str(next_review)

    logger.info(f"Updated metadata: last_verified={today}, next_review={next_review}")
    return config


def write_config(config: dict) -> None:
    """Write updated config back to YAML file.

    Preserves existing formatting and structure where possible.

    Args:
        config: Updated config dict.

    Raises:
        OSError: If file write fails.
    """
    try:
        content = yaml.dump(
            config,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        CONFIG_PATH.write_text(content, encoding="utf-8")
        logger.info(f"Updated {CONFIG_PATH}")
    except Exception as e:
        logger.error(f"Error writing YAML: {e}")
        raise


def main() -> int:
    """Main entry point.

    Returns:
        0 on success (config updated with metadata),
        1 on fetch/parse error,
        2 on I/O error.

    Note: Discrepancies in multipliers are logged but do not affect exit code,
    since the purpose of this script is to refresh metadata even when docs
    and config may temporarily diverge.
    """
    try:
        html = fetch_docs_page()
    except Exception as e:
        logger.error(f"Failed to fetch docs: {e}")
        return 1

    try:
        parsed = parse_multipliers_from_html(html)
    except Exception as e:
        logger.error(f"Failed to parse HTML: {e}")
        return 1

    if not parsed:
        logger.error("No multipliers parsed from HTML")
        return 1

    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return 2

    all_match, discrepancies = compare_multipliers(parsed, config)

    if discrepancies:
        logger.warning(f"Found {len(discrepancies)} discrepancy(ies):")
        for disc in discrepancies:
            logger.warning(f"  - {disc}")

    config = update_metadata(config)

    try:
        write_config(config)
    except Exception as e:
        logger.error(f"Failed to write config: {e}")
        return 2

    logger.info("Metadata updated successfully")

    if not all_match:
        logger.warning("Discrepancies were found — review config manually but metadata refresh still succeeded")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
