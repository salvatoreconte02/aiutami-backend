from django.urls import path
from .views import MeView, SignupView

urlpatterns = [
    path("me/", MeView.as_view(), name="accounts_me"),
    path("signup/", SignupView.as_view(), name="accounts_signup"),
]
