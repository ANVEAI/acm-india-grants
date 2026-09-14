
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('travel-grant-form/', views.travel_grant_form, name='travel_grant_form'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('help/', views.help_page, name='help'),
    path('budget-management/', views.budget_management, name='budget_management'),
    path('add_user/', views.add_user, name='add_user'),
    path("application/<int:app_id>/", views.application_details, name="application_details"),
    path("application/<int:app_id>/budget/", views.update_budget_details, name="update_budget_details"),
    path('api/get-application-by-tracking/', views.get_application_by_tracking_code, name='get_application_by_tracking'),
    path('api/get-application-details/', views.get_application_details_api, name='get_application_details_api'),
    path('application-details/<str:tracking_code>/', views.application_details_by_tracking, name='application_details_by_tracking'),
    path("application/<int:app_id>/submit-review/", views.submit_review, name="submit_review"),
    path("application/<int:app_id>/submit-final-approval/", views.submit_final_approval, name="submit_final_approval"),
    path('notify-applicant/<int:app_id>/', views.notify_applicant, name='notify_applicant'),
    path('applications/<int:app_id>/reject/', views.reject_application, name='reject_application'),
    path('applications/export/', views.export_applications, name='export_applications'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_update, name='profile'),
]
