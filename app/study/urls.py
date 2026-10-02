from django.urls import path

from . import views


app_name = "study"

urlpatterns = [
    path("", views.index, name="index"),
    path("learner/<int:learner_entity_pk>/schedule/new/", views.schedule_new, name="schedule_new"),
    path("schedule/<int:schedule_pk>/", views.schedule_detail, name="schedule_detail"),
    path("learner/<int:learner_entity_pk>/report/", views.report, name="report"),
    path("learner/<int:learner_entity_pk>/report.json", views.report_json, name="report_json"),
]
