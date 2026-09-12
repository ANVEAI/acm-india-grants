"""
URL configuration for soilMoisture project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
import os



urlpatterns = [
    path('', include('home.urls')),
   path('api/', include('backend.urls')),
   re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),

    # For serving static files
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
    re_path(r'^bills/(?P<path>.*)$', serve, {
        'document_root': os.path.join(os.path.dirname(settings.BASE_DIR), 'bills')
    }),
]

