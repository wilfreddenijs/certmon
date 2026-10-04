# Phase 02: Shared Server Mode - RBAC UI Gap Closure - Pattern Map

**Mapped:** 2026-10-02  
**Files analyzed:** 3 planned files  
**Analogs found:** 2 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app.py` | route / controller | request-response | `app.py` auth status and authorization middleware | exact |
| `templates/index.html` | component / client controller | request-response, event-driven | `templates/index.html` auth initialization, tab switching, and renderers | exact |
| `tests/test_rbac_browser.py` | test | request-response, event-driven | `tests/test_rbac.py` and `tests/test_auth_api.py` | role-match; no browser harness exists |

## Pattern Assignments

### `app.py` (route, request-response)

**Analog:** existing `auth_status()` and request authorization boundary in `app.py`.

**Imports / permission source** (lines 56-61): the module already imports `Permission`, `authorize`, `permissions_for_roles`, and request permission-context helpers together. Extend the existing status response with server-derived effective permission values; do not create a browser role map or alter `ROLE_PERMISSIONS`.

**Authenticated request pattern** (lines 283-312):
```python
@app.before_request
def require_server_authentication():
    g.current_user = None
    g.permission_token = set_current_permissions(None)
    if not server_mode_enabled():
        return None
    token = request.cookies.get(SESSION_COOKIE)
    g.current_user = auth_service.user_for_token(token)
    if request.path in AUTH_EXEMPT_PATHS:
        return None
    if g.current_user is None:
        return jsonify({"error": "Authentication required"}), 401
    set_current_permissions(permissions_for_roles(g.current_user.get("roles", [])))
```

**Status-response pattern** (lines 500-514): preserve the single status JSON contract used by `initAuth()`. Add the effective-permission list only when `current_user()` exists, using `permissions_for_roles(current_user().get("roles", []))` and serialized permission values.
```python
@app.route("/api/auth/status")
def auth_status():
    token = request.cookies.get(SESSION_COOKIE)
    return jsonify(
        {
            "server_mode": server_mode_enabled(),
            "authenticated": current_user() is not None,
            "first_admin_required": auth_service.first_admin_required(),
            "user": public_user(current_user()),
            "csrf_header": CSRF_HEADER,
            "csrf_token": csrf_token_for_session(token, csrf_secret())
            if current_user() is not None
            else None,
        }
    )
```

**Authorization / error pattern** (lines 310-312): leave API enforcement intact; hiding a control is not an authorization substitute.
```python
@app.errorhandler(AuthorizationError)
def handle_authorization_error(exc):
    return jsonify({"error": str(exc)}), 403
```

**Public/private artifact boundary to retain:**
- `app.py:1300-1339`: Local CA certificate and trust bundle use `Permission.DOWNLOAD_PUBLIC_CERTIFICATE`; the bundle writes only the public certificate and README.
- `app.py:1606-1646`: the all-Extron ZIP requires `Permission.DOWNLOAD_PRIVATE_KEY` and materializes `combined.pem` privately.
- `app.py:1850-1911`: public artifact allowlist is `certificate.pem`, `chain.pem`, `full-chain.pem`, and `request.csr`; private route allowlist is `private-key.pem` and `combined.pem`.

---

### `templates/index.html` (component/client controller, request-response and event-driven)

**Analog:** existing auth state, fetch wrapper, static controls, tab navigation, and DOM renderers in the same template.

**State and CSRF fetch pattern** (lines 1278-1296): keep `authState` as the session-derived client contract and layer 401 recovery into this one wrapper. Preserve same-origin CSRF injection for mutation methods.
```javascript
let authState = { server_mode: false, authenticated: true, first_admin_required: false };

const nativeFetch = window.fetch.bind(window);
window.fetch = (input, init = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const url = typeof input === 'string' ? input : input.url;
  const sameOrigin = !/^https?:\/\//i.test(url || '') || (url || '').startsWith(window.location.origin);
  if (authState && authState.csrf_token && sameOrigin && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const headers = new Headers(init.headers || {});
    headers.set(authState.csrf_header || 'X-CertMon-CSRF', authState.csrf_token);
    init = { ...init, headers };
  }
  return nativeFetch(input, init);
};
```

**Authentication transition pattern** (lines 1298-1336): after `/api/auth/status`, toggle the sign-in gate/main layout and then run the centralized permission visibility pass. It must run after successful login via the existing `startApp()` transition (lines 1363-1383), not through polling.
```javascript
async function initAuth() {
  const res = await fetch('/api/auth/status');
  authState = await res.json();
  // Existing branches show either the gate or main UI.
  // Invoke centralized permission visibility after authState is assigned.
}
```

**Existing role-name helper to replace, not extend** (lines 1398-1425): `isAuthenticatedAdmin()` and `canManageServerBackup()` inspect literal role names. Replace their visibility decisions with permission membership from the status response so multi-role users receive the union. Keep the current behavior that redirects away from a tab that became unavailable.
```javascript
if (!visible && panel && panel.classList.contains('active')) switchTab('certs');
```

**Static markup pattern**:
- `templates/index.html:866-871`: navigation includes visible Audit and hidden Administration tabs. Permission metadata/central visibility must cover both tabs and panels.
- `templates/index.html:1015-1088`: Upload contains a deployment-only Toolbelt section plus manual/public-download content. Gate controls/sections separately so Upload remains when public downloads are allowed.
- `templates/index.html:1048-1050`: the static all-Extron ZIP link is a private-key control and must be marked for `download_private_key` visibility.
- `templates/index.html:1070-1077`: public and private artifact result containers are already separated; drive their rendering/visibility independently.

**Tab-selection and loading pattern** (lines 2490-2505): guard inaccessible tabs before loading their data. In particular, never invoke `loadToolbeltDevices(false)` for a principal lacking deployment permission.
```javascript
function switchTab(name) {
  if (name === 'admin' && !canManageServerBackup()) return;
  document.querySelectorAll('.tab[data-tab]').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  if (name === 'ca') loadCA();
  if (name === 'audit') prepareAuditTab();
  if (name === 'admin' && isAuthenticatedAdmin()) loadUsers();
  if (name === 'upload') {
    loadUploadDevices();
    loadAvailableCertificates();
    loadToolbeltDevices(false);
  }
}
```

**Dynamic renderer pattern:** call the one visibility pass after DOM insertion in each affected renderer.
- `templates/index.html:2517-2537`: `renderCA(ca, issued)` renders public CA/trust links and private CA backup controls together.
- `templates/index.html:3020-3044`: `loadToolbeltDevices()` fetches a deployment route and handles unavailable-state UI; prevent this request when deployment is not granted.
- `templates/index.html:3247-3280`: `renderUploadDevices()` and `renderCertificateSelect()` replace inner HTML. Apply visibility after these renderers create permission-bound controls.

**401 recovery:** centralize it at the fetch boundary, clear protected in-memory/rendered state, and re-enter `initAuth()` once for a protected same-origin response. Do not retry the original request, poll permissions, or weaken the backend 401/403 boundary.

---

### `tests/test_rbac_browser.py` (test, request-response and event-driven)

**Analog:** `tests/test_rbac.py` for server-mode principal creation/login and authorization assertions; `tests/test_auth_api.py:4-14` for temporary data-dir app reload configuration.

**Server-mode fixture/load pattern** (`tests/test_auth_api.py:4-14`):
```python
def load_app(tmp_data_dir, monkeypatch, *, server_mode=True):
    monkeypatch.setenv("CERTMON_DATA_DIR", str(tmp_data_dir))
    if server_mode:
        monkeypatch.setenv("CERTMON_SERVER_MODE", "1")
        monkeypatch.setenv("CERTMON_BIND_HOST", "127.0.0.1")
    else:
        monkeypatch.delenv("CERTMON_SERVER_MODE", raising=False)
        monkeypatch.delenv("CERTMON_BIND_HOST", raising=False)
    import app
    return importlib.reload(app)
```

**Role fixture and denied-action assertion pattern** (`tests/test_rbac.py:44-64`):
```python
module.database.create_user(
    user_id="viewer-1",
    username="viewer",
    password_hash=hash_password("correct horse"),
    roles=["viewer"],
)
client = module.app.test_client()
assert client.post(
    "/api/auth/login",
    json={"username": "viewer", "password": "correct horse"},
).status_code == 200

response = client.post("/api/renew", json=renewal_payload(), headers=auth_headers(client))
assert response.status_code == 403
```

**Session-revocation assertion pattern** (`tests/test_user_management.py:260-275`): create a target client, mutate its roles through an admin client, then assert the target's next protected request returns 401. The browser version adds the required visual assertion: after that next request it returns to sign-in and no protected UI remains.

**Browser-test requirements:** no existing browser automation fixture, runner, or configuration analog was found. Wave 0 must choose and legitimacy-audit one approved integration, add an ephemeral-port server fixture with deterministic browser teardown, and then cover actual DOM visibility rather than HTML source strings.

Required browser cases:
1. Viewer: Audit, Extron ZIP, private-key/combined-PEM, Toolbelt, administration, and backup controls absent; public certificates/chains/CSRs, public CA/trust content, Excel/devices references remain available when artifacts exist.
2. Upload: tab remains available for public artifacts and does not issue a deployment-only Toolbelt listing request.
3. Multi-role: visible controls equal the union returned in status, not a role-name shortcut.
4. Role change, disablement, password reset, and expiry: the next protected request produces the sign-in gate and cleared protected state, with no polling.
5. Desktop mode: no sign-in gate and existing local behavior remains available.

## Shared Patterns

### Effective Permission Union
**Source:** `certmon/permissions.py:25-62`  
**Apply to:** `app.py` status contract and all client visibility decisions.
```python
def permissions_for_roles(roles):
    permissions = set()
    for role in roles or []:
        permissions.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(permissions)
```

### Backend Authorization Is Authoritative
**Source:** `certmon/permissions.py:73-82`; `app.py:283-312`  
**Apply to:** all UI hiding work. Keep route `authorize(Permission...)` calls and the `AuthorizationError` 403 handler unchanged.
```python
def authorize(permission, *, granted=None):
    permission = Permission(permission)
    # Resolves local or request-scoped effective permissions.
    if permission not in effective:
        raise AuthorizationError(f"Permission denied: {permission.value}")
```

### Session Revocation
**Source:** `certmon/auth.py:125-170`, `certmon/auth.py:220-235`  
**Apply to:** browser next-request cleanup only; do not change revocation semantics.
```python
roles_changed = list(new_roles) != list(user["roles"])
updated = self.database.update_user_identity_and_roles(
    user_id,
    username=new_username,
    roles=new_roles,
    revoke_sessions=roles_changed,
    protect_final_admin=True,
)
```

### Existing API Test Helpers
**Source:** `tests/test_rbac.py:6-8`; `tests/test_user_management.py:132-163`  
**Apply to:** server-side setup used by browser fixture helpers. Obtain CSRF header/token from `/api/auth/status`; create users through the established admin API path where test setup needs audit/auth behavior.

## No Analog Found

| File / Concern | Role | Data Flow | Reason |
|---|---|---|---|
| Browser runner fixture and its dependency/config file | test infrastructure / config | event-driven, request-response | No JavaScript-capable browser harness or browser fixture exists in the inspected test suite. Choose and legitimacy-audit it in Wave 0 before product-code repair. |

## Metadata

**Analog search scope:** `certmon/permissions.py`, `certmon/auth.py`, `app.py`, `templates/index.html`, and focused existing RBAC/auth/UI/API tests only.  
**Files scanned:** 13  
**Pattern extraction date:** 2026-10-02
