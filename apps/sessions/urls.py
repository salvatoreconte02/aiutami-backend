from django.urls import path
from .views import (
    InvitationCreateView,
    JoinByTokenView,
    MySessionsListView,
    ParticipantsListView,
    SessionCreateView,
    SessionDetailView,
    SessionStartView,
)

urlpatterns = [
    # Sessioni
    path("", SessionCreateView.as_view(), name="session_create"),                     # POST /
    path("mine/", MySessionsListView.as_view(), name="session_mine"),                 # GET /mine/
    path("<uuid:session_id>/", SessionDetailView.as_view(), name="session_detail"),   # GET /<id>/
    path("<uuid:session_id>/start/", SessionStartView.as_view(), name="session_start"),  # POST /<id>/start/

    # Partecipanti
    path(
        "<uuid:session_id>/participants/",
        ParticipantsListView.as_view(),
        name="session_participants"
    ),  # GET /<id>/participants/

    # Inviti
    path(
        "<uuid:session_id>/invitations/",
        InvitationCreateView.as_view(),
        name="session_invite_create"
    ),  # POST /<id>/invitations/

    # Join via token
    path(
        "join_by_token/",
        JoinByTokenView.as_view(),
        name="session_join_by_token"
    ),  # POST /join_by_token/
]