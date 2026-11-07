from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("start", views.start),
    path("api/region", views.region),
    path("favicon.ico", RedirectView.as_view(url="/static/core/img/ghs-emblem.png")),
]
