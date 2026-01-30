from django.urls import path

from .views import SessionReportDownloadView

urlpatterns = [
    path(
        "<uuid:session_id>/report/",
        SessionReportDownloadView.as_view(),
        name="session_report_download",
    ),
]
