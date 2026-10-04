"""Explicit local development settings; production delivery belongs to D1."""
import os

from django.core.exceptions import ImproperlyConfigured


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ImproperlyConfigured(f"Set {name} explicitly before using persistence")
    return value


SECRET_KEY = required("SWB_SECRET_KEY")
DEBUG = False
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "zh-hans"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
INSTALLED_APPS = ["django.contrib.auth", "django.contrib.contenttypes", "app.persistence", "app.imports.apps.ImportsConfig"]
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "HOST": required("SWB_DB_HOST"),
    "NAME": required("SWB_DB_NAME"),
    "USER": required("SWB_DB_USER"),
    "PASSWORD": os.environ.get("SWB_DB_PASSWORD", ""),
    "PORT": os.environ.get("SWB_DB_PORT", "5432"),
    "CONN_MAX_AGE": 0,
}}

# Local manual Web flow; D1 supplies the production server/TLS configuration.
INSTALLED_APPS += ['django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'app.web.apps.WebConfig']
ROOT_URLCONF = 'app.urls'
ALLOWED_HOSTS = [value for value in os.environ.get('SWB_ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(',') if value]
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
              'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
              'django.contrib.auth.middleware.AuthenticationMiddleware', 'app.web.middleware.PrivateResponsesMiddleware',
              'django.contrib.messages.middleware.MessageMiddleware',
              'django.middleware.clickjacking.XFrameOptionsMiddleware']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                  'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages']}}]
TEMPLATES[0]['OPTIONS']['context_processors'].append('app.web.context_processors.release')
STATIC_URL = '/static/'
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
SWB_DATA_ROOT = os.environ.get('SWB_DATA_ROOT')
SWB_FRONTEND_DEFAULT = False
INSTALLED_APPS += ['app.printing.apps.PrintingConfig']
INSTALLED_APPS += ['app.catalogue.apps.CatalogueConfig']
INSTALLED_APPS += ['app.study.apps.StudyConfig']
INSTALLED_APPS += ['app.ai.apps.AIConfig']
INSTALLED_APPS += ['app.operations.apps.OperationsConfig']
INSTALLED_APPS += ['app.workflows.apps.WorkflowsConfig']
FILE_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 30
FILE_UPLOAD_PERMISSIONS = 0o600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
FILE_UPLOAD_HANDLERS = ['app.web.uploads.BoundedUploadHandler',
                        'django.core.files.uploadhandler.MemoryFileUploadHandler',
                        'django.core.files.uploadhandler.TemporaryFileUploadHandler']
