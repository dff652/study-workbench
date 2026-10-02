"""Read-only source verification and private, reproducible legacy import packages."""
import ast
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import warnings

from PIL import Image

from app.domain import ContractError, SourceImage, deserialize_bundle, serialize_bundle
from .catalog import CatalogConversion, build_legacy_bundle


PACKAGE_SCHEMA = "study-workbench.legacy-import.v1"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 40_000_000


def fail(code, path, message):
    raise ContractError(code, path, message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "source", "Duplicate source JSON key")
        result[key] = value
    return result


def read_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: fail("invalid_json", "source", "Non-finite JSON number"))
    except ContractError:
        raise
    except (ValueError, UnicodeDecodeError) as exc:
        fail("invalid_json", "source", "Invalid UTF-8 source JSON")


def confined(root, relative):
    if not isinstance(relative, str):
        fail("invalid_path", "source", "Expected a relative local path")
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        fail("invalid_path", "source", "Source path must stay inside its root")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        fail("invalid_path", "source", "Symlink leaves the configured source root")
    return path


def checked_bytes(root, record):
    path = confined(root, record["path"])
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        fail("invalid_source_file", record["path"], "Missing or oversized source file")
    raw = path.read_bytes()
    if len(raw) != record["size_bytes"] or digest(raw) != record["sha256"]:
        fail("source_hash_mismatch", record["path"], "Source no longer matches its inventory")
    return raw


def image_dimensions(raw):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["JPEG"]) as image:
                width, height = image.size
                if width * height > MAX_PIXELS:
                    fail("image_too_large", "image", "Image pixel count exceeds the import limit")
                image.load()  # Verify decoding without rotation, OCR or modification.
                return width, height
    except ContractError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        fail("invalid_image", "image", "Expected a decodable JPEG within the pixel limit")


@dataclass(frozen=True)
class PreparedImport:
    manifest: dict
    conversion: CatalogConversion
    catalog_bytes: bytes


def verify_prepared(prepared):
    """Rebuild the row mapping; callers cannot substitute a different bundle."""
    manifest, conversion = prepared.manifest, prepared.conversion
    if (manifest.get("schema") != PACKAGE_SCHEMA or
        _source_fingerprint(manifest) != manifest.get("source_digest")):
        fail("invalid_package", "manifest", "Import source fingerprint does not match")
    if (digest(prepared.catalog_bytes) != manifest["sources"]["catalog"]["sha256"] or
        read_json(prepared.catalog_bytes) != [row["raw"] for row in manifest["index_rows"]]):
        fail("mapping_mismatch", "catalog", "Source rows differ from the verified original JSON bytes")
    images = {photo["token"]: SourceImage(photo["image_id"], manifest["household_id"], photo["sha256"],
        photo["storage_key"], "image/jpeg", photo["width"], photo["height"], manifest["sources"]["image_recorded_at"])
        for photo in manifest["sources"]["photos"]}
    rebuilt = build_legacy_bundle([row["raw"] for row in manifest["index_rows"]],
        {int(k): v for k, v in manifest["sources"]["groups"].items()}, images,
        household_id=manifest["household_id"], dataset_key=manifest["dataset_key"], recorded_at=manifest["prepared_at"])
    _verify_counts(rebuilt, manifest["sources"]["expected_counts"])
    if (rebuilt != conversion or manifest["index_rows"] != list(rebuilt.index_rows) or
        manifest["counts"] != rebuilt.counts or
        digest(serialize_bundle(rebuilt.bundle).encode()) != manifest["bundle_sha256"]):
        fail("mapping_mismatch", "package", "Source mapping and bundle do not agree")


def _source_fingerprint(manifest):
    return digest(canonical({"schema": manifest["schema"], "household_id": manifest["household_id"],
        "dataset_key": manifest["dataset_key"], "sources": manifest["sources"]}))


def _verify_counts(conversion, expected):
    rows = conversion.index_rows
    by_book = {book: sum(row["book"] == book for row in rows) for book in {r["book"] for r in rows}}
    by_group = {str(group): sum(row["raw"]["group"] == group for row in rows) for group in range(1, 7)}
    if (conversion.counts["index_entries"] != expected["question_entries"] or
        conversion.counts["root_questions"] != expected["parent_questions"] or
        conversion.counts["images"] != expected["photos"] or by_book != expected["by_book"] or
        by_group != {str(k): v for k, v in expected["by_group"].items()}):
        fail("source_count_mismatch", "inventory.counts", "Imported coverage does not match the source inventory")


def load_prepared_import(package_dir, data_root):
    """Verify saved source copies, images, mapping and sealed bundle before DB use."""
    package_dir, data_root = Path(package_dir).resolve(), Path(data_root).resolve()
    if not package_dir.is_relative_to(data_root):
        fail("invalid_path", "package", "Package must be inside the configured private data root")
    def package_bytes(name):
        path = confined(package_dir, name)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            fail("invalid_package", "package", "Missing or oversized package file")
        return path.read_bytes()
    manifest = read_json(package_bytes("manifest.json"))
    if manifest.get("schema") != PACKAGE_SCHEMA or _source_fingerprint(manifest) != manifest.get("source_digest"):
        fail("invalid_package", "manifest", "Unsupported or modified import manifest")
    raw_catalog = package_bytes("catalog.source.json")
    group_raw = package_bytes("groups.json")
    if digest(raw_catalog) != manifest["sources"]["catalog"]["sha256"] or digest(group_raw) != manifest["groups_sha256"]:
        fail("source_hash_mismatch", "package", "Saved catalog or group definitions were changed")
    groups = {int(key): value for key, value in read_json(group_raw).items()}
    if canonical(groups) != canonical(manifest["sources"]["groups"]):
        fail("mapping_mismatch", "groups", "Saved groups differ from the original source mapping")
    images = {}
    for photo in manifest["sources"]["photos"]:
        raw = checked_bytes(data_root, {"path": photo["storage_key"], "size_bytes": photo["size_bytes"], "sha256": photo["sha256"]})
        if image_dimensions(raw) != (photo["width"], photo["height"]):
            fail("image_metadata_mismatch", "package", "Image dimensions do not match their source record")
        images[photo["token"]] = SourceImage(photo["image_id"], manifest["household_id"], photo["sha256"],
            photo["storage_key"], "image/jpeg", photo["width"], photo["height"], manifest["sources"]["image_recorded_at"])
    conversion = build_legacy_bundle(read_json(raw_catalog), groups, images, household_id=manifest["household_id"],
        dataset_key=manifest["dataset_key"], recorded_at=manifest["prepared_at"])
    _verify_counts(conversion, manifest["sources"]["expected_counts"])
    saved = package_bytes("bundle.json")
    if digest(saved) != manifest["bundle_sha256"] or deserialize_bundle(saved.decode()) != conversion.bundle:
        fail("bundle_mismatch", "package", "Bundle does not match the verified original catalog")
    if manifest["index_rows"] != list(conversion.index_rows) or manifest["counts"] != conversion.counts:
        fail("mapping_mismatch", "package", "Source row mapping or counts were changed")
    return PreparedImport(manifest, conversion, raw_catalog)


def _write_private(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink()
        raise


def prepare_legacy_import(inventory_path, data_root, *, household_id, dataset_key):
    """Copy only original JPEG bytes and index data; never execute the old scripts."""
    inventory_raw = Path(inventory_path).read_bytes()
    inventory = read_json(inventory_raw)
    source = Path(inventory["source_root"]).resolve()
    files = inventory["files"]
    def source_file(suffix):
        matches = [row for row in files if row["path"] == suffix]
        if len(matches) != 1:
            fail("missing_source", suffix, "Expected exactly one inventoried source")
        return matches[0]
    catalog_record = source_file("documents/v3/question_catalog.json")
    groups_record = source_file("documents/v3/question_catalog.py")
    catalog_raw = checked_bytes(source, catalog_record)
    groups_source = checked_bytes(source, groups_record)
    try:
        assignments = [node for node in ast.parse(groups_source).body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "GROUPS" for target in node.targets)]
        if len(assignments) != 1:
            raise ValueError("Ambiguous GROUPS")
        groups = ast.literal_eval(assignments[0].value)
    except (SyntaxError, ValueError, TypeError):
        fail("invalid_groups_source", "GROUPS", "Expected one literal group dictionary")
    now = datetime.now(timezone.utc).isoformat()
    photos, images = [], {}
    for record in files:
        if record["kind"] != "source_photo":
            continue
        match = re.fullmatch(r"IMG_\d{8}_(\d{6})\.jpg", PurePosixPath(record["path"]).name, re.IGNORECASE)
        if not match or match[1] in images:
            fail("ambiguous_photo_token", "photos", "Photo token must resolve to exactly one source")
        raw = checked_bytes(source, record)
        width, height = image_dimensions(raw)
        token, sha = match[1], record["sha256"]
        key = f"originals/{sha}.jpg"
        photo = {**record, "token": token, "image_id": f"image-{sha}", "storage_key": key, "width": width, "height": height}
        photos.append(photo)
        images[token] = SourceImage(photo["image_id"], household_id, sha, key, "image/jpeg", width, height, inventory["created_at"])
    conversion = build_legacy_bundle(read_json(catalog_raw), groups, images, household_id=household_id,
                                     dataset_key=dataset_key, recorded_at=now)
    _verify_counts(conversion, inventory["counts"])
    groups_raw = canonical(groups)
    manifest = {"schema": PACKAGE_SCHEMA, "household_id": household_id, "dataset_key": dataset_key, "prepared_at": now,
        "sources": {"inventory_sha256": digest(inventory_raw), "source_root": str(source), "catalog": catalog_record,
            "groups_source": groups_record, "groups": groups, "photos": photos,
            "image_recorded_at": inventory["created_at"], "expected_counts": inventory["counts"]},
        "groups_sha256": digest(groups_raw), "counts": conversion.counts, "index_rows": list(conversion.index_rows)}
    manifest["source_digest"] = _source_fingerprint(manifest)
    scope = digest(canonical([household_id, dataset_key]))[:24]
    data_root = Path(data_root).resolve()
    data_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    originals, imports = data_root / "originals", data_root / "imports"
    originals.mkdir(mode=0o700, exist_ok=True)
    imports.mkdir(mode=0o700, exist_ok=True)
    for directory in (data_root, originals, imports):
        if directory.stat().st_mode & 0o077 or not directory.resolve().is_relative_to(data_root):
            fail("unsafe_data_root", "data_root", "Private storage directories require mode 0700 and no escaping symlinks")
    destination = imports / scope
    lock_path = confined(data_root, ".legacy-import.lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if destination.exists():
            prepared = load_prepared_import(destination, data_root)
            if prepared.manifest["source_digest"] != manifest["source_digest"]:
                fail("import_source_conflict", "dataset_key", "Dataset key already has different source bytes")
            return destination, prepared
        temporary = Path(tempfile.mkdtemp(prefix=".preparing-", dir=imports))
        created_photos = []
        try:
            for photo in photos:
                raw = checked_bytes(source, photo)
                target = confined(data_root, photo["storage_key"])
                if target.exists():
                    checked_bytes(data_root, {**photo, "path": photo["storage_key"]})
                else:
                    _write_private(target, raw)
                    created_photos.append(target)
            bundle_raw = serialize_bundle(conversion.bundle).encode()
            manifest["bundle_sha256"] = digest(bundle_raw)
            _write_private(temporary / "catalog.source.json", catalog_raw)
            _write_private(temporary / "groups.json", groups_raw)
            _write_private(temporary / "bundle.json", bundle_raw)
            _write_private(temporary / "manifest.json", canonical(manifest))
            # Validate all completed copies before making the package visible.
            prepared = load_prepared_import(temporary, data_root)
            temporary.rename(destination)
            return destination, prepared
        except BaseException:
            shutil.rmtree(temporary)
            for path in created_photos:
                path.unlink()
            raise
