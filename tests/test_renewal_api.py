import importlib


def load_app(tmp_data_dir):
    import app

    return importlib.reload(app)


def test_create_draft_replaces_command_generation(tmp_data_dir):
    module = load_app(tmp_data_dir)

    response = module.app.test_client().post(
        "/api/renew",
        json={
            "endpoint_host": "192.168.1.20",
            "endpoint_port": 443,
            "issuer_type": "acme",
            "identifiers": ["device.example.com"],
            "profile": "generic-rsa",
            "environment": "staging",
            "dns_provider": "manual",
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["state"] == "draft"
    assert payload["endpoint_host"] == "192.168.1.20"
    assert "command" not in payload


def test_job_list_and_detail_are_sanitized(tmp_data_dir):
    module = load_app(tmp_data_dir)
    created = module.app.test_client().post(
        "/api/renew",
        json={
            "endpoint_host": "device.local",
            "issuer_type": "external_ca",
            "identifiers": ["device.local"],
            "profile": "extron-rsa",
        },
    ).get_json()

    listing = module.app.test_client().get("/api/renewals").get_json()
    detail = module.app.test_client().get(f"/api/renewals/{created['id']}").get_json()

    assert listing[0]["id"] == created["id"]
    assert detail["id"] == created["id"]
    serialized = repr((listing, detail)).lower()
    assert "private key" not in serialized
    assert "password" not in serialized
    assert "passphrase" not in serialized


class FakeOrchestrator:
    def continue_manual_dns(self, job_id):
        return {"id": job_id, "state": "issued", "certificate_id": "cert-1"}

    def cancel(self, job_id):
        return {"id": job_id, "state": "cancelled"}

    def retry_cleanup(self, job_id):
        return {"id": job_id, "state": "issued", "certificate_id": "cert-1"}


def test_manual_continue_cancel_and_cleanup_routes(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    monkeypatch.setattr(module, "acme_orchestrator", FakeOrchestrator())
    monkeypatch.setattr(
        module.database, "get_job", lambda job_id: {"issuer_type": "acme"}
    )
    client = module.app.test_client()

    assert client.post("/api/renewals/job-1/manual-dns/continue").get_json()["state"] == "issued"
    assert client.post("/api/renewals/job-1/cancel").get_json()["state"] == "cancelled"
    assert client.post("/api/renewals/job-1/retry-cleanup").get_json()["state"] == "issued"


class FakeArtifacts:
    def read_public(self, certificate_id, name):
        if name == "private-key.pem":
            raise AssertionError("private artifact must not be read")
        return b"public certificate"


def test_public_artifact_route_rejects_private_names(tmp_data_dir, monkeypatch):
    module = load_app(tmp_data_dir)
    monkeypatch.setattr(module, "artifact_store", FakeArtifacts())
    client = module.app.test_client()

    assert client.get("/api/certificates/cert-1/public/certificate.pem").status_code == 200
    assert client.get("/api/certificates/cert-1/public/private-key.pem").status_code == 404
