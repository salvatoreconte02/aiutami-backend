from pathlib import Path
from datetime import timedelta
import os

# Percorso base del progetto
BASE_DIR = Path(__file__).resolve().parent.parent

# Chiave segreta (usa una variabile d'ambiente in produzione)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-change-me")

# Modalità debug (True = attiva)
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

# Host consentiti
ALLOWED_HOSTS = ["*"]

# Applicazioni installate
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Librerie esterne
    "rest_framework",
    "rest_framework_simplejwt",
    "channels",

   
     "apps.accounts",
    # "apps.sessions",
    # "apps.turns",
    # "apps.moderation",
    # "apps.realtime",
    # "apps.asr",
    # "apps.notifications",
    # "apps.audit",
    # "apps.exports",
]

# Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

# URL principale
ROOT_URLCONF = "aiutami.urls"

# Template (per le pagine admin o future viste HTML)
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# WSGI (per compatibilità)
WSGI_APPLICATION = "aiutami.wsgi.application"

# Database (PostgreSQL)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("PGDATABASE", "aiutami"),
        "USER": os.getenv("PGUSER", "aiutami"),
        "PASSWORD": os.getenv("PGPASSWORD", "aiutami"),
        "HOST": os.getenv("PGHOST", "localhost"),
        "PORT": os.getenv("PGPORT", "5432"),
    }
}

# Autenticazione REST con JWT
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
      "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

# Lingua e fuso orario
LANGUAGE_CODE = "it-it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

# File statici
STATIC_URL = "static/"

# ASGI (Channels per WebSocket)
ASGI_APPLICATION = "aiutami.asgi.application"

# Configurazione di Redis per Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [os.getenv("REDIS_URL", "redis://localhost:6379/0")],
        },
    },
}

# Configurazione Celery (per i task periodici e i trigger del moderatore)
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}