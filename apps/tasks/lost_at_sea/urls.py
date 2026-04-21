from django.urls import path

from .views import LostAtSeaRankingView, LostAtSeaRankingStatusView, LostAtSeaRankingSubmitView

urlpatterns = [
    path(
        "sessions/<uuid:session_id>/ranking/",
        LostAtSeaRankingView.as_view(),
        name="lost_at_sea_ranking",
    ),
    path(
        "sessions/<uuid:session_id>/ranking/submit/",
        LostAtSeaRankingSubmitView.as_view(),
        name="lost_at_sea_ranking_submit",
    ),
    path(
        "sessions/<uuid:session_id>/ranking-status/",
        LostAtSeaRankingStatusView.as_view(),
        name="lost_at_sea_ranking_status",
    ),
]
