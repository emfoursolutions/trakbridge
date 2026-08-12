# ABOUTME: Business logic for the admin plugin manager — install validation chain,
# ABOUTME: whitelist sync, and plugin lifecycle (enable/disable/uninstall/registry sync).

import ast
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

from services.logging_service import get_module_logger

logger = get_module_logger(__name__)

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 50 * 1024 * 1024
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
REQUIRED_MANIFEST_KEYS = ("id", "name", "version", "entry_point", "class_name")

# AST scan policy: dangerous CALLS plus imports of process/FFI modules.
# Plain imports of trakbridge_sdk / plugins.base_plugin are always fine.
DANGEROUS_CALL_NAMES = {"exec", "eval", "compile", "__import__"}
DANGEROUS_ATTR_CALLS = {("os", "system"), ("os", "popen")}
DANGEROUS_IMPORT_MODULES = {"subprocess", "ctypes"}


class PluginInstallError(Exception):
    """Install rejected — message is safe to show to the admin."""


def _default_whitelist_path() -> Path:
    external = Path("external_config/plugins.yaml")
    if external.is_file():
        return external
    return Path("config/settings/plugins.yaml")


def update_whitelist_file(
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    path: Optional[Path] = None,
) -> None:
    """Add/remove entries in allowed_plugin_modules in plugins.yaml.

    Rewrites the file via pyyaml (comments are not preserved). Atomic
    (tmp file + os.replace in the same directory). Raises PermissionError
    if the target path or its parent directory is a symlink.
    """
    path = Path(path) if path is not None else _default_whitelist_path()

    # Reject symlinks at the target path to prevent redirect attacks.
    if path.is_symlink():
        raise PermissionError(
            f"Whitelist path {path} is a symlink — refusing to write"
        )
    # Reject symlinks at the parent directory to prevent traversal via linked dirs.
    if path.parent.is_symlink():
        raise PermissionError(
            f"Whitelist parent directory {path.parent} is a symlink — refusing to write"
        )

    data: Dict[str, Any] = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text()) or {}

    modules = list(data.get("allowed_plugin_modules") or [])
    for entry in add:
        if entry not in modules:
            modules.append(entry)
    modules = [m for m in modules if m not in set(remove)]
    data["allowed_plugin_modules"] = modules

    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, default_flow_style=False, sort_keys=False))
    # Set restrictive permissions before the atomic replace so the final file
    # is owner read/write only, regardless of the process umask.
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    logger.info(f"Updated plugin whitelist ({path}): {modules}")


def _check_archive_entries(names_and_flags) -> None:
    for name, is_link in names_and_flags:
        if is_link:
            raise PluginInstallError("Archive contains unsafe link entries")
        if name.startswith("/") or name.startswith("\\"):
            raise PluginInstallError("Archive contains unsafe absolute paths")
        parts = Path(name).parts
        if ".." in parts:
            raise PluginInstallError("Archive contains unsafe traversal paths")


def _extract_archive(data: bytes, filename: str, dest: Path) -> None:
    lower = filename.lower()
    if lower.endswith(".zip"):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise PluginInstallError(f"Corrupt zip archive: {e}") from e
        with zf:
            infos = zf.infolist()
            _check_archive_entries(
                (info.filename, (info.external_attr >> 16) & 0o170000 == 0o120000)
                for info in infos
            )
            total = sum(info.file_size for info in infos)
            if total > MAX_DECOMPRESSED_BYTES:
                raise PluginInstallError(
                    "Archive decompressed size exceeds the 50MB limit"
                )
            zf.extractall(dest)
    elif lower.endswith((".tar.gz", ".tgz")):
        try:
            tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
        except tarfile.TarError as e:
            raise PluginInstallError(f"Corrupt tar archive: {e}") from e
        with tf:
            members = tf.getmembers()
            _check_archive_entries((m.name, m.issym() or m.islnk()) for m in members)
            total = sum(m.size for m in members)
            if total > MAX_DECOMPRESSED_BYTES:
                raise PluginInstallError(
                    "Archive decompressed size exceeds the 50MB limit"
                )
            tf.extractall(dest, filter="data")
    else:
        raise PluginInstallError("Package must be a .zip or .tar.gz archive")


def _package_root(extract_dir: Path) -> Path:
    entries = [p for p in extract_dir.iterdir() if not p.name.startswith("__")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def _scan_python_source(path: Path) -> None:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as e:
        raise PluginInstallError(f"Unparseable Python in package ({path.name}): {e}")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in names:
                root = name.split(".")[0]
                if root in DANGEROUS_IMPORT_MODULES:
                    raise PluginInstallError(
                        f"Package contains dangerous import '{root}' in {path.name}"
                    )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in DANGEROUS_CALL_NAMES:
                raise PluginInstallError(
                    f"Package contains dangerous call '{func.id}()' in {path.name}"
                )
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if (func.value.id, func.attr) in DANGEROUS_ATTR_CALLS:
                    raise PluginInstallError(
                        f"Package contains dangerous call "
                        f"'{func.value.id}.{func.attr}()' in {path.name}"
                    )
                if (
                    func.value.id == "importlib"
                    and func.attr == "import_module"
                    and not (node.args and isinstance(node.args[0], ast.Constant))
                ):
                    raise PluginInstallError(
                        f"Package contains dynamic import in {path.name}"
                    )


def _load_plugin_class(root: Path, manifest: Dict[str, Any]):
    import importlib.util

    from plugins.base_plugin import (
        BaseGPSPlugin,
        BaseInboundPlugin,
        BaseOutputPlugin,
    )

    entry_path = (root / manifest["entry_point"]).resolve()
    module_name = f"_plugin_install_check_{manifest['id']}"
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise PluginInstallError("Could not load the plugin entry point")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise PluginInstallError(f"Plugin entry point failed to import: {e}") from e

    plugin_class = getattr(module, manifest["class_name"], None)
    if plugin_class is None:
        raise PluginInstallError(
            f"Class '{manifest['class_name']}' not found in entry point"
        )

    if issubclass(plugin_class, BaseGPSPlugin):
        plugin_type = "gps"
    elif issubclass(plugin_class, BaseInboundPlugin):
        plugin_type = "inbound"
    elif issubclass(plugin_class, BaseOutputPlugin):
        plugin_type = "output"
    else:
        raise PluginInstallError(
            "Plugin class does not inherit a TrakBridge plugin base class"
        )

    try:
        reported_name = plugin_class({}).plugin_name
    except Exception as e:
        raise PluginInstallError(f"Plugin class could not be instantiated: {e}") from e
    if reported_name != manifest["id"]:
        raise PluginInstallError(
            f"Plugin class plugin_name '{reported_name}' must equal manifest "
            f"id '{manifest['id']}'"
        )
    return plugin_class, plugin_type


def install_plugin(
    data: bytes,
    filename: str,
    username: str,
    external_dir: Optional[Path] = None,
    whitelist_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the full install validation chain and commit the package.

    Raises PluginInstallError on any rejection; nothing is written until
    every validation step has passed.
    """
    from database import db
    from models.installed_plugin import InstalledPlugin, PluginAuditLog
    from plugins.plugin_manager import get_plugin_manager
    from services.license_service import TIERS, get_license_service
    from services.plugin_package_verifier import verify_package_signature

    external_dir = Path(external_dir) if external_dir else Path("external_plugins")

    # 1. extension + size
    if not filename.lower().endswith((".zip", ".tar.gz", ".tgz")):
        raise PluginInstallError("Package must be a .zip or .tar.gz archive")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PluginInstallError("Package too large (max 10MB)")

    tmp_dir = Path(tempfile.mkdtemp(prefix="tb_plugin_install_"))
    try:
        # 2-3. entry safety + extract
        _extract_archive(data, filename, tmp_dir)
        root = _package_root(tmp_dir)

        # 4. manifest
        manifest_path = root / "plugin.yaml"
        if not manifest_path.is_file():
            raise PluginInstallError("Package is missing plugin.yaml")
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except yaml.YAMLError as e:
            raise PluginInstallError(f"plugin.yaml is not valid YAML: {e}") from e
        missing = [k for k in REQUIRED_MANIFEST_KEYS if not manifest.get(k)]
        if missing:
            raise PluginInstallError(
                f"plugin.yaml missing required keys: {', '.join(missing)}"
            )
        plugin_id = str(manifest["id"])
        if not PLUGIN_ID_RE.match(plugin_id):
            raise PluginInstallError(
                "Invalid plugin id (lowercase letters, digits, underscores; "
                "2-50 chars)"
            )
        tier = str(manifest.get("tier", "community"))
        if tier not in TIERS:
            raise PluginInstallError(f"Unknown tier '{tier}'")

        # 5. min version
        min_version = manifest.get("min_trakbridge_version")
        if min_version and not _version_satisfied(str(min_version)):
            raise PluginInstallError(
                f"Plugin requires TrakBridge {min_version} or newer"
            )

        # 6. tier gate
        license_service = get_license_service()
        if not license_service.is_tier_allowed(tier):
            raise PluginInstallError(
                f"Plugin requires the '{tier}' tier but this deployment is "
                f"licensed as '{license_service.get_tier()}'"
            )

        # 7. signature
        signature_status = verify_package_signature(root)
        if signature_status == "invalid":
            raise PluginInstallError(
                "Package signature verification failed — the package may have "
                "been tampered with"
            )
        # Signed-only enforcement applies to the PLUGIN's declared tier, not the
        # deployment tier. A Pro deployment may still install unsigned community
        # plugins (with the UNVERIFIED warning) — the trust guarantee is only
        # meaningful for premium plugins that claim Pro/Enterprise capability.
        if signature_status == "unsigned" and tier != "community":
            raise PluginInstallError(
                f"Unsigned '{tier}' tier plugin cannot be installed — plugins "
                "declaring Pro or Enterprise tier must carry a valid Emfour "
                "signature."
            )
        verified = signature_status == "verified"

        # 8. entry point containment
        entry_path = (root / str(manifest["entry_point"])).resolve()
        if not entry_path.is_relative_to(root.resolve()):
            raise PluginInstallError("entry_point escapes the package directory")
        if not entry_path.is_file():
            raise PluginInstallError(
                f"entry_point '{manifest['entry_point']}' not found in package"
            )

        # 9. AST scan
        for py_file in sorted(root.rglob("*.py")):
            _scan_python_source(py_file)

        # 10. import + class checks + identity rule
        plugin_class, plugin_type = _load_plugin_class(root, manifest)
        declared_type = manifest.get("plugin_type")
        if declared_type and str(declared_type) != plugin_type:
            raise PluginInstallError(
                f"plugin.yaml declares plugin_type '{declared_type}' but the "
                f"class is a '{plugin_type}' plugin"
            )

        # 11. conflicts
        pm = get_plugin_manager()
        if pm.is_builtin_plugin(plugin_id) or plugin_id in getattr(
            pm, "_builtin_plugin_names", set()
        ):
            raise PluginInstallError(
                f"Plugin id '{plugin_id}' conflicts with a built-in plugin"
            )
        if InstalledPlugin.query.filter_by(plugin_id=plugin_id).first():
            raise PluginInstallError(
                f"Plugin '{plugin_id}' is already installed — uninstall it first"
            )

        # 12. commit
        target = external_dir / plugin_id
        module_name = f"external_plugins.{plugin_id}"
        staging = external_dir / f".{plugin_id}.installing"
        committed = {"files": False, "whitelist": False}
        try:
            external_dir.mkdir(parents=True, exist_ok=True)
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(root, staging)
            os.replace(staging, target)
            committed["files"] = True

            update_whitelist_file(add=[module_name], path=whitelist_path)
            committed["whitelist"] = True
            pm._allowed_modules.add(module_name)

            row = InstalledPlugin(
                plugin_id=plugin_id,
                display_name=manifest.get("name"),
                version=str(manifest.get("version")),
                author=manifest.get("author"),
                description=manifest.get("description"),
                plugin_type=plugin_type,
                package_format="package",
                is_enabled=True,
                is_verified=verified,
                tier=tier,
                install_path=plugin_id,
                installed_by=username,
                metadata_json=json.dumps(manifest),
            )
            db.session.add(row)
            db.session.add(
                PluginAuditLog(
                    plugin_id=plugin_id,
                    action="installed",
                    performed_by=username,
                    details=json.dumps({"verified": verified, "tier": tier}),
                )
            )
            db.session.commit()

            # hot-load
            try:
                pm._load_package_plugins(str(external_dir))
            except Exception as e:
                logger.warning(f"Hot-load after install failed (non-fatal): {e}")

            logger.info(
                f"AUDIT: plugin install accepted user={username} "
                f"plugin_id={plugin_id} tier={tier} verified={verified}"
            )
            return {"plugin_id": plugin_id, "verified": verified, "tier": tier}
        except PluginInstallError:
            raise
        except Exception as e:
            if committed["whitelist"]:
                update_whitelist_file(remove=[module_name], path=whitelist_path)
                pm._allowed_modules.discard(module_name)
            if committed["files"] and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            from database import db as _db

            _db.session.rollback()
            raise PluginInstallError(f"Install failed during commit: {e}") from e
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _get_installed(plugin_id: str):
    from models.installed_plugin import InstalledPlugin

    row = InstalledPlugin.query.filter_by(plugin_id=plugin_id).first()
    if row is None:
        raise PluginInstallError(f"Plugin '{plugin_id}' is not installed")
    return row


def _assert_no_streams(plugin_id: str) -> None:
    from models.stream import Stream

    count = Stream.query.filter_by(plugin_type=plugin_id).count()
    if count:
        raise PluginInstallError(
            f"Plugin '{plugin_id}' is used by {count} stream(s) — remove or "
            f"repoint those streams first"
        )


def _audit(plugin_id: str, action: str, username: str, details: Optional[dict] = None):
    from database import db
    from models.installed_plugin import PluginAuditLog

    db.session.add(
        PluginAuditLog(
            plugin_id=plugin_id,
            action=action,
            performed_by=username,
            details=json.dumps(details or {}),
        )
    )


def enable_plugin(
    plugin_id: str,
    username: str,
    whitelist_path: Optional[Path] = None,
    external_dir: Optional[Path] = None,
) -> None:
    """Re-enable a disabled plugin. Re-checks the tier gate — the licence may
    have been downgraded since the plugin was installed."""
    from database import db
    from plugins.plugin_manager import get_plugin_manager
    from services.license_service import get_license_service

    row = _get_installed(plugin_id)

    license_service = get_license_service()
    if not license_service.is_tier_allowed(row.tier):
        raise PluginInstallError(
            f"Plugin '{plugin_id}' requires the '{row.tier}' tier but this "
            f"deployment is licensed as '{license_service.get_tier()}'"
        )

    module_name = f"external_plugins.{plugin_id}"
    update_whitelist_file(add=[module_name], path=whitelist_path)
    pm = get_plugin_manager()
    pm._allowed_modules.add(module_name)

    row.is_enabled = True
    _audit(plugin_id, "enabled", username)
    db.session.commit()

    external_dir = Path(external_dir) if external_dir else Path("external_plugins")
    try:
        pm._load_package_plugins(str(external_dir))
    except Exception as e:
        logger.warning(f"Hot-load after enable failed (non-fatal): {e}")
    logger.info(f"AUDIT: plugin enabled user={username} plugin_id={plugin_id}")


def disable_plugin(
    plugin_id: str,
    username: str,
    whitelist_path: Optional[Path] = None,
) -> None:
    """Disable a plugin: whitelist removal + registry unload. Files stay."""
    from database import db
    from plugins.plugin_manager import get_plugin_manager

    row = _get_installed(plugin_id)
    _assert_no_streams(plugin_id)

    module_name = f"external_plugins.{plugin_id}"
    update_whitelist_file(remove=[module_name], path=whitelist_path)
    pm = get_plugin_manager()
    pm._allowed_modules.discard(module_name)
    pm.unregister_plugin(plugin_id)

    row.is_enabled = False
    _audit(plugin_id, "disabled", username)
    db.session.commit()
    logger.info(f"AUDIT: plugin disabled user={username} plugin_id={plugin_id}")


def uninstall_plugin(
    plugin_id: str,
    username: str,
    whitelist_path: Optional[Path] = None,
    external_dir: Optional[Path] = None,
) -> None:
    """Remove a plugin: registry, whitelist, files, and DB record."""
    from database import db
    from plugins.plugin_manager import get_plugin_manager

    row = _get_installed(plugin_id)
    _assert_no_streams(plugin_id)

    module_name = f"external_plugins.{plugin_id}"
    update_whitelist_file(remove=[module_name], path=whitelist_path)
    pm = get_plugin_manager()
    pm._allowed_modules.discard(module_name)
    pm.unregister_plugin(plugin_id)

    external_dir = Path(external_dir) if external_dir else Path("external_plugins")
    target = external_dir / (row.install_path or plugin_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    db.session.delete(row)
    _audit(plugin_id, "uninstalled", username)
    db.session.commit()
    logger.info(f"AUDIT: plugin uninstalled user={username} plugin_id={plugin_id}")


def sync_plugin_registry(
    external_dir: Optional[Path] = None,
    whitelist_path: Optional[Path] = None,
) -> None:
    """Reconcile the InstalledPlugin table with the external_plugins directory.

    Handles manual additions/removals made outside the UI, and grandfathers
    pre-existing plugins into the whitelist (required since external plugins
    are no longer blanket-allowed).
    """
    from database import db
    from models.installed_plugin import InstalledPlugin
    from services.plugin_package_verifier import verify_package_signature

    external_dir = Path(external_dir) if external_dir else Path("external_plugins")

    on_disk: Dict[str, Dict[str, Any]] = {}
    if external_dir.is_dir():
        for entry in sorted(external_dir.iterdir()):
            if entry.name.startswith(("__", ".")):
                continue
            if entry.is_dir() and (entry / "plugin.yaml").is_file():
                try:
                    manifest = yaml.safe_load((entry / "plugin.yaml").read_text()) or {}
                except yaml.YAMLError as e:
                    logger.warning(f"Sync: unreadable manifest in {entry.name}: {e}")
                    continue
                on_disk[entry.name] = {
                    "format": "package",
                    "manifest": manifest,
                    "verified": verify_package_signature(entry) == "verified",
                }
            elif entry.is_file() and entry.suffix == ".py":
                on_disk[entry.stem] = {
                    "format": "legacy",
                    "manifest": {},
                    "verified": False,
                }

    known = {row.plugin_id: row for row in InstalledPlugin.query.all()}

    for plugin_id, info in on_disk.items():
        manifest = info["manifest"]
        if plugin_id not in known:
            db.session.add(
                InstalledPlugin(
                    plugin_id=plugin_id,
                    display_name=manifest.get("name", plugin_id),
                    version=str(manifest.get("version", "")),
                    author=manifest.get("author"),
                    description=manifest.get("description"),
                    package_format=info["format"],
                    is_enabled=True,
                    is_verified=info["verified"],
                    tier=str(manifest.get("tier", "community")),
                    install_path=plugin_id,
                    installed_by="system-sync",
                    metadata_json=json.dumps(manifest),
                )
            )
            logger.info(f"Sync: recorded new external plugin '{plugin_id}'")
        else:
            row = known[plugin_id]
            if row.metadata_json:
                old_json = json.loads(row.metadata_json)
            else:
                old_json = {}

            if (
                old_json != manifest
                or row.package_format != info["format"]
                or row.is_verified != info["verified"]
            ):
                row.metadata_json = json.dumps(manifest)
                row.display_name = manifest.get("name", plugin_id)
                row.version = str(manifest.get("version", ""))
                row.author = manifest.get("author")
                row.description = manifest.get("description")
                row.tier = str(manifest.get("tier", "community"))
                row.package_format = info["format"]
                row.is_verified = info["verified"]
                _audit(plugin_id, "metadata-synced", "system-sync")
                logger.info(
                    f"Sync: updated metadata for external plugin '{plugin_id}'"
                )
        row = known.get(plugin_id)
        if row is None or row.is_enabled:
            update_whitelist_file(
                add=[f"external_plugins.{plugin_id}"], path=whitelist_path
            )

    for plugin_id, row in known.items():
        if plugin_id not in on_disk:
            logger.info(
                f"Sync: plugin '{plugin_id}' removed from disk — dropping record"
            )
            update_whitelist_file(
                remove=[f"external_plugins.{plugin_id}"], path=whitelist_path
            )
            db.session.delete(row)

    db.session.commit()


def list_all_plugins() -> list:
    """Merge built-in plugin metadata with external plugin DB records."""
    from models.installed_plugin import InstalledPlugin
    from plugins.plugin_manager import get_plugin_manager

    pm = get_plugin_manager()
    external_rows = {row.plugin_id: row for row in InstalledPlugin.query.all()}

    result = []
    for name, metadata in pm.get_all_plugin_metadata().items():
        if name in external_rows:
            continue  # listed below with DB detail
        result.append(
            {
                "plugin_id": name,
                "display_name": metadata.get("display_name", name),
                "description": metadata.get("description", ""),
                "category": metadata.get("category", ""),
                "icon": metadata.get("icon", ""),
                "source": "builtin" if pm.is_builtin_plugin(name) else "external",
                "is_enabled": True,
                "is_verified": True,
                "tier": "community",
                "package_format": None,
                "version": None,
            }
        )

    for plugin_id, row in sorted(external_rows.items()):
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
        result.append(
            {
                "plugin_id": plugin_id,
                "display_name": row.display_name or plugin_id,
                "description": row.description or "",
                "category": metadata.get("category", ""),
                "icon": metadata.get("icon", ""),
                "source": "external",
                "is_enabled": row.is_enabled,
                "is_verified": row.is_verified,
                "tier": row.tier,
                "package_format": row.package_format,
                "version": row.version,
            }
        )
    return result


def get_plugin_details(plugin_id: str) -> Dict[str, Any]:
    """Full metadata + README + audit history for the detail page."""
    from models.installed_plugin import InstalledPlugin, PluginAuditLog

    row = _get_installed(plugin_id)
    metadata = json.loads(row.metadata_json) if row.metadata_json else {}

    readme = None
    readme_path = (
        Path("external_plugins") / (row.install_path or plugin_id) / "README.md"
    )
    if readme_path.is_file():
        readme = readme_path.read_text()

    audit = (
        PluginAuditLog.query.filter_by(plugin_id=plugin_id)
        .order_by(PluginAuditLog.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "plugin_id": row.plugin_id,
        "display_name": row.display_name,
        "version": row.version,
        "author": row.author,
        "description": row.description,
        "plugin_type": row.plugin_type,
        "package_format": row.package_format,
        "is_enabled": row.is_enabled,
        "is_verified": row.is_verified,
        "tier": row.tier,
        "installed_by": row.installed_by,
        "installed_at": row.created_at,
        "metadata": metadata,
        "readme": readme,
        "audit_log": audit,
    }


def _version_satisfied(min_version: str) -> bool:
    from services.version import get_version_tuple

    def as_tuple(value: str):
        clean = value.split("+")[0].split("-")[0]
        return tuple(int(p) for p in clean.split(".") if p.isdigit())

    try:
        return get_version_tuple() >= as_tuple(min_version)
    except (ValueError, AttributeError, TypeError):
        return True  # unparseable local version: don't block installs
