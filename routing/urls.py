from django.urls import path

from .views import HealthView, RoutePlanView

urlpatterns = [
    path("health/", HealthView.as_view()),
    path("route-plan/", RoutePlanView.as_view()),
]
