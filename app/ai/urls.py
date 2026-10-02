from django.urls import path

from . import views


app_name = "ai"

urlpatterns = [
    path("", views.index, name="index"),
    path("config/<str:household_id>/", views.config, name="config"),
    path("new/<str:household_id>/<str:task_kind>/", views.run_new, name="run_new"),
    path("new/<str:household_id>/<str:task_kind>/create/", views.run_create, name="run_create"),
    path("run/<uuid:run_id>/", views.run_detail, name="run_detail"),
    path("run/<uuid:run_id>/execute/", views.run_execute, name="run_execute"),
    path("run/<uuid:run_id>/cancel/", views.run_cancel, name="run_cancel"),
    path("run/<uuid:run_id>/apply/", views.run_apply, name="run_apply"),
]
