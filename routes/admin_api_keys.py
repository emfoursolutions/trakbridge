# ABOUTME: Admin cross-user API key management at /admin/api-keys.
# ABOUTME: Lists every key across all users; revoke any as admin.
"""
File: routes/admin_api_keys.py

Description:
    Admin-only cross-user view of API keys. Complements the per-user
    self-service pages at /auth/api-keys with the "who has what live
    keys across the whole deployment" view an admin needs to spot
    dormant keys, respond to a leak, or audit access.

    All endpoints are session-only + admin-required. A leaked admin
    API key can therefore never see or revoke other users' keys.

Author: Emfour Solutions
Created: 2026-08-26
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from database import db
from models.user import User, UserApiKey
from services.auth import admin_required, get_current_user, session_only
from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

bp = Blueprint("admin_api_keys", __name__)


@bp.route("/", methods=["GET"])
@session_only
@admin_required
def list_all_keys():
    """Render the cross-user API key table."""
    # Left-join keys → users so an admin sees the owner's username on
    # every row without an extra query per key.
    rows = (
        db.session.query(UserApiKey, User)
        .join(User, UserApiKey.user_id == User.id)
        .order_by(UserApiKey.created_at.desc())
        .all()
    )
    keys = []
    for key, user in rows:
        entry = key.to_dict()
        entry["owner_username"] = user.username
        entry["owner_email"] = user.email
        entry["owner_role"] = user.role.value
        keys.append(entry)

    active_count = sum(1 for k in keys if k["is_valid"])
    total_count = len(keys)
    return render_template(
        "admin/api_keys.html",
        keys=keys,
        active_count=active_count,
        total_count=total_count,
    )


@bp.route("/<int:key_id>/revoke", methods=["POST"])
@session_only
@admin_required
def revoke_any_key(key_id: int):
    """Admin revoke of any key regardless of owner.

    Emits a WARNING-level audit line naming both the acting admin
    and the affected owner so a cross-user revocation is
    distinguishable from a self-revoke in the log stream.
    """
    actor = get_current_user()
    key = UserApiKey.query.get(key_id)
    if key is None:
        if request.is_json:
            return jsonify({"error": "not_found"}), 404
        abort(404)

    if key.revoked_at is not None:
        message = "This key was already revoked."
        if request.is_json:
            return jsonify({"success": True, "message": message}), 200
        flash(message, "info")
        return redirect(url_for("admin_api_keys.list_all_keys"))

    owner_username = key.user.username if key.user else "unknown"
    key.revoke()
    db.session.commit()
    logger.warning(
        "AUDIT: api_key revoke actor=%s owner=%s key_prefix=%s "
        "action=admin_cross_user",
        actor.username,
        owner_username,
        key.token_prefix,
    )

    message = (
        f"API key '{key.name}' belonging to {owner_username} "
        f"has been revoked."
    )
    if request.is_json:
        return jsonify({"success": True, "message": message}), 200
    flash(message, "success")
    return redirect(url_for("admin_api_keys.list_all_keys"))
