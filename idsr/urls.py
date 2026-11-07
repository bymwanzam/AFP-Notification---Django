from django.urls import path

from . import views

urlpatterns = [
    path("idsr", views.idsr_page),
    path("api/idsr/data", views.data),
    path("api/idsr/form.xlsx", views.form_xlsx),
    path("api/idsr/week.csv", views.week_csv),
    path("api/idsr/store.xlsx", views.store_xlsx),
    path("api/idsr/week", views.save_week),
    path("api/idsr/week/delete", views.delete_week),
    path("api/idsr/import", views.import_file),
    path("api/idsr/settings", views.save_settings),
    path("api/idsr/image", views.image),
    path("api/idsr/dhims2", views.dhims2_config),
    path("api/idsr/dhims2/datasets", views.dhims2_datasets),
    path("api/idsr/dhims2/elements", views.dhims2_elements),
    path("api/idsr/dhims2/connect", views.dhims2_connect),
    path("api/idsr/dhims2/forget", views.dhims2_forget),
    path("api/idsr/dhims2/mapping", views.dhims2_mapping),
    path("api/idsr/dhims2/fetch", views.dhims2_fetch),
]
