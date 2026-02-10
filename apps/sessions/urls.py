from django.urls import path
from django.conf import settings

from .views import (
    InvitationCreateView,
    JoinByTokenView,
    MySessionsListView,
    ParticipantsListView,
    SessionCreateView,
    SessionDetailView,
    SessionStartView,
    SessionDebugForceCloseView,
    SessionReadyToConcludeView,
    SessionVoteView,
    SessionVoteStatusView,
    SessionCloseView,
)

urlpatterns = [
    # Sessioni
    path("", SessionCreateView.as_view(), name="session_create"),                     # POST /
    path("mine/", MySessionsListView.as_view(), name="session_mine"),                 # GET /mine/
    path("<uuid:session_id>/", SessionDetailView.as_view(), name="session_detail"),   # GET /<id>/
    path("<uuid:session_id>/start/", SessionStartView.as_view(), name="session_start"),  # POST /<id>/start/

    #  pronto alla conclusione
    path(
        "<uuid:session_id>/ready_to_conclude/",
        SessionReadyToConcludeView.as_view(),
        name="session_ready_to_conclude",
    ),  # POST /<id>/ready_to_conclude/

    # Votazione
    path(
        "<uuid:session_id>/vote/",
        SessionVoteView.as_view(),
        name="session_vote",
    ),  # POST /<id>/vote/
    path(
        "<uuid:session_id>/vote-status/",
        SessionVoteStatusView.as_view(),
        name="session_vote_status",
    ),  # GET /<id>/vote-status/
    path(
        "<uuid:session_id>/close/",
        SessionCloseView.as_view(),
        name="session_close",
    ),  # POST /<id>/close/

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

if settings.DEBUG:
    urlpatterns += [
        path(
            "<uuid:id>/debug_force_close/",
            SessionDebugForceCloseView.as_view(),
            name="session-debug-force-close",
        ),
    ]