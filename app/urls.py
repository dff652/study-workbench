from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView
from app.health import healthz

urlpatterns = [path('accounts/login/', LoginView.as_view(template_name='web/login.html'), name='login'),
               path('accounts/logout/', LogoutView.as_view(), name='logout'),
               path('healthz', healthz, name='healthz'),
               path('knowledge/', include('app.web.knowledge_urls')),
               path('learning/', include('app.web.learning_urls')),
               path('catalogue/', include('app.catalogue.urls')),
               path('study/', include('app.study.urls')),
               path('ai/', include('app.ai.urls')),
               path('operations/', include('app.operations.urls')),
               path('prints/', include('app.printing.urls')),
               path('', include('app.web.urls'))]
