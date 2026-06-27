from certmon.profiles import PROFILES, recommend_profile


def test_extron_profile_is_rsa_2048_with_expected_usages():
    profile = PROFILES["extron-rsa"]

    assert profile.key_type == "rsa"
    assert profile.key_size == 2048
    assert profile.key_usage == frozenset(
        {
            "digital_signature",
            "content_commitment",
            "key_encipherment",
            "data_encipherment",
        }
    )
    assert profile.extended_key_usage == frozenset({"server_auth"})


def test_modern_profile_is_p256_server_auth():
    profile = PROFILES["generic-ecdsa"]

    assert profile.key_type == "ecdsa"
    assert profile.curve == "secp256r1"
    assert profile.extended_key_usage == frozenset({"server_auth"})


def test_extron_devices_receive_extron_profile_recommendation():
    assert recommend_profile("extron") == "extron-rsa"
    assert recommend_profile("generic") == "generic-ecdsa"
