from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.index, name="index"),
    path("material/new/", views.material_new, name="material_new"),
    path("material/<uuid:material_id>/", views.material_detail, name="material_detail"),
    path("material/<uuid:material_id>/order/", views.reorder_pages, name="reorder_pages"),
    path("page/<uuid:page_id>/", views.page_detail, name="page_detail"),
    path("page/<uuid:page_id>/preview/<int:rotation>/", views.page_preview, name="page_preview"),
    path("material/<uuid:material_id>/question/new/", views.question_new, name="question_new"),
    path("question/<str:question_id>/", views.question_detail, name="question_detail"),
    path("question/<str:question_id>/edit/", views.question_edit, name="question_edit"),
    path("question/<str:question_id>/review/", views.question_review, name="question_review"),
]
