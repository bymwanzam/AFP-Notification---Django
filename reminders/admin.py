from django.contrib import admin

from .models import DistrictContact, ReminderLog


@admin.register(DistrictContact)
class DistrictContactAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "district", "region", "active")
    list_filter = ("region", "active")
    search_fields = ("name", "phone", "district")


@admin.register(ReminderLog)
class ReminderLogAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "epid", "stage", "district", "contact", "phone", "ok")
    list_filter = ("region", "ok", "stage")
    search_fields = ("epid", "phone", "contact")
    readonly_fields = [f.name for f in ReminderLog._meta.fields]
