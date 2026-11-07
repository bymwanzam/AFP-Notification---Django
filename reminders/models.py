"""Who gets the AFP 60-day follow-up reminders by SMS, and what was sent."""
from django.conf import settings
from django.db import models


class DistrictContact(models.Model):
    """A district surveillance officer (or anyone else) who gets the reminders for a district's cases. A blank
    district means every district of the region (e.g. the regional surveillance officer)."""
    region = models.CharField(max_length=40)
    district = models.CharField(max_length=80, blank=True, help_text="Org unit district name; blank for the whole region.")
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=12, help_text="233XXXXXXXXX")
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["region", "district", "name"]
        constraints = [models.UniqueConstraint(fields=["region", "district", "phone"], name="sms_contact_unique")]

    def __str__(self):
        return f"{self.name} ({self.district or self.region + ' Region'})"


class ReminderLog(models.Model):
    """One case's reminder at one stage to one phone. A stage is "soon" (the last days before day 60) or
    "past-N" (the N-th week overdue), so each is sent once, and a failed send is tried again on the next run."""
    epid = models.CharField(max_length=30, db_index=True)
    stage = models.CharField(max_length=12)
    region = models.CharField(max_length=40)
    district = models.CharField(max_length=80)
    phone = models.CharField(max_length=12)
    contact = models.CharField(max_length=80, blank=True)
    ok = models.BooleanField(default=False)
    reference = models.CharField(max_length=60, blank=True)
    error = models.CharField(max_length=300, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+",
                                help_text="Empty when the daily job sent it.")

    class Meta:
        ordering = ["-sent_at", "-id"]
        indexes = [models.Index(fields=["epid", "stage", "phone"])]
