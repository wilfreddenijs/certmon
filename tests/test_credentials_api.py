import importlib


def load_app(tmp_data_dir):
    import app

    return importlib.reload(app)


def test_cloudflare_credentials_create_list_delete_without_secret_leak(tmp_data_dir):
    module = load_app(tmp_data_dir)
    client = module.app.test_client()

    created = client.post(
        "/api/credentials/cloudflare",
        json={"token": "top-secret-token", "zones": ["example.com"]},
    )
    listing = client.get("/api/credentials/cloudflare")

    assert created.status_code == 201
    assert created.get_json() == {"configured": True, "zones": ["example.com"]}
    assert listing.get_json() == {"configured": True, "zones": ["example.com"]}
    assert "top-secret-token" not in repr((created.get_json(), listing.get_json()))
    assert client.delete("/api/credentials/cloudflare").status_code == 204
    assert client.get("/api/credentials/cloudflare").get_json() == {
        "configured": False,
        "zones": [],
    }


def test_cloudflare_credentials_require_token_and_zone(tmp_data_dir):
    module = load_app(tmp_data_dir)

    response = module.app.test_client().post(
        "/api/credentials/cloudflare", json={"token": "", "zones": []}
    )

    assert response.status_code == 400
    assert "token" not in response.get_json().get("details", "").lower()
