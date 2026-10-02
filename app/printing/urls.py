from django.urls import path
from . import views
app_name='printing'
urlpatterns=[path('',views.index,name='index'),path('arithmetic/',views.arithmetic,name='arithmetic'),path('snapshots/<int:pk>/',views.snapshot,name='snapshot'),
    path('reports/<int:pk>/',views.evidence_report,name='evidence_report'),
    path('snapshots/<int:pk>/<str:name>/',views.download,name='download'),
    path('answers/<str:pk>/',views.answer,name='answer'),path('errata/<str:pk>/',views.erratum,name='erratum')]
