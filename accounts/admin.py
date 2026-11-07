"""Django's admin site (/django-admin/, support only): every account with its profile, as a back-up to the
app's own Accounts page."""
from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .models import LoginLock, Profile, reserved_problem


class ReservedNames:
    """Refuse the support account's username here too, with a message rather than an error page."""
    def clean(self):
        data = super().clean()
        problem = reserved_problem(data.get("username"), self.instance.pk, data.get("is_superuser", self.instance.is_superuser))
        if problem:
            raise forms.ValidationError({"username": problem})
        return data


class AddForm(ReservedNames, UserCreationForm):
    pass


class ChangeForm(ReservedNames, UserChangeForm):
    pass


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


class AccountAdmin(UserAdmin):
    add_form, form = AddForm, ChangeForm
    inlines = [ProfileInline]
    list_display = ("username", "full_name", "region", "is_superuser", "last_login")

    @admin.display(description="Full name")
    def full_name(self, user):
        return getattr(getattr(user, "profile", None), "full_name", "")

    @admin.display(description="Region")
    def region(self, user):
        return getattr(getattr(user, "profile", None), "region", "")


admin.site.unregister(User)
admin.site.register(User, AccountAdmin)
admin.site.register(LoginLock)
admin.site.site_header = "Surveillance support"
