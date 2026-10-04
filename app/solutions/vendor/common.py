"""Small shared I/O contract for private, append-only workflow artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


class WorkflowError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def fail(code: str, message: str):
    raise WorkflowError(code, message)


class WorkflowArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        fail('invalid_arguments', 'Command-line arguments do not match the tool contract')


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "JSON object contains a repeated key")
        result[key] = value
    return result


def read_json(path, max_bytes=16 * 1024 * 1024):
    path = Path(path)
    assert_no_symlinks(path)
    try:
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            fail("input_too_large", "JSON exceeds the configured input limit")
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: fail("invalid_json", "Non-finite JSON number"))
    except WorkflowError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise WorkflowError("invalid_json", "Could not read bounded UTF-8 JSON") from exc


def assert_no_symlinks(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            fail("symlink_path", "Symlink paths are not allowed for workflow I/O")


def root_path(path, must_exist=True):
    assert_no_symlinks(path)
    root = Path(path).resolve()
    if must_exist and not root.is_dir():
        fail("missing_root", "Configured root must be an existing directory")
    return root


def resolve_under(root, key, must_exist=True):
    root = root_path(root)
    if not isinstance(key, str) or not key or Path(key).is_absolute() or ".." in Path(key).parts:
        fail("path_escape", "Storage key must be a relative path without parent traversal")
    path = root / key
    assert_no_symlinks(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(root) or resolved == root:
        fail("path_escape", "Storage key must resolve inside its configured root")
    if must_exist and not resolved.is_file():
        fail("missing_file", "Referenced file is missing")
    return resolved


def ensure_output_outside(source_root, output):
    root = root_path(source_root)
    assert_no_symlinks(output)
    output = Path(output).resolve()
    if output.is_relative_to(root):
        fail("source_output_overlap", "Outputs must stay outside the original source tree")


def write_json(path, value, *, replace=False):
    """Same content is an idempotent no-op; different content conflicts by default."""
    path = Path(path)
    assert_no_symlinks(path)
    data = canonical(value) + b"\n"
    if path.exists():
        if not path.is_file():
            fail("output_conflict", "Output key exists and is not a regular file")
        if path.read_bytes() == data:
            return False
        if not replace:
            fail("output_conflict", "Output exists with different content; use a new version")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    fail("output_conflict", "Concurrent output has different content")
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


def cli_result(function):
    try:
        print(json.dumps(function(), ensure_ascii=False, allow_nan=False))
        return 0
    except WorkflowError as exc:
        print(json.dumps({"status": "error", "code": exc.code, "message": str(exc)}, ensure_ascii=False))
        return 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"status": "error", "code": "invalid_input", "message": str(exc)}, ensure_ascii=False))
        return 2
