from django.urls import path

from . import views

urlpatterns = [
    path("login", views.login_page),
    path("logout", views.logout_view),
    path("password", views.password_page),
    path("profile", views.profile_page),
    path("admin", views.accounts_page),  # the support account's Accounts page; Django's own admin is /django-admin/
    path("api/login", views.login_api),
    path("api/setup", views.login_api),
    path("api/password", views.password_api),
    path("api/me", views.me),
    path("api/profile", views.profile_api),
    path("api/profile/photo", views.photo_api),
    path("api/admin/users", views.users_api),
]
