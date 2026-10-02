import contextlib
import io
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts import manage_private_retention as cli


class RetentionCLIArgumentTests(SimpleTestCase):
    def test_dry_run_cannot_be_combined_with_execution_or_explicit_retirement(self):
        for action in (["--execute"], ["--retire-snapshot", "1"], ["--export-ledger"]):
            with patch("sys.argv", ["maintenance", "--household", "synthetic", "--owner-id", "1",
                    "--dry-run", *action]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as captured:
                    cli._arguments()
                self.assertEqual(captured.exception.code, 2)
