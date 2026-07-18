# ABOUTME: Test helper building plugin package zip archives (optionally Ed25519-signed)
# ABOUTME: for install-chain, route, and e2e tests.

import base64
import io
import textwrap
import zipfile
from pathlib import Path

PLUGIN_CODE_TEMPLATE = textwrap.dedent("""
    from plugins.base_plugin import BaseGPSPlugin

    class {class_name}(BaseGPSPlugin):
        @property
        def plugin_name(self):
            return "{reported_name}"

        @property
        def plugin_metadata(self):
            return {{"display_name": "{plugin_id}", "category": "tracker",
                     "config_fields": []}}

        async def fetch_locations(self, session):
            return []
    """)


def default_class_name(plugin_id):
    return f"{plugin_id.title().replace('_', '')}Plugin"


def build_package_dir(
    root: Path,
    plugin_id: str,
    *,
    tier=None,
    manifest_overrides=None,
    code=None,
    reported_name=None,
    extra_files=None,
    sign_key=None,
):
    """Create a package directory; returns its path."""
    class_name = default_class_name(plugin_id)
    pkg = root / plugin_id
    pkg.mkdir(parents=True)

    manifest = {
        "id": plugin_id,
        "name": plugin_id.replace("_", " ").title(),
        "version": "1.0.0",
        "author": "Test Author",
        "description": "Test plugin package",
        "entry_point": f"{plugin_id}.py",
        "class_name": class_name,
        "plugin_type": "gps",
    }
    if tier:
        manifest["tier"] = tier
    if manifest_overrides:
        manifest.update(manifest_overrides)

    lines = []
    for key, value in manifest.items():
        if value is None:
            continue
        lines.append(
            f'{key}: "{value}"' if isinstance(value, str) else f"{key}: {value}"
        )
    (pkg / "plugin.yaml").write_text("\n".join(lines) + "\n")

    (pkg / manifest["entry_point"]).write_text(
        code
        if code is not None
        else PLUGIN_CODE_TEMPLATE.format(
            class_name=class_name,
            plugin_id=plugin_id,
            reported_name=reported_name or plugin_id,
        )
    )

    for rel, content in (extra_files or {}).items():
        path = pkg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())

    if sign_key is not None:
        from services.plugin_package_verifier import canonical_package_digest

        digest = canonical_package_digest(pkg)
        signature = sign_key.sign(digest)
        (pkg / "signature.sig").write_text(
            base64.b64encode(signature).decode("ascii") + "\n"
        )

    return pkg


def zip_package_dir(pkg: Path, *, top_level=True) -> bytes:
    """Zip a package directory; entries under <plugin_id>/ when top_level."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pkg.rglob("*")):
            if path.is_file():
                rel = path.relative_to(pkg)
                arcname = (
                    f"{pkg.name}/{rel.as_posix()}" if top_level else rel.as_posix()
                )
                zf.write(path, arcname)
    return buf.getvalue()


def build_plugin_zip(tmp_path: Path, plugin_id: str, **kwargs) -> bytes:
    """Build a package directory and return it zipped."""
    pkg = build_package_dir(tmp_path / f"src_{plugin_id}", plugin_id, **kwargs)
    return zip_package_dir(pkg)
