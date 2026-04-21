from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Endpoint JWT
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Accounts
    path("api/accounts/", include("apps.accounts.urls")),

    # Sessions
    path("api/sessions/", include("apps.sessions.urls")),

    # Reports (montato sotto il path sessions per /api/sessions/{id}/report/)
    path("api/sessions/", include("apps.reports.urls")),

    # Task-specific endpoints
    path("api/tasks/murder-mystery/", include("apps.tasks.murder_mystery.urls")),
    path("api/tasks/lost-at-sea/", include("apps.tasks.lost_at_sea.urls")),
    path("api/tasks/nasa-moon/", include("apps.tasks.nasa_moon.urls")),
]
