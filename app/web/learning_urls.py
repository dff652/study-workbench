from django.urls import path

from . import learning_views as views

app_name = "learning"

urlpatterns = [
    path("", views.index, name="index"),
    path("profile/new/", views.profile_new, name="profile_new"),
    path("profile/<str:learner_id>/", views.profile_detail, name="profile_detail"),
    path("observation/new/", views.observation_new, name="observation_new"),
    path("observation/<str:observation_id>/", views.observation_detail, name="observation_detail"),
    path("observation/<str:observation_id>/edit/", views.observation_edit, name="observation_edit"),
    path("profile/<str:learner_id>/attempt/new/", views.attempt_new, name="attempt_new"),
    path("attempt/<str:attempt_id>/", views.attempt_detail, name="attempt_detail"),
    path("attempt/<str:attempt_id>/edit/", views.attempt_edit, name="attempt_edit"),
    path("attempt/<str:attempt_id>/correct/", views.attempt_correct, name="attempt_correct"),
    path("attempt/<str:attempt_id>/assessment/new/", views.assessment_new, name="assessment_new"),
    path("assessment/<str:assessment_id>/", views.assessment_detail, name="assessment_detail"),
    path("assessment/<str:assessment_id>/edit/", views.assessment_edit, name="assessment_edit"),
    path("assessment/<str:assessment_id>/review/", views.assessment_review, name="assessment_review"),
]
