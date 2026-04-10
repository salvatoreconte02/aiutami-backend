from django.urls import path

from .views import SessionVoteView, SessionVoteStatusView

urlpatterns = [
    path(
        "sessions/<uuid:session_id>/vote/",
        SessionVoteView.as_view(),
        name="mm_session_vote",
    ),
    path(
        "sessions/<uuid:session_id>/vote-status/",
        SessionVoteStatusView.as_view(),
        name="mm_session_vote_status",
    ),
]
