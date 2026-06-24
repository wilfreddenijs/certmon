from pathlib import Path


HTML = Path(__file__).parents[1] / "templates" / "index.html"


def page():
    return HTML.read_text(encoding="utf-8")


def test_wizard_has_endpoint_identifiers_issuers_profiles_and_dns_choices():
    html = page()

    for required in (
        'id="renewal-endpoint-host"',
        'id="renewal-endpoint-port"',
        'id="renewal-identifiers"',
        'value="acme"',
        'value="local_ca"',
        'value="external_ca"',
        'value="generic-ecdsa"',
        'value="generic-rsa"',
        'value="extron-rsa"',
        'value="manual"',
        'value="cloudflare"',
        'value="staging"',
        'value="production"',
    ):
        assert required in html


def test_wizard_has_external_ca_and_resumable_state_actions():
    html = page()

    assert 'id="external-ca-controls"' in html
    assert "Download CSR" in html
    assert "Import signed certificate" in html
    assert "Verify and continue" in html
    assert "Retry cleanup" in html
    assert "Deploy now" in html
    assert "Keep for later" in html
    assert "Cancel renewal" in html


def test_legacy_command_selectors_are_removed():
    html = page().lower()

    assert 'value="certbot"' not in html
    assert 'value="acme.sh"' not in html
    assert "certbot certonly" not in html
    assert "acme.sh --issue" not in html


def test_private_material_is_not_kept_in_wizard_dom_state():
    wizard = page().split('id="renewal-modal"', 1)[1].split(
        "<!-- External CA certificate import -->", 1
    )[0]

    assert "private-key.pem" not in wizard
    assert "key_pem" not in wizard
    assert "stored token" not in wizard.lower()


def test_upload_tab_uses_certificate_ids_not_browser_pem_fields():
    html = page()
    push_function = html.split("async function pushCert()", 1)[1]

    assert 'id="push-certificate-select"' in html
    assert 'id="cert-pem"' not in html
    assert 'id="key-pem"' not in html
    assert "certificate_id" in html
    assert "cert_pem" not in push_function
    assert "key_pem" not in push_function


def test_external_ca_import_form_submits_generated_and_existing_certificates():
    html = page()

    for required in (
        'id="external-import-modal"',
        'id="external-certificate-file"',
        'id="external-chain-file"',
        'id="external-private-key-file"',
        'id="external-passphrase"',
        'id="external-trust-anchor"',
        "openExternalImport(id)",
        "external/${action}",
    ):
        assert required in html
    assert "Use the External CA import form" not in html


def test_deployment_result_offers_private_key_download_without_storing_key_material():
    html = page()

    assert 'id="push-private-artifacts"' in html
    assert 'id="push-private-artifact-links"' in html
    assert "/api/certificates/${certificate_id}/private/private-key.pem" in html
    assert "privateKeyPem" not in html


def test_renewal_resume_actions_surface_errors_inline():
    html = page()

    assert "renewal-action-result-" in html
    assert "response.ok" in html
    assert "Could not verify renewal" in html
    assert "friendlyResponseError" in html


def test_manual_dns_verify_mismatch_surfaces_inline_warning():
    html = page()

    assert "renewalActionResults" in html
    assert "renewalActionResultMarkup" in html
    assert "setRenewalActionResult" in html
    assert "result.visible === false" in html
    assert "dnsTxtMismatchMessage" in html
    assert "DNS TXT record is not visible yet or does not match" in html
    assert "Expected TXT:" in html


def test_cancelled_and_failed_renewals_can_be_deleted_from_list():
    html = page()

    assert "Delete entry" in html
    assert "deleteRenewal(" in html
    assert "method: 'DELETE'" in html


def test_awaiting_dns_renewals_show_dns_challenge_records():
    html = page()

    assert "DNS TXT challenge" in html
    assert "renewalDnsRecords" in html
    assert "record.fqdn" in html
    assert "record.value" in html


def test_template_contains_no_mojibake_sequences():
    html = page()

    for broken in ("â", "ðŸ", "Ã", "Â", "�"):
        assert broken not in html
