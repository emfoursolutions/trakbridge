from flask import Blueprint, render_template, jsonify, current_app
from services.cot_type_service import cot_type_service
from plugins.plugin_manager import plugin_manager
from database import db
import logging
import yaml
import os
from collections import Counter

logger = logging.getLogger(__name__)

bp = Blueprint('cot_types', __name__)


@bp.route('/cot_types')
def list_cot_types():
    """Display all COT types with filtering and search capabilities"""
    try:
        # Load COT data
        cot_data = cot_type_service.get_template_data()

        if not cot_data:
            # Return template with empty data and error message
            return render_template('cot_types.html',
                                   cot_data={'cot_types': []},
                                   cot_stats={'friendly': 0, 'hostile': 0, 'neutral': 0, 'unknown': 0, 'other': 0,
                                              'categories': []},
                                   error_message="Could not load COT types data. Please check the YAML configuration file.")

        # Ensure cot_types exists
        if 'cot_types' not in cot_data:
            cot_data['cot_types'] = []

        # Calculate statistics
        cot_stats = cot_type_service.calculate_cot_statistics(cot_data)

        # Log some info
        logger.info(f"Loaded {len(cot_data['cot_types'])} COT types")
        logger.debug(f"COT statistics: {cot_stats}")

        #cot_data = jsonify(cot_data)
        return render_template('cot_types.html',
                               cot_data=cot_data,
                               cot_stats=cot_stats)

    except Exception as e:
        logger.error(f"Error in list_cot_types route: {e}")
        return render_template('cot_types.html',
                               cot_data={'cot_types': []},
                               cot_stats={'friendly': 0, 'hostile': 0, 'neutral': 0, 'unknown': 0, 'other': 0,
                                          'categories': []},
                               error_message=f"Error loading COT types: {str(e)}")