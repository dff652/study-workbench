from django.urls import path
from . import views
from . import workflow_views as workflow
from . import progress_views as progress
from . import content_views as content
from . import preparation_views as preparation

app_name = "api"
urlpatterns = [
    path("session/", views.session, name="session"),
    path("about/", views.about, name="about"),
    path("learners/", views.learners, name="learners"),
    path("learners/<str:learner_id>/overview/", views.overview, name="overview"),
    path("learners/<str:learner_id>/attempts/", views.attempts, name="attempts"),
    path("progress/", progress.materials, name="progress"),
    path("learners/<str:learner_id>/progress/", progress.learner, name="learner_progress"),
    path("learners/<str:learner_id>/schedules/options/", progress.options, name="schedule_options"),
    path("learners/<str:learner_id>/schedules/", progress.schedules, name="schedules"),
    path("schedules/<int:schedule_id>/actions/", progress.action, name="schedule_action"),
    path("materials/", workflow.material_list, name="materials"),
    path("materials/create/", workflow.material_create, name="material_create"),
    path("materials/<uuid:material_id>/", workflow.material_detail, name="material_detail"),
    path("materials/<uuid:material_id>/content/", content.material_content, name="material_content"),
    path("materials/<uuid:material_id>/content/draft/", content.draft, name="content_draft"),
    path("materials/<uuid:material_id>/erratum/", content.erratum, name="material_erratum"),
    path("pages/<uuid:page_id>/reading/", content.reading, name="page_reading"),
    path("materials/<uuid:material_id>/upload/", workflow.upload, name="upload"),
    path("materials/<uuid:material_id>/workflows/", workflow.create, name="workflow_create"),
    path("workflows/<uuid:job_id>/", workflow.detail, name="workflow_detail"),
    path("workflows/<uuid:job_id>/preparation/", preparation.workspace, name="preparation"),
    path("workflows/<uuid:job_id>/preparation/<uuid:stage_id>/confirm/", preparation.confirm, name="preparation_confirm"),
    path("workflows/<uuid:job_id>/preparation/<uuid:stage_id>/cancel/", preparation.cancel, name="preparation_cancel"),
    path("workflows/<uuid:job_id>/actions/", workflow.action, name="workflow_action"),
    path("workflows/<uuid:job_id>/download/", workflow.download, name="workflow_download"),
]
