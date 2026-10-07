from django.urls import path

from apps.accounts.views import CsrfTokenView, SessionLoginView, SessionLogoutView

app_name = "session_auth"

urlpatterns = [
    path("csrf/", CsrfTokenView.as_view(), name="csrf"),
    path("login/", SessionLoginView.as_view(), name="login"),
    path("logout/", SessionLogoutView.as_view(), name="logout"),
]
