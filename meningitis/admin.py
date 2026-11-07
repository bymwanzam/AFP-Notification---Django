from django.contrib import admin

from .models import Case, CaseEdit, SubDistrict, ThresholdConfig


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("epid", "region", "district", "epi_year", "epi_week", "final_classification", "outcome")
    list_filter = ("region", "final_classification", "outcome", "other_region")
    search_fields = ("epid", "last_name", "first_name", "health_facility")
    readonly_fields = ("epid", "epi_year", "epi_week", "created_by", "updated_by", "created_at", "updated_at")


@admin.register(SubDistrict)
class SubDistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "region", "population")
    list_filter = ("region",)
    search_fields = ("name", "district")


@admin.register(ThresholdConfig)
class ThresholdConfigAdmin(admin.ModelAdmin):
    list_display = ("region", "alert_rate", "epidemic_rate", "small_pop_cutoff", "season_start_week")


@admin.register(CaseEdit)
class CaseEditAdmin(admin.ModelAdmin):
    list_display = ("at", "epid", "region", "user", "action")
    list_filter = ("region", "action")
    search_fields = ("epid",)
    readonly_fields = [f.name for f in CaseEdit._meta.fields]
