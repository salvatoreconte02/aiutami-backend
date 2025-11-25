# apps/turns/routing.py

from django.urls import path
from .ws_consumer import TurnsConsumer

websocket_urlpatterns = [
    path("ws/turns/<uuid:session_id>/", TurnsConsumer.as_asgi()),
]