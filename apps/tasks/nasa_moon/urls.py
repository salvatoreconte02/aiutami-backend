from django.urls import path

from .views import NasaRankingView, NasaRankingStatusView

urlpatterns = [
    path(
        "sessions/<uuid:session_id>/ranking/",
        NasaRankingView.as_view(),
        name="nasa_ranking",
    ),
    path(
        "sessions/<uuid:session_id>/ranking-status/",
        NasaRankingStatusView.as_view(),
        name="nasa_ranking_status",
    ),
]
