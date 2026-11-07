"""The meningitis line list: one Case per patient, the region's sub-districts (with the population the alert and
epidemic thresholds need), each region's threshold settings, and a log of every change to a case.

Regions and districts are the org units of core.orgunits (by name), as in the other modules. A case belongs to the
region that reported it.
"""
from datetime import date

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import choices as ch


def choice(name):
    return [(c, f"{c}-{t}") for c, t in ch.LISTS[name]]


def iso_week(d):
    """(ISO year, ISO week) of a date: Monday to Sunday weeks, week 1 holds the year's first Thursday."""
    y, w, _ = d.isocalendar()
    return y, w


class SubDistrict(models.Model):
    """A sub-district of one of the region's districts. Weekly thresholds are worked out from its population."""
    region = models.CharField(max_length=40)
    district = models.CharField(max_length=80, help_text="Org unit district name.")
    name = models.CharField(max_length=80)
    population = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["region", "district", "name"]
        constraints = [models.UniqueConstraint(fields=["region", "district", "name"], name="men_subdistrict_unique")]

    def __str__(self):
        return f"{self.name} ({self.district})"


class ThresholdConfig(models.Model):
    """WHO meningitis belt thresholds, per region. Above `small_pop_cutoff` the weekly attack rate per 100,000 is
    compared with the rates; at or below it (or with no population on file) the week's case count is."""
    region = models.CharField(max_length=40, unique=True)
    alert_rate = models.DecimalField("alert rate per 100,000 per week", max_digits=5, decimal_places=1, default=3)
    epidemic_rate = models.DecimalField("epidemic rate per 100,000 per week", max_digits=5, decimal_places=1, default=10)
    small_pop_cutoff = models.PositiveIntegerField("small population: at most", default=30000)
    small_pop_alert_cases = models.PositiveSmallIntegerField("small population: alert at cases in a week", default=2)
    small_pop_epidemic_cases = models.PositiveSmallIntegerField("small population: epidemic at cases in a week", default=5)
    season_start_week = models.PositiveSmallIntegerField(default=39, validators=[MinValueValidator(1), MaxValueValidator(53)])

    def __str__(self):
        return f"Thresholds for {self.region}"

    @classmethod
    def for_region(cls, region):
        """The region's settings; the WHO defaults (not saved) until someone changes them."""
        return cls.objects.filter(region=region).first() or cls(region=region)


class Case(models.Model):
    # Identity (names are personal data: never in an export marked to share outside GHS)
    last_name = models.CharField(max_length=80, blank=True)
    first_name = models.CharField(max_length=80, blank=True)

    # EPID number CCC-RRR-DDD-YY-NNNNN, unique
    region = models.CharField(max_length=40, db_index=True, help_text="The reporting region (org unit name).")
    country_code = models.CharField(max_length=3, default="GHA")
    region_code = models.CharField(max_length=3)
    district_code = models.CharField(max_length=3)
    year_code = models.CharField(max_length=2)
    sequence_no = models.PositiveIntegerField()
    epid = models.CharField(max_length=24, unique=True)

    # Place
    health_facility = models.CharField(max_length=120, blank=True)
    district = models.CharField("reporting district", max_length=80, db_index=True)
    reporting_subdistrict = models.ForeignKey(SubDistrict, models.SET_NULL, null=True, blank=True, related_name="+")
    residence_district = models.CharField("district of residence", max_length=80, blank=True)
    residence_subdistrict = models.ForeignKey(SubDistrict, models.SET_NULL, null=True, blank=True, related_name="+")
    community = models.CharField("community of residence", max_length=120, blank=True)
    other_region = models.BooleanField(default=False, help_text="Lives in another region: listed apart, not in the region's reports.")

    # Person
    age_months = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(11)])
    age_years = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(120)])
    sex = models.CharField(max_length=1, choices=choice("sex"), blank=True)

    # Time: the epi week is the ISO week of the date seen (or of onset), else the one written in an imported file
    date_seen = models.DateField(null=True, blank=True)
    date_onset = models.DateField(null=True, blank=True)
    epi_year = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    epi_week = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(53)])

    # Clinical
    fever = models.CharField(max_length=1, choices=choice("yesno"), blank=True)
    neck_stiffness = models.CharField(max_length=1, choices=choice("yesno"), blank=True)
    headache = models.CharField(max_length=1, choices=choice("yesno"), blank=True)
    other_symptoms = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=1, choices=choice("outcome"), blank=True)

    # Vaccination
    vaccinated = models.CharField(max_length=1, choices=choice("yesno"), blank=True)
    vaccine_1 = models.CharField(max_length=1, choices=choice("vaccine"), blank=True)
    vaccine_2 = models.CharField(max_length=1, choices=choice("vaccine"), blank=True)
    pcv = models.CharField(max_length=1, choices=choice("pcv"), blank=True)
    other_vaccine = models.CharField(max_length=120, blank=True)

    # Laboratory
    specimen_collected = models.CharField(max_length=1, choices=choice("yesno"), blank=True)
    date_specimen = models.DateField("date specimen collected", null=True, blank=True)
    gram = models.CharField(max_length=1, choices=choice("gram"), blank=True)
    rapid_test = models.CharField("rapid test (TDR)", max_length=1, choices=choice("rapid"), blank=True)
    latex = models.CharField(max_length=2, choices=choice("latex"), blank=True)
    culture = models.CharField(max_length=2, choices=choice("pathogen"), blank=True)
    pcr = models.CharField("PCR", max_length=2, choices=choice("pathogen"), blank=True)
    final_result = models.CharField("final lab result", max_length=2, choices=choice("pathogen"), blank=True)

    # Classification
    final_classification = models.CharField(max_length=1, choices=choice("classification"), blank=True)
    observations = models.TextField(blank=True)

    # System
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-epi_year", "-epi_week", "-id"]
        indexes = [models.Index(fields=["region", "epi_year", "epi_week"])]
        constraints = [
            models.UniqueConstraint(fields=["country_code", "region_code", "district_code", "year_code", "sequence_no"],
                                    name="men_epid_parts_unique"),
            models.CheckConstraint(condition=~models.Q(age_months__isnull=False, age_years__isnull=False),
                                   name="men_one_age"),
        ]

    def __str__(self):
        return self.epid

    @staticmethod
    def make_epid(country, region, district, year, seq):
        """UPPER(CCC-RRR-DDD-YY-NNNNN), the workbook's EPID formula."""
        return f"{country}-{region}-{district}-{year}-{int(seq):05d}".upper()

    def save(self, *args, **kwargs):
        self.epid = self.make_epid(self.country_code, self.region_code, self.district_code, self.year_code, self.sequence_no)
        when = self.date_seen or self.date_onset
        if when:
            self.epi_year, self.epi_week = iso_week(when)
        super().save(*args, **kwargs)

    @property
    def age_in_years(self):
        if self.age_years is not None:
            return self.age_years
        return 0 if self.age_months is not None else None

    def problems(self, today=None):
        """(errors, warnings) as [(field, message)]: errors stop a save, warnings are shown with it."""
        today, errors, warnings = today or date.today(), [], []
        if self.age_months is not None and self.age_years is not None:
            errors.append(("age_months", "Give the age in months (under 1 year) or in years, not both."))
        if self.age_years == 0:
            errors.append(("age_years", "Under 1 year: give the age in months."))
        if self.date_onset and self.date_seen and self.date_onset > self.date_seen:
            errors.append(("date_onset", "Onset is after the date seen at the health facility."))
        for f in ("date_seen", "date_onset", "date_specimen"):
            d = getattr(self, f)
            if d and d > today:
                errors.append((f, "This date is in the future."))
        if self.date_specimen and self.date_onset and self.date_specimen < self.date_onset:
            errors.append(("date_specimen", "The specimen was collected before onset."))
        if self.vaccinated != ch.YES and (self.vaccine_1 or self.vaccine_2 or self.other_vaccine):
            errors.append(("vaccinated", "Vaccines are recorded only when Vaccinated is 1-Yes."))
        lab = ("date_specimen", "gram", "rapid_test", "latex", "culture", "pcr", "final_result")
        if self.specimen_collected != ch.YES and any(getattr(self, f) for f in lab):
            errors.append(("specimen_collected", "Laboratory results are recorded only when Specimen collected is 1-Yes."))
        if self.final_classification == ch.CONFIRMED and (not self.final_result or self.final_result in ch.NOT_A_RESULT):
            warnings.append(("final_classification", "Confirmed, but the final lab result shows no pathogen."))
        if self.final_result in ch.BACTERIA and self.final_classification and self.final_classification != ch.CONFIRMED:
            warnings.append(("final_classification", "The final lab result found a pathogen: should this case be Confirmed?"))
        if self.date_seen is None and self.date_onset is None and self.epi_week is None:
            errors.append(("date_seen", "Give the date seen at the health facility."))
        return errors, warnings


class CaseEdit(models.Model):
    """Who added, changed or deleted a case, when, and what changed: {field: [old, new]}."""
    case = models.ForeignKey(Case, models.SET_NULL, null=True, blank=True, related_name="edits")
    epid = models.CharField(max_length=24)
    region = models.CharField(max_length=40)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=10, choices=[("add", "Added"), ("edit", "Changed"), ("delete", "Deleted"),
                                                      ("import", "Imported")])
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
