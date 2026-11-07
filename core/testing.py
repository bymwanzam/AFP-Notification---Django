"""Test helpers: every test works on a temporary copy of data/, never the real register or IDSR files."""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from accounts import services

PLAIN_STATIC = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class DataTestCase(TestCase):
    password = "a-long-password"

    @classmethod
    def setUpClass(cls):
        cls._tmp = Path(tempfile.mkdtemp(prefix="surveillance-test-"))
        data, private = cls._tmp / "data", cls._tmp / "private"
        shutil.copytree(settings.DATA_DIR, data)
        cls._override = override_settings(
            DATA_DIR=data, AFP_REGISTER=data / "AFP nofitication.xlsx", IDSR_STORE=data / "IDSR weekly data.xlsx",
            IDSR_IMAGES=data / "idsr-images", PRIVATE_MEDIA=private, STORAGES=PLAIN_STATIC)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def account(self, username="ue-officer", region="Upper East", **kw):
        return services.create_account(username, self.password, "Test Officer", region, **kw)

    def support(self, username="ghs-support"):
        from django.contrib.auth.models import User
        user = User.objects.create_superuser(username, password=self.password)
        services.profile_of(user)
        return user

    def sign_in(self, user):
        self.client.force_login(user)
        return user
