import importlib


class FakeArtifacts:
    def __init__(self):
        self.requested = []
        self.deleted = []

    def has_certificate(self, certificate_id):
        return certificate_id in {"local-ca", "cert-1"}

    def read_public(self, certificate_id, name):
        self.requested.append((certificate_id, name))
        return b"-----BEGIN CERTIFICATE-----\npublic\n-----END CERTIFICATE-----\n"

    def delete_certificate_set(self, certificate_id):
        self.deleted.append(certificate_id)


class FakeCertificateDatabase:
    def __init__(self):
        self.certificates = {
            "cert-1": {
                "id": "cert-1",
                "kind": "leaf",
                "issuer_type": "local_ca",
                "identifiers": ["192.168.0.10", "device.local"],
                "not_after": "2030-01-01T00:00:00+00:00",
            },
            "external-1": {
                "id": "external-1",
                "kind": "leaf",
                "issuer_type": "external_ca",
                "identifiers": ["external.local"],
                "not_after": "2030-01-01T00:00:00+00:00",
            },
        }
        self.deleted = []

    def list_certificates(self):
        return list(self.certificates.values())

    def get_certificate(self, certificate_id):
        return self.certificates.get(certificate_id)

    def delete_certificate(self, certificate_id):
        self.deleted.append(certificate_id)
        self.certificates.pop(certificate_id, None)


class FakeLocalCA:
    def issue(self, **kwargs):
        assert kwargs["profile_name"] == "extron-rsa"
        return {"certificate_id": "cert-1", "not_after": "2030-01-01T00:00:00+00:00"}


class FakeExternalCA:
    def complete_csr_job(self, job_id, leaf, chain, trust_anchor_id):
        assert job_id == "job-1"
        assert leaf == b"leaf"
        assert chain == b"chain"
        assert trust_anchor_id == "root-1"
        return "cert-2"


def load_app(tmp_data_dir):
    import app

    return importlib.reload(app)


def test_local_ca_issue_response_contains_no_private_material(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    monkeypatch.setattr(module, "artifact_store", FakeArtifacts())
    monkeypatch.setattr(module, "local_ca_service", FakeLocalCA())

    response = module.app.test_client().post(
        "/api/ca/issue",
        json={"hostname": "device.local", "profile": "extron-rsa"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["certificate_id"] == "cert-1"
    assert not {"key_pem", "passphrase", "key_path", "pem_path"} & payload.keys()


def test_public_download_never_reads_private_artifact(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    artifacts = FakeArtifacts()
    monkeypatch.setattr(module, "artifact_store", artifacts)

    response = module.app.test_client().get("/api/ca/download/cert-1")

    assert response.status_code == 200
    assert artifacts.requested == [("cert-1", "certificate.pem")]


def test_devices_txt_exports_certificate_ids_not_private_paths(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir)
    monkeypatch.setattr(module, "database", FakeCertificateDatabase())

    response = module.app.test_client().get("/api/ca/devices-txt")

    assert response.status_code == 200
    assert response.text == "192.168.0.10,cert-1\n"
    assert ".pem" not in response.text


def test_delete_issued_certificate_uses_certificate_id(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir)
    artifacts = FakeArtifacts()
    database = FakeCertificateDatabase()
    monkeypatch.setattr(module, "artifact_store", artifacts)
    monkeypatch.setattr(module, "database", database)

    response = module.app.test_client().delete("/api/ca/issued/cert-1")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "removed": ["cert-1"]}
    assert artifacts.deleted == ["cert-1"]
    assert database.deleted == ["cert-1"]


def test_external_completion_response_contains_only_certificate_id(
    tmp_data_dir, monkeypatch
):
    module = load_app(tmp_data_dir)
    monkeypatch.setattr(module, "external_ca_service", FakeExternalCA())

    response = module.app.test_client().post(
        "/api/renewals/job-1/external/complete",
        json={
            "certificate_pem": "leaf",
            "chain_pem": "chain",
            "trust_anchor_id": "root-1",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "certificate_id": "cert-2"}
