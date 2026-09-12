from django.urls import path
from . import views

urlpatterns = [

    # ==========================
    # AUTHENTICATION
    # ==========================
    path('login/', views.login_view, name='login'),

    # ==========================
    # USER MANAGEMENT (ADMIN)
    # ==========================
    path('api/admin/update-user', views.update_user_admin, name='update_user_admin'),
    path('api/admin/add-user', views.submit_add_user, name='submit_add_user'),

# APIs
path("api/users/add/", views.add_user),
path("api/users/get/", views.get_user),
path("api/users/update/", views.update_user),
path("api/users/toggle/", views.toggle_user),

path('submit-travel-grant/', views.submit_travel_grant, name='submit_travel_grant'),

]
