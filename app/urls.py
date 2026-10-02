from django.urls import include, path
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [path('accounts/login/', LoginView.as_view(template_name='web/login.html'), name='login'),
               path('accounts/logout/', LogoutView.as_view(), name='logout'),
               path('', include('app.web.urls'))]
