from django.urls import path

from .ws_consumer import SessionsConsumer

websocket_urlpatterns = [
    # Esempio:
    # ws://<host>/ws/sessions/<session_id>/
    path(
        "ws/sessions/<uuid:session_id>/",
        SessionsConsumer.as_asgi(),
        name="sessions_consumer",
    ),
]