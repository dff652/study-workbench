from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView
from app.health import healthz
from app.web import pwa
from app.api import views as api_views
from app.web import views as web_views

urlpatterns = [path('api/v1/', include('app.api.urls')),
               path('materials/', web_views.index, name='legacy-materials'),
               path('app/assets/<path:name>', api_views.frontend_asset, name='frontend-asset'),
               path('app/', api_views.frontend, name='frontend'),
               path('app/<path:route>', api_views.frontend, name='frontend-route'),
               path('manifest.webmanifest', pwa.manifest, name='pwa-manifest'),
               path('sw.js', pwa.service_worker, name='pwa-worker'),
               path('mobile/', pwa.mobile_help, name='pwa-help'),
               path('accounts/login/', LoginView.as_view(template_name='web/login.html'), name='login'),
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
