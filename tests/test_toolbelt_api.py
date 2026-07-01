import importlib


def load_app(tmp_data_dir):
    import app

    return importlib.reload(app)


class FakeToolbeltService:
    def __init__(self):
        self.selection = None
        self.credentials = None
        self.started = []
        self.run = {
            "id": "run-1",
            "mode": "dry-run",
            "status": "complete",
            "devices": {},
            "events": [],
        }

    def list_devices(self):
        return [
            {
                "selector": "192.168.0.10",
                "certificate_id": "cert-1",
                "label": "UCS Boardroom",
                "profile": "extron-rsa",
                "extron_ready": True,
                "selected": True,
                "dry_run": {"ok": True, "message": "dry-run (not applied)"},
                "upload": None,
                "credentials_saved": False,
            }
        ]

    def save_selection(self, selectors):
        self.selection = selectors

    def reset_upload_tab_state(self):
        self.selection = None
        return self.list_devices()

    def save_credentials(self, selector, *, username, password):
        self.credentials = (selector, username, password)

    def start(self, *, mode, selectors=None):
        self.started.append((mode, selectors))
        return {"id": "run-1", "mode": mode, "status": "running"}

    def get_run(self, run_id):
        return self.run if run_id == "run-1" else None

    def stop(self, run_id):
        if run_id != "run-1":
            return None
        return {"id": "run-1", "requested_stop": True}


def install_fake_toolbelt(module, service):
    module.toolbelt_service = service
    module.artifact_store = object()
    module.vault = object()


def test_toolbelt_devices_returns_safe_device_list(tmp_data_dir):
    module = load_app(tmp_data_dir)
    service = FakeToolbeltService()
    install_fake_toolbelt(module, service)

    response = module.app.test_client().get("/api/toolbelt/devices")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["devices"][0]["selector"] == "192.168.0.10"
    assert "password" not in str(payload).lower()
    assert "private_key" not in str(payload).lower()


def test_toolbelt_reset_upload_tab_route_returns_clean_device_list(tmp_data_dir):
    module = load_app(tmp_data_dir)
    service = FakeToolbeltService()
    install_fake_toolbelt(module, service)

    response = module.app.test_client().post("/api/toolbelt/reset-upload-tab")

    assert response.status_code == 200
    assert response.get_json()["devices"][0]["selector"] == "192.168.0.10"
    assert service.selection is None


def test_toolbelt_dry_run_rejects_private_material_and_starts_run(tmp_data_dir):
    module = load_app(tmp_data_dir)
    service = FakeToolbeltService()
    install_fake_toolbelt(module, service)
    client = module.app.test_client()

    rejected = client.post("/api/toolbelt/dry-run", json={"combined_pem": "secret"})
    assert rejected.status_code == 400

    response = client.post(
        "/api/toolbelt/dry-run", json={"selectors": ["192.168.0.10"]}
    )

    assert response.status_code == 200
    assert response.get_json()["run"]["id"] == "run-1"
    assert service.started == [("dry-run", ["192.168.0.10"])]


def test_toolbelt_upload_stop_selection_and_credentials_routes(tmp_data_dir):
    module = load_app(tmp_data_dir)
    service = FakeToolbeltService()
    install_fake_toolbelt(module, service)
    client = module.app.test_client()

    assert client.patch(
        "/api/toolbelt/selection", json={"selectors": ["192.168.0.10"]}
    ).status_code == 200
    assert service.selection == ["192.168.0.10"]

    assert client.patch(
        "/api/toolbelt/devices/192.168.0.10/credentials",
        json={"username": "admin", "password": "extron"},
    ).status_code == 200
    assert service.credentials == ("192.168.0.10", "admin", "extron")

    response = client.post(
        "/api/toolbelt/upload", json={"selectors": ["192.168.0.10"]}
    )
    assert response.status_code == 200
    assert service.started[-1] == ("upload", ["192.168.0.10"])

    assert client.post("/api/toolbelt/runs/run-1/stop").get_json()["run"][
        "requested_stop"
    ] is True
