from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard),
    path("index.html", views.dashboard),
    path("api/data", views.data),
    path("api/schema", views.schema),
    path("api/next-epid", views.next_epid),
    path("api/case", views.case),
    path("api/case/update", views.update_case),
    path("api/case/delete", views.delete_case),
    path("api/cases", views.new_case),
    path("api/import", views.import_file),
    path("api/register.xlsx", views.register_xlsx),
    path("api/report.xlsx", views.report),
]
