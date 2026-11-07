import json

from django.contrib.auth.models import User
from django.test import Client

from core.testing import DataTestCase

from . import services


def post(client, path, body, **kw):
    return client.post(path, json.dumps(body), content_type="application/json", **kw)


class SignInTests(DataTestCase):
    def test_first_run_offers_setup_and_signs_the_new_account_in(self):
        page = self.client.get("/login")
        self.assertEqual(page.context["data"]["mode"], "setup")
        r = post(self.client, "/api/setup", {"username": "First.User", "password": self.password, "confirm": self.password,
                                             "name": "First User", "region": "North East", "next": "/idsr"})
        self.assertEqual(r.json(), {"go": "/idsr"})
        user = User.objects.get(username="first.user")
        self.assertEqual(services.profile_of(user).region, "North East")
        self.assertEqual(self.client.get("/start").status_code, 200)

    def test_setup_is_refused_once_an_account_exists(self):
        self.account()
        self.assertEqual(self.client.get("/login").context["data"]["mode"], "login")
        r = post(self.client, "/api/setup", {"username": "other", "password": self.password, "confirm": self.password, "region": "Volta"})
        self.assertEqual(r.status_code, 409)

    def test_wrong_passwords_lock_the_username(self):
        self.account()
        for _ in range(services.MAX_FAILS):
            r = post(self.client, "/api/login", {"username": "ue-officer", "password": "wrong-password"})
            self.assertEqual(r.status_code, 401)
        r = post(self.client, "/api/login", {"username": "ue-officer", "password": self.password})
        self.assertIn("Too many wrong passwords", r.json()["error"])

    def test_login_never_sends_you_to_another_site(self):
        self.account()
        r = post(self.client, "/api/login", {"username": "ue-officer", "password": self.password, "next": "//evil.example"})
        self.assertEqual(r.json(), {"go": "/start"})

    def test_pages_need_a_sign_in_and_apis_answer_json(self):
        r = self.client.get("/idsr?week=4")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/login?next=/idsr%3Fweek%3D4")
        r = self.client.get("/api/data")
        self.assertEqual((r.status_code, r.json()["error"]), (401, "Your session has ended. Sign in again."))

    def test_writes_need_the_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        self.account()
        client.get("/login")
        r = post(client, "/api/login", {"username": "ue-officer", "password": self.password})
        self.assertEqual(r.status_code, 403)
        r = post(client, "/api/login", {"username": "ue-officer", "password": self.password},
                 HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(r.status_code, 200)

    def test_password_set_by_support_must_be_changed_first(self):
        user = self.account(must_change=True)
        r = post(self.client, "/api/login", {"username": "ue-officer", "password": self.password, "next": "/idsr"})
        self.assertEqual(r.json(), {"go": "/login?next=/idsr"})
        self.assertEqual(self.client.get("/login?next=/idsr").context["data"]["mode"], "change")
        self.assertEqual(self.client.get("/start").status_code, 302)
        self.assertEqual(self.client.get("/api/data").status_code, 403)
        r = post(self.client, "/api/password", {"current": self.password, "password": "another-password",
                                                "confirm": "another-password", "next": "/idsr"})
        self.assertEqual(r.json(), {"go": "/idsr"})
        self.assertFalse(services.must_change(user))
        self.assertEqual(self.client.get("/start").status_code, 200)  # still signed in after the change

    def test_logout(self):
        self.sign_in(self.account())
        self.assertEqual(self.client.get("/logout")["Location"], "/login")
        self.assertEqual(self.client.get("/start").status_code, 302)


class ProfileAndAccountsTests(DataTestCase):
    def test_profile_and_picture(self):
        self.sign_in(self.account())
        self.assertEqual(self.client.get("/profile").status_code, 200)
        r = post(self.client, "/api/profile", {"name": "Ama Mensah", "cadre": "Epidemiologist"})
        self.assertEqual((r.json()["name"], r.json()["cadre"]), ("Ama Mensah", "Epidemiologist"))
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
        r = self.client.post("/api/profile/photo", png, content_type="application/octet-stream")
        self.assertTrue(r.json()["photo"])
        r = self.client.get("/api/profile/photo")
        self.assertEqual((r["Content-Type"], r.content), ("image/png", png))
        r = self.client.post("/api/profile/photo", b"not a picture", content_type="application/octet-stream")
        self.assertEqual(r.status_code, 400)

    def test_only_support_manages_accounts(self):
        self.sign_in(self.account())
        self.assertEqual(self.client.get("/admin")["Location"], "/start")
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)

    def test_support_adds_an_account_and_moves_it(self):
        self.sign_in(self.support())
        self.assertEqual(self.client.get("/admin").status_code, 200)
        r = post(self.client, "/api/admin/users", {"action": "add", "username": "nr-officer", "name": "NR", "region": "Northern"})
        self.assertTrue(r.json()["password"])
        self.assertEqual([u["username"] for u in r.json()["users"]], ["nr-officer"])
        self.assertTrue(services.must_change(User.objects.get(username="nr-officer")))
        r = post(self.client, "/api/admin/users", {"action": "region", "username": "nr-officer", "region": "Ghana"})
        self.assertEqual(r.json()["users"][0]["region"], "Ghana")
        self.assertTrue(services.is_national(User.objects.get(username="nr-officer")))


class ReservedUsernameTests(DataTestCase):
    def test_nobody_can_take_the_support_username(self):
        for name in ("admin", "Admin", " ADMIN "):
            self.assertIn("reserved", services.check_new(name, self.password))
        with self.assertRaises(ValueError):
            self.account("admin")
        with self.assertRaises(ValueError):
            User.objects.create_user("admin", password=self.password)  # the shell or an import

    def test_first_run_setup_refuses_it(self):
        r = post(self.client, "/api/setup", {"username": "Admin", "password": self.password, "confirm": self.password,
                                             "name": "X", "region": "Volta"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(username__iexact="admin").exists())

    def test_support_cannot_add_or_rename_to_it(self):
        self.sign_in(self.support("admin"))
        r = post(self.client, "/api/admin/users", {"action": "add", "username": "admin", "region": "Volta"})
        self.assertEqual(r.status_code, 400)
        officer = self.account()
        officer.username = "admin"
        with self.assertRaises(ValueError):
            officer.save()

    def test_only_one_support_account_may_be_called_admin(self):
        self.support("admin")
        with self.assertRaises(ValueError):
            User.objects.create_superuser("Admin", password=self.password)

    def test_django_admin_form_refuses_it(self):
        from .admin import AddForm
        form = AddForm(data={"username": "admin", "password1": self.password, "password2": self.password})
        self.assertFalse(form.is_valid())
        self.assertIn("reserved", str(form.errors["username"]))
