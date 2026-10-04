from django.urls import path
from . import views
from . import packet_views
from . import diagram_views
app_name='printing'
urlpatterns=[path('',views.index,name='index'),path('arithmetic/',views.arithmetic,name='arithmetic'),path('snapshots/<int:pk>/',views.snapshot,name='snapshot'),
    path('diagrams/<str:pk>/',diagram_views.diagrams,name='diagrams'),
    path('diagrams/files/<int:pk>/<str:name>/',diagram_views.diagram_file,name='diagram_file'),
    path('materials/<uuid:material_id>/five-books/',packet_views.prepare,name='packet_prepare'),
    path('materials/<uuid:material_id>/five-books/<str:packet_id>/',packet_views.detail,name='packet'),
    path('materials/<uuid:material_id>/five-books/<str:packet_id>/download/',packet_views.download,name='packet_download'),
    path('reports/<int:pk>/',views.evidence_report,name='evidence_report'),
    path('snapshots/<int:pk>/<str:name>/',views.download,name='download'),
    path('answers/<str:pk>/',views.answer,name='answer'),path('errata/<str:pk>/',views.erratum,name='erratum')]
