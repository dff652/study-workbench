import tempfile
import unittest
from unittest.mock import patch

from app.domain import ContractError
from app.imports.package import (canonical, checked_bytes, confined, digest, load_prepared_import,
    prepare_legacy_import, read_json)
from .fixtures import source_fixture


class PrivatePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.inventory, self.source, self.data, self.description = source_fixture(self.temporary.name)

    def prepare(self):
        return prepare_legacy_import(self.inventory, self.data, household_id="synthetic-household", dataset_key="synthetic-v1")

    def test_original_bytes_private_permissions_and_repeat_stability(self):
        before = {r["path"]: checked_bytes(self.source, r) for r in self.description["files"]}
        directory, prepared = self.prepare()
        again, repeated = self.prepare()
        self.assertEqual(directory, again)
        self.assertEqual(prepared, repeated)
        for photo in prepared.manifest["sources"]["photos"]:
            self.assertEqual((self.data / photo["storage_key"]).read_bytes(), before[photo["path"]])
        for relative, raw in before.items():
            self.assertEqual((self.source / relative).read_bytes(), raw)
        for path in self.data.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
        self.assertEqual(load_prepared_import(directory, self.data), prepared)
        self.assertEqual(prepared.conversion.counts["question_entities"], 4)

    def test_stale_inventory_fails_before_copying(self):
        (self.source / self.description["files"][0]["path"]).write_bytes(b"[]")
        with self.assertRaises(ContractError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.issues[0].code, "source_hash_mismatch")
        self.assertFalse(self.data.exists())

    def test_changed_registered_source_does_not_replace_existing_package(self):
        directory, prepared = self.prepare()
        original = (directory / "manifest.json").read_bytes()
        record = self.description["files"][0]
        changed = read_json((self.source / record["path"]).read_bytes())
        changed[0]["feature"] = "New source summary"
        raw = canonical(changed)
        (self.source / record["path"]).write_bytes(raw)
        record.update(size_bytes=len(raw), sha256=digest(raw))
        self.inventory.write_bytes(canonical(self.description))
        with self.assertRaises(ContractError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.issues[0].code, "import_source_conflict")
        self.assertEqual((directory / "manifest.json").read_bytes(), original)
        self.assertEqual(load_prepared_import(directory, self.data), prepared)

    def test_corrupted_saved_photo_or_bundle_is_rejected(self):
        directory, prepared = self.prepare()
        photo = self.data / prepared.manifest["sources"]["photos"][0]["storage_key"]
        original = photo.read_bytes()
        photo.write_bytes(b"bad")
        with self.assertRaises(ContractError):
            load_prepared_import(directory, self.data)
        photo.write_bytes(original)
        (directory / "bundle.json").write_bytes(b"{}")
        with self.assertRaises(ContractError) as caught:
            load_prepared_import(directory, self.data)
        self.assertEqual(caught.exception.issues[0].code, "bundle_mismatch")

    def test_duplicate_json_and_path_escape_are_rejected(self):
        with self.assertRaises(ContractError):
            read_json(b'{"a":1,"a":2}')
        with self.assertRaises(ContractError):
            read_json(b'{"a":NaN}')
        for relative in ("../inventory.local.json", "/etc/passwd"):
            with self.assertRaises(ContractError):
                confined(self.source, relative)
        (self.source / "escape").symlink_to(self.inventory)
        with self.assertRaises(ContractError):
            confined(self.source, "escape")

    def test_late_copy_failure_removes_only_its_new_files(self):
        from app.imports import package
        writer = package._write_private
        def failing_writer(path, raw):
            if path.name == "groups.json":
                raise OSError("Synthetic late failure")
            return writer(path, raw)
        with patch("app.imports.package._write_private", side_effect=failing_writer):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(list((self.data / "originals").iterdir()), [])
        self.assertEqual(list((self.data / "imports").iterdir()), [])
        self.prepare()  # A failed preparation does not poison the next import.

    def test_public_data_directory_is_rejected(self):
        self.data.mkdir(mode=0o755)
        self.data.chmod(0o755)
        with self.assertRaises(ContractError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.issues[0].code, "unsafe_data_root")

    def test_geometry_profile_is_bound_to_private_package_and_repeatable(self):
        catalog = self.description['files'][0]
        entries = read_json((self.source / catalog['path']).read_bytes())
        entries[0].update(book='J3', num='1(左)', photo='000001+000002', aux='Synthetic auxiliary')
        entries[1].update(book='W5')
        raw = canonical(entries)
        (self.source / catalog['path']).write_bytes(raw)
        catalog.update(size_bytes=len(raw), sha256=digest(raw))
        self.description['counts']['by_book'] = {'J3':1,'W5':1}
        self.inventory.write_bytes(canonical(self.description))
        profile = {'format_id':'geometry.v1','auxiliary_mapping':{'Synthetic auxiliary':5}}
        directory, prepared = prepare_legacy_import(self.inventory, self.data,
            household_id='synthetic-household', dataset_key='geometry-v1', profile=profile)
        self.assertEqual(load_prepared_import(directory,self.data),prepared)
        self.assertEqual(prepared.manifest['sources']['profile'],profile)
        self.assertEqual(prepared.conversion.index_rows[0]['num'],'1(左)')
        self.assertEqual(prepared.conversion.index_rows[0]['photo_tokens'],['000001','000002'])
        again, repeated = prepare_legacy_import(self.inventory,self.data,
            household_id='synthetic-household',dataset_key='geometry-v1',profile=profile)
        self.assertEqual((again,repeated),(directory,prepared))
        with self.assertRaises(ContractError) as caught:
            prepare_legacy_import(self.inventory,self.data,household_id='synthetic-household',
                dataset_key='geometry-v1',profile={**profile,'auxiliary_mapping':{'Synthetic auxiliary':2}})
        self.assertEqual(caught.exception.issues[0].code,'import_source_conflict')
        self.assertEqual(load_prepared_import(directory,self.data),prepared)
