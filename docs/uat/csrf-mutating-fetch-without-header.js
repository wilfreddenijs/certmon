// CertMon UAT 6 helper: mutating request without the CSRF header.
//
// Usage:
// 1. Start CertMon in server mode.
// 2. Sign in as an admin.
// 3. Open browser DevTools > Console.
// 4. Paste this snippet and press Enter.
//
// Expected result:
// The response status should be 403 because this POST intentionally omits
// the X-CertMon-CSRF header required for state-changing server-mode requests.

fetch('/api/renew', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    endpoint_host: '127.0.0.1',
    endpoint_port: 443,
    issuer_type: 'local-ca',
    identifiers: ['uat-csrf-test.local'],
    profile: 'generic-rsa'
  })
}).then(async response => ({
  status: response.status,
  body: await response.text()
})).then(console.log);
