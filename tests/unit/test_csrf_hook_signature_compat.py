# ABOUTME: Regression tests for the CSRF bearer-bypass hook — it must
# ABOUTME: match both Flask-WTF 1.1 and 1.2 protect() signatures.
"""CSRF hook must be signature-compatible with Flask-WTF 1.1 and 1.2.

Flask-WTF 1.1 called ``CSRFProtect.protect(apply_exemptions=True)``
in its before-request hook. Flask-WTF 1.2 dropped the argument and
calls ``protect()``. Our bearer-bypass shim wraps ``protect``, so
if the shim's signature does not match the installed Flask-WTF's
call site, every request 500s with a ``TypeError`` before it ever
reaches auth. Two container images on different Flask-WTF versions
hit each side of this bug in production, so pin the compatibility
down with a test.
"""

import inspect

import pytest


def _get_bearer_bypass_hook(app):
    """Return the CSRF protect callable currently installed on the app."""
    return app.csrf.protect


class TestCSRFHookAcceptsBothSignatures:
    """The shim must accept a call with no args (Flask-WTF 1.2) AND
    a call with ``apply_exemptions=True`` (Flask-WTF 1.1)."""

    def test_hook_signature_accepts_variadic(self, app):
        """The shim must be *args/**kwargs; otherwise a Flask-WTF
        version change silently breaks every request."""
        hook = _get_bearer_bypass_hook(app)
        sig = inspect.signature(hook)
        # Either has *args or **kwargs — one of them must be present
        # so any caller signature is tolerated.
        kinds = {p.kind for p in sig.parameters.values()}
        assert (
            inspect.Parameter.VAR_POSITIONAL in kinds
            or inspect.Parameter.VAR_KEYWORD in kinds
        ), (
            f"CSRF bearer-bypass hook has fixed signature {sig!s}; "
            f"must accept variadic args to tolerate both Flask-WTF "
            f"1.1 (apply_exemptions=True) and 1.2 (no args)."
        )

    def test_hook_callable_with_no_args(self, app, client):
        """Flask-WTF 1.2 call path: hook is invoked with no arguments."""
        hook = _get_bearer_bypass_hook(app)
        # Must not raise TypeError — no assertion needed on return,
        # only on absence of the signature error.
        with app.test_request_context("/", method="GET"):
            hook()  # If this raises TypeError, the shim is broken.

    def test_hook_callable_with_apply_exemptions_kwarg(self, app, client):
        """Flask-WTF 1.1 call path: hook receives apply_exemptions=True."""
        hook = _get_bearer_bypass_hook(app)
        with app.test_request_context("/", method="GET"):
            # If the shim rejects the kwarg, every request 500s in
            # production. The bearer-bypass path returns early on a
            # bearer header; the fall-through calls the wrapped
            # CSRFProtect.protect which itself may not accept the
            # kwarg on 1.2 — that's fine, we're only guarding the
            # shim's own signature here, so use a bearer token that
            # short-circuits before the underlying call.
            from flask import request as _req
            _req.environ["HTTP_AUTHORIZATION"] = "Bearer tb_pat_dummy"
            hook(apply_exemptions=True)
