from django.urls import path

from apps.health.views import LivenessView, ReadinessView

app_name = "health"
urlpatterns = [
    path("live/", LivenessView.as_view(), name="live"),
    path("ready/", ReadinessView.as_view(), name="ready"),
]
