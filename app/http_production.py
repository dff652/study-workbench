"""Optional direct HTTP listener; HTTPS keeps using app.production."""
from django.core.exceptions import ImproperlyConfigured

from .production import *  # noqa: F403

if SECURE_SSL_REDIRECT or SESSION_COOKIE_SECURE or SECURE_PROXY_SSL_HEADER:  # noqa: F405
    raise ImproperlyConfigured("HTTP requires redirects, secure cookies and proxy trust to be disabled")

# Cookies are scoped by host/path, not port. Keep the HTTP login separate.
SESSION_COOKIE_NAME = "swb_http_sessionid"
CSRF_COOKIE_NAME = "swb_http_csrftoken"
