from django.urls import path

from . import views


app_name = "operations"

urlpatterns = [
    path("", views.index, name="index"),
    path("household/<str:household_id>/retention/", views.retention_policy,
        name="retention_policy"),
    path("household/<str:household_id>/timing/new/", views.work_timing_new,
        name="work_timing_new"),
]
