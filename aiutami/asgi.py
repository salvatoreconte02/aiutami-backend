"""
ASGI config for aiutami project.

Gestisce sia HTTP (Django ASGI) sia WebSocket (Channels).
"""

import os

# 1) Setup delle settings Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aiutami.settings")

# 2) Ora è sicuro importare Django/Channels
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

# Import WS routing esistenti
from apps.turns.routing import websocket_urlpatterns as turns_ws_urlpatterns
from apps.sessions.routing import websocket_urlpatterns as sessions_ws_urlpatterns

# 🔹 NUOVO: aggiungiamo il routing WebRTC
from apps.webrtc.routing import websocket_urlpatterns as webrtc_ws_urlpatterns

from apps.turns.ws_auth import JwtAuthMiddlewareStack


django_asgi_app = get_asgi_application()

# 🔹 Routing WebSocket combinato: turns + sessions + webrtc
websocket_urlpatterns = (
    turns_ws_urlpatterns
    + sessions_ws_urlpatterns
    + webrtc_ws_urlpatterns
)

application = ProtocolTypeRouter(
    {
        # HTTP classico (REST API)
        "http": django_asgi_app,

        # WebSockets autenticati via JWT (?token=<ACCESS_TOKEN>)
        "websocket": JwtAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        ),
    }
)