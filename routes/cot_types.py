"""
File: routes/cot_types.py

Description:
    Displays all Cursor-on-Target (COT) event types in a structured format for review, filtering, and analysis.
    Fetches data from the YAML-backed configuration via the `cot_type_service`, computes classification statistics,
    and renders a UI view with error handling and status feedback. This route provides support for reviewing all known
    COT event types categorized as friendly, hostile, neutral, unknown, or other.

Key features:
    - Loads and parses COT type definitions from a YAML configuration
    - Computes statistical breakdowns by affiliation and category
    - Renders a structured HTML template with the parsed and analyzed data
    - Gracefully handles missing or malformed data with user-friendly error messaging
    - Supports logging for debugging and operational visibility

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

# Standard library imports
import logging

# Third-party imports
from flask import Blueprint, render_template

# Module-level logger
logger = logging.getLogger(__name__)

bp = Blueprint("cot_types", __name__)


@bp.route("/cot_types")
def list_cot_types():
    """Display all COT types with filtering and search capabilities"""
    from services.cot_type_service import cot_type_service

    try:
        # Load COT data
        cot_data = cot_type_service.get_template_data()

        if not cot_data:
            # Return template with empty data and error message
            return render_template(
                "cot_types.html",
                cot_data={"cot_types": []},
                cot_stats={
                    "friendly": 0,
                    "hostile": 0,
                    "neutral": 0,
                    "unknown": 0,
                    "other": 0,
                    "categories": [],
                },
                error_message="Could not load COT types data. "
                "Please check the YAML configuration file.",
            )

        # Ensure cot_types exists
        if "cot_types" not in cot_data:
            cot_data["cot_types"] = []

        # Calculate statistics
        cot_stats = cot_type_service.calculate_cot_statistics(cot_data)

        # Log some info
        logger.info(f"Loaded {len(cot_data['cot_types'])} COT types")
        logger.debug(f"COT statistics: {cot_stats}")

        return render_template("cot_types.html", cot_data=cot_data, cot_stats=cot_stats)

    except Exception as e:
        logger.error(f"Error in list_cot_types route: {e}")
        return render_template(
            "cot_types.html",
            cot_data={"cot_types": []},
            cot_stats={
                "friendly": 0,
                "hostile": 0,
                "neutral": 0,
                "unknown": 0,
                "other": 0,
                "categories": [],
            },
            error_message=f"Error loading COT types: {str(e)}",
        )
