from django.urls import path

from . import views

app_name = "catalogue"

urlpatterns = [
    path("", views.index, name="index"),
    path("merge/", views.merge, name="merge"),
    path("question/<int:entity_id>/", views.question_detail, name="question_detail"),
    path("question/<int:entity_id>/split/", views.question_split, name="question_split"),
]
