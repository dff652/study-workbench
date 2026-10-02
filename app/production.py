"""Production settings for the single-host container deployment."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

SWB_PRODUCTION = True


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Set {name} explicitly for the production service")
    return value


def _flag(name, *, default=False):
    value = os.environ.get(name, "true" if default else "false").strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ImproperlyConfigured(f"{name} must be true or false")
    return value in {"true", "1", "yes"}


_required("SWB_DB_PASSWORD")
SWB_SECRET_KEY = _required("SWB_SECRET_KEY")
SWB_DATA_ROOT = _required("SWB_DATA_ROOT")
if not Path(SWB_DATA_ROOT).is_absolute():
    raise ImproperlyConfigured("SWB_DATA_ROOT must be an absolute private-volume path")

ALLOWED_HOSTS = [host.strip() for host in _required("SWB_ALLOWED_HOSTS").split(",") if host.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("SWB_ALLOWED_HOSTS must contain at least one host")

CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.environ.get("SWB_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

STATIC_ROOT = os.environ.get("SWB_STATIC_ROOT", "/tmp/study-workbench-static")
MIDDLEWARE = [MIDDLEWARE[0], "whitenoise.middleware.WhiteNoiseMiddleware", *MIDDLEWARE[1:]]  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

_trust_proxy = _flag("SWB_TRUST_PROXY_HEADERS")
SECURE_SSL_REDIRECT = _flag("SWB_SECURE_SSL_REDIRECT")
SESSION_COOKIE_SECURE = _flag("SWB_SECURE_COOKIES")
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
if _trust_proxy:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
elif SECURE_SSL_REDIRECT or SESSION_COOKIE_SECURE:
    raise ImproperlyConfigured(
        "HTTPS redirects and secure cookies require SWB_TRUST_PROXY_HEADERS=true behind a trusted TLS proxy"
    )
else:
    SECURE_PROXY_SSL_HEADER = None

SECURE_REFERRER_POLICY = "same-origin"
