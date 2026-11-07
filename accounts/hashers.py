"""Passwords of accounts brought over from the local app: salted PBKDF2-SHA256, 240,000 rounds.

They are stored as "afp_pbkdf2$<rounds>$<salt hex>$<hash hex>". Django checks them with this hasher and, because it
is not the preferred one, saves them again with its own hashing the first time the account signs in.
"""
import hashlib
import hmac

from django.contrib.auth.hashers import BasePasswordHasher


class LegacyAFPHasher(BasePasswordHasher):
    algorithm = "afp_pbkdf2"

    def encode(self, password, salt, iterations=240_000):
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
        return f"{self.algorithm}${iterations}${salt}${digest}"

    def decode(self, encoded):
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        return {"algorithm": algorithm, "iterations": int(iterations), "salt": salt, "hash": digest}

    def verify(self, password, encoded):
        d = self.decode(encoded)
        return hmac.compare_digest(self.encode(password, d["salt"], d["iterations"]), encoded)

    def safe_summary(self, encoded):
        d = self.decode(encoded)
        return {"algorithm": d["algorithm"], "iterations": d["iterations"], "salt": d["salt"][:6] + "…", "hash": d["hash"][:6] + "…"}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass

    def salt(self):
        import secrets
        return secrets.token_hex(16)
