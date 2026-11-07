from django.urls import path

from . import views

urlpatterns = [
    path("reminders", views.reminders_page),
    path("api/sms/data", views.data),
    path("api/sms/contacts", views.save_contacts),
    path("api/sms/send", views.send_now),
    path("api/sms/test", views.send_test),
    path("api/sms/settings", views.save_settings),
]
