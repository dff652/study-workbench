"""Configuration and health checks for the container production entrypoint."""
import json
import os
import subprocess
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def service_environment(**overrides):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SWB_")}
    environment.update({
        "DJANGO_SETTINGS_MODULE": "app.production",
        "SWB_SECRET_KEY": "synthetic-test-secret",
        "SWB_DATA_ROOT": "/private",
        "SWB_DB_HOST": "db",
        "SWB_DB_NAME": "study_workbench_test",
        "SWB_DB_USER": "study_workbench_test",
        "SWB_DB_PASSWORD": "synthetic-test-password",
        "SWB_ALLOWED_HOSTS": "127.0.0.1, example.test",
        "SWB_CSRF_TRUSTED_ORIGINS": "https://example.test",
        "SWB_SECURE_SSL_REDIRECT": "false",
        "SWB_SECURE_COOKIES": "false",
        "SWB_TRUST_PROXY_HEADERS": "false",
    })
    environment.update(overrides)
    return environment


def run_python(source, environment):
    return subprocess.run(
        [sys.executable, "-c", source], cwd=ROOT, env=environment,
        text=True, capture_output=True, check=False,
    )


class ProductionSettingsTests(unittest.TestCase):
    def test_required_production_settings_and_static_storage(self):
        source = """
import json
from django.conf import settings
print(json.dumps({
    'debug': settings.DEBUG,
    'hosts': settings.ALLOWED_HOSTS,
    'white_noise': settings.MIDDLEWARE[1],
    'storage': settings.STORAGES['staticfiles']['BACKEND'],
    'root': settings.STATIC_ROOT,
    'db_host': settings.DATABASES['default']['HOST'],
}))
"""
        result = run_python(
            source,
            service_environment(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertFalse(settings["debug"])
        self.assertEqual(settings["hosts"], ["127.0.0.1", "example.test"])
        self.assertEqual(settings["white_noise"], "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertEqual(settings["storage"], "whitenoise.storage.CompressedManifestStaticFilesStorage")
        self.assertEqual(settings["root"], "/tmp/study-workbench-static")
        self.assertEqual(settings["db_host"], "db")

    def test_missing_password_and_empty_host_list_fail_closed(self):
        missing_password = service_environment()
        del missing_password["SWB_DB_PASSWORD"]
        result = run_python("from django.conf import settings; print(settings.DEBUG)", missing_password)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWB_DB_PASSWORD", result.stderr)

        result = run_python(
            "from django.conf import settings; print(settings.DEBUG)",
            service_environment(SWB_ALLOWED_HOSTS=", ,"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWB_ALLOWED_HOSTS", result.stderr)

    def test_secure_cookie_mode_requires_and_accepts_trusted_proxy(self):
        result = run_python(
            "from django.conf import settings; print(settings.DEBUG)",
            service_environment(SWB_SECURE_COOKIES="true"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWB_TRUST_PROXY_HEADERS", result.stderr)

        result = run_python(
            "from django.conf import settings; assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE",
            service_environment(
                SWB_SECURE_SSL_REDIRECT="true",
                SWB_SECURE_COOKIES="true",
                SWB_TRUST_PROXY_HEADERS="true",
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class HealthViewTests(unittest.TestCase):
    def test_health_view_reports_database_readiness(self):
        source = """
import json
from django.db import DatabaseError
from django.test import RequestFactory
from unittest.mock import patch
from app.health import healthz

request = RequestFactory().get('/healthz')
with patch('app.health.connection.cursor') as cursor:
    response = healthz(request)
    assert response.status_code == 200
    cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')
with patch('app.health.connection.cursor', side_effect=DatabaseError('synthetic')):
    response = healthz(request)
    assert response.status_code == 503
    assert json.loads(response.content) == {'status': 'unavailable'}
"""
        result = run_python(
            source,
            service_environment(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
