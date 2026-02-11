from django.urls import path
from .ws_consumer import WebRTCConsumer

websocket_urlpatterns = [
    path("ws/webrtc/<uuid:session_id>/", WebRTCConsumer.as_asgi()),
]