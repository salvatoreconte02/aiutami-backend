"""
ASGI config for aiutami project.

Gestisce sia HTTP (Django ASGI) sia WebSocket (Channels).
"""

import os

# 1) PRIMA DI TUTTO: setup delle settings Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aiutami.settings")

# 2) Solo ora è sicuro importare Django/Channels e i moduli delle app
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

from apps.turns.routing import websocket_urlpatterns
from apps.turns.ws_auth import JwtAuthMiddlewareStack


django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,

        # WebSockets autenticati via JWT (?token=<ACCESS_TOKEN>)
        "websocket": JwtAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)