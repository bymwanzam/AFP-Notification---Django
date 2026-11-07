"""The site's URLs. The pages call their API with absolute paths and no trailing slash (/api/...), so the paths
below are kept as they were in the local app."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("core.urls")),
    path("", include("idsr.urls")),
    path("", include("meningitis.urls")),
    path("", include("afp.urls")),
]
