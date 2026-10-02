from django.urls import path

from . import knowledge_views as views

app_name = "knowledge"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/<str:kind>/", views.node_new, name="node_new"),
    path("entity/<int:entity_id>/", views.node_detail, name="node_detail"),
    path("entity/<int:entity_id>/edit/", views.node_edit, name="node_edit"),
    path("entity/<int:entity_id>/link/", views.node_link, name="node_link"),
    path("entity/<int:entity_id>/review/", views.review, name="review"),
    path("question/<int:entity_id>/", views.question_detail, name="question_detail"),
    path("question/<int:entity_id>/link/", views.question_link, name="question_link"),
    path("source/<int:image_id>/original/", views.source_image, name="source_image"),
]
