from pathlib import Path
from datetime import timedelta
import os

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret-key-change-me")

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")

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
    "corsheaders",

   
     "apps.accounts",
     "apps.sessions.apps.SessionsConfig",   #label unica per session -> confltto con quella d django
     "apps.turns.apps.TurnsConfig",
     "apps.asr.apps.AsrConfig",
     "apps.reports",
     "apps.tasks.apps.TasksConfig",
]

# Middleware
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
]

CORS_ALLOW_CREDENTIALS = True



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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "aiutami"),
        "USER": os.getenv("POSTGRES_USER", "postgres"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
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
STATIC_ROOT = Path(__file__).resolve().parent.parent / "staticfiles"

# ASGI (Channels per WebSocket)
ASGI_APPLICATION = "aiutami.asgi.application"

# Configurazione di Redis per Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)]        },
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
# OpenAI (LLM + STT + TTS)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
OPENAI_STT_LANGUAGE = os.getenv("OPENAI_STT_LANGUAGE", "it")
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")

# Logging: silenzia il rumore degli scanner internet che bussano con
# hostname non in ALLOWED_HOSTS. Django emette un traceback completo per
# ogni DisallowedHost: su VPS pubblico sono decine al minuto e nascondono
# i log utili. Le richieste vengono comunque rifiutate con 400 (Django
# fa il suo lavoro), silenziamo solo l'output a log.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "django.security.DisallowedHost": {
            "handlers": [],
            "propagate": False,
        },
    },
}
