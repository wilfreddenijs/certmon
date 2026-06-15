from dataclasses import dataclass


@dataclass(frozen=True)
class CertificateProfile:
    name: str
    key_type: str
    key_size: int | None
    curve: str | None
    key_usage: frozenset[str]
    extended_key_usage: frozenset[str]


PROFILES = {
    "generic-ecdsa": CertificateProfile(
        name="Generic modern",
        key_type="ecdsa",
        key_size=None,
        curve="secp256r1",
        key_usage=frozenset({"digital_signature"}),
        extended_key_usage=frozenset({"server_auth"}),
    ),
    "generic-rsa": CertificateProfile(
        name="Generic RSA",
        key_type="rsa",
        key_size=2048,
        curve=None,
        key_usage=frozenset({"digital_signature", "key_encipherment"}),
        extended_key_usage=frozenset({"server_auth"}),
    ),
    "extron-rsa": CertificateProfile(
        name="Extron compatible",
        key_type="rsa",
        key_size=2048,
        curve=None,
        key_usage=frozenset(
            {
                "digital_signature",
                "content_commitment",
                "key_encipherment",
                "data_encipherment",
            }
        ),
        extended_key_usage=frozenset({"server_auth"}),
    ),
}


def recommend_profile(device_type):
    if (device_type or "").lower() == "extron":
        return "extron-rsa"
    return "generic-ecdsa"
