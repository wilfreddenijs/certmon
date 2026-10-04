// CertMon UAT 6 helper: mutating request without the CSRF header.
//
// Usage:
// 1. Start CertMon in server mode.
// 2. Sign in as an admin.
// 3. Open browser DevTools > Console.
// 4. Paste this snippet and press Enter.
//
// Expected result:
// 1. The status check should show server_mode: true and authenticated: true.
// 2. The POST response status should be 403 because this request intentionally
//    omits the X-CertMon-CSRF header required for state-changing server-mode
//    requests.
//
// Note:
// The CertMon UI wraps window.fetch and automatically injects the CSRF header
// for normal same-origin UI requests. This helper therefore uses
// XMLHttpRequest for the mutating request, so the CSRF header is truly absent.

(async () => {
  const statusResponse = await fetch('/api/auth/status');
  const authStatus = await statusResponse.json();
  console.log('CertMon auth status:', authStatus);

  if (!authStatus.server_mode) {
    console.error('UAT setup issue: this browser tab is not connected to CertMon server mode.');
    return;
  }
  if (!authStatus.authenticated) {
    console.error('UAT setup issue: sign in first, then run this snippet again.');
    return;
  }

  const result = await new Promise(resolve => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/renew', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = () => resolve({
      status: xhr.status,
      body: xhr.responseText
    });
    xhr.onerror = () => resolve({
      status: xhr.status || 0,
      body: 'network error'
    });
    xhr.send(JSON.stringify({
      endpoint_host: '127.0.0.1',
      endpoint_port: 443,
      issuer_type: 'local-ca',
      identifiers: ['uat-csrf-test.local'],
      profile: 'generic-rsa'
    }));
  });

  console.log('Mutating request without CSRF header:', result);
})();
