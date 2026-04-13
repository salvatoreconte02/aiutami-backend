from django.urls import path

from .views import NasaRankingView, NasaRankingStatusView, NasaRankingSubmitView

urlpatterns = [
    path(
        "sessions/<uuid:session_id>/ranking/",
        NasaRankingView.as_view(),
        name="nasa_ranking",
    ),
    path(
        "sessions/<uuid:session_id>/ranking/submit/",
        NasaRankingSubmitView.as_view(),
        name="nasa_ranking_submit",
    ),
    path(
        "sessions/<uuid:session_id>/ranking-status/",
        NasaRankingStatusView.as_view(),
        name="nasa_ranking_status",
    ),
]
