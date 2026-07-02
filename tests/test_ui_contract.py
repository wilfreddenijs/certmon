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

    assert 'id="push-target-select"' in html
    assert 'id="push-certificate-select"' not in html
    assert 'id="push-device-select"' not in html
    assert 'id="cert-pem"' not in html
    assert 'id="key-pem"' not in html
    assert "certificate_id" in html
    assert "cert_pem" not in push_function
    assert "key_pem" not in push_function
    assert "Each certificate belongs to one device" in html
    assert "certificate/device pair" in html
    assert "For unsupported devices" in html
    assert "separate private-key.pem download" in html


def test_devices_workflow_explains_device_certificate_fields():
    html = page()

    assert "Choose a device and select <b>Create certificate</b>" in html
    assert r"\b(dmp|ipcp|iplp|tlp|ucs|dtx|sme|smp|in\d{3,4}|dvs|dsc)\b" in html
    assert "Use the IP address users enter" in html
    assert "Add this if users connect by DNS name" in html
    assert "Choose Extron/RSA for older devices" in html
    assert "Create certificate" in html
    assert "Upload ready" in html
    assert "Certificate ready" in html
    assert "Use existing" in html
    assert 'value="extron-rsa"' in html


def test_first_tab_is_devices_and_local_ca_is_root_management_only():
    html = page()
    ca_panel = html.split('id="tab-ca"', 1)[1].split("<!-- Upload Tab -->", 1)[0]

    assert "switchTab('certs')\">Devices" in html
    assert "Scanned devices" in html
    assert "Issue Device Certificate" not in ca_panel
    assert "Issued Device Certificates" not in ca_panel
    assert "Generate Local CA" in html
    assert "Download CA cert" in html


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
    assert "The device CertMon connects to" in html
    assert "Names that must appear on the certificate" in html
    assert "Use for public DNS names" in html
    assert "Use for local IPs or internal names" in html
    assert "Use when another CA signs the certificate" in html
    assert "Choose compatibility first" in html
    assert "CertMon shows a TXT record" in html
    assert "Safe test mode" in html
    assert "Creates a real trusted certificate" in html
    assert "Used by the ACME provider" in html
    assert 'name="external-ca-workflow"' in html
    assert 'value="csr"' in html
    assert 'value="existing"' in html
    assert "Generate CSR with CertMon key" in html
    assert "Import existing certificate and private key" in html
    assert "CertMon keeps the new job in draft and opens the import form immediately" in html
    assert "Create and import certificate" in html
    assert "Certificate file" in html
    assert "certificate.pem" in html
    assert "Do not use <code>full-chain.pem</code> here" in html
    assert "Intermediate/chain file" in html
    assert "chain.pem" in html
    assert "Private key file" in html
    assert "private-key.pem" in html
    assert "Leave empty for normal imports" in html
    assert "Use this when a certificate was signed outside CertMon" in html
    assert 'id="external-import-help-complete"' in html
    assert 'id="external-import-help-existing"' in html
    assert "Choose this when CertMon generated the CSR and private key" in html
    assert "Choose this when you already have both the certificate and its matching private key" in html
    assert "Leave empty unless the private key file itself is encrypted" in html
    assert "external-import-help-complete').hidden = existing" in html
    assert "external-import-help-existing').hidden = !existing" in html
    assert "externalImportErrorMessage" in html
    assert "already been started as a CSR flow" in html
    assert "create a new External CA renewal and import before starting it" in html
    assert "Signed certificate for the generated CSR" in html
    assert "openExternalImport(job.id, 'existing')" in html
    assert "draft.external_ca_workflow === 'existing'" in html
    assert "r.metadata?.external_ca_workflow === 'existing'" in html
    assert "Import certificate" in html
    assert "Use Import certificate or delete the entry" in html
    assert "Use the External CA import form" not in html


def test_dark_ui_help_text_uses_readable_contrast():
    html = page()

    assert "--muted: #8fa6b2" in html
    assert ".help-text" in html
    assert ".choice-help" in html
    assert "select option" in html


def test_deployment_result_offers_private_key_download_without_storing_key_material():
    html = page()

    assert 'id="push-private-artifacts"' in html
    assert 'id="push-private-artifact-links"' in html
    assert "/api/certificates/${certificate_id}/private/private-key.pem" in html
    assert "privateKeyPem" not in html


def test_local_ca_extron_pem_download_uses_private_combined_artifact():
    html = page()

    assert "PEM (Extron)" in html
    assert "Extron profile certificates show an extra" in html
    assert "Generic certificates should normally use the separate cert/key files" in html
    assert "Extron certificates are legacy/Toolbelt-friendly RSA certs" in html
    assert "c.profile === 'extron-rsa'" in html
    assert "/api/certificates/${c.certificate_id}/private/combined.pem" in html
    assert "/api/ca/download/${c.certificate_id}" in html
    assert "Extron PEM contains certificate and private key" in html


def test_upload_tab_has_toolbelt_batch_upload_flow():
    html = page()

    assert "Prepared device upload" in html
    assert "one central prepared-device list" in html
    assert "Add device" in html
    assert "Manual upload fallback" in html
    assert "Download Certificates for Manual Upload" in html
    assert "Target Devices" not in html
    assert "Toolbelt batch upload" in html
    assert "Test Toolbelt upload first" in html
    assert "Test Toolbelt upload" in html
    assert "Retry dry-run" not in html
    assert 'id="toolbelt-device-list"' in html
    assert 'id="toolbelt-upload-btn"' in html
    assert 'id="toolbelt-stop-btn"' in html
    assert "/api/toolbelt/devices" in html
    assert "/api/toolbelt/default-credentials" in html
    assert "/api/toolbelt/reset-upload-tab" in html
    assert "/api/toolbelt/dry-run" in html
    assert "/api/toolbelt/upload" in html
    assert "Shared device password" in html
    assert "tries shared device password, then admin/extron" in html
    assert "Stop after current device" in html
    assert "tries admin/extron, then admin/serial from Toolbelt" in html
    assert "run.error" in html
    assert "errorText" in html
    assert "d.event !== 'device_pending'" in html


def test_manual_upload_lists_all_certificate_profiles_as_download_targets():
    html = page()
    render_select = html.split("function renderCertificateSelect()", 1)[1].split(
        "function applyPendingDeployment()", 1
    )[0]

    assert "availableCertificates || []" in render_select
    assert "filter(c => c.profile !== 'extron-rsa')" not in render_select
    assert "Download Certificates for Manual Upload" in html
    assert "certificate/device pair" in html


def test_upload_tab_does_not_auto_start_toolbelt_dry_run():
    html = page()
    load_toolbelt = html.split("async function loadToolbeltDevices(forceDryRun)", 1)[1].split(
        "function toolbeltStatusLabel", 1
    )[0]

    assert "if (forceDryRun && toolbeltDevices.length)" in load_toolbelt
    assert "!toolbeltAutoDryRunStarted" not in load_toolbelt


def test_upload_rows_can_remove_prepared_local_ca_certificate():
    html = page()

    assert "removePreparedToolbeltDevice" in html
    assert "/api/ca/issued/${encodeURIComponent(certificateId)}" in html
    assert "delete the associated Local CA device certificate" in html


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
    assert "r.state === 'issued'" in html
    assert "deployment_pending" in html
    assert "Deployment did not finish yet or needs attention" in html
    assert "Keep for later" not in html


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
