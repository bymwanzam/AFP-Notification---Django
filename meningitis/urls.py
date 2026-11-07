from django.urls import path

from . import views

urlpatterns = [
    path("meningitis", views.men_page),
    path("api/men/data", views.data),
    path("api/men/cases", views.case_list),
    path("api/men/case", views.case_detail),
    path("api/men/case/save", views.save_case),
    path("api/men/case/delete", views.delete_case),
    path("api/men/next-epid", views.next_epid),
    path("api/men/report", views.report),
    path("api/men/report.xlsx", views.report_xlsx),
    path("api/men/linelist.xlsx", views.linelist_xlsx),
    path("api/men/template.xlsx", views.template_xlsx),
    path("api/men/import", views.import_file),
    path("api/men/subdistricts", views.save_subdistricts),
    path("api/men/thresholds", views.save_thresholds),
]
