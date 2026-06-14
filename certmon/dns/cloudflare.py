from certmon.dns.base import CleanupResult, PresentedRecord


class CloudflareError(RuntimeError):
    pass


class CloudflareDNSProvider:
    API_BASE = "https://api.cloudflare.com/client/v4"
    SECRET_ID = "dns-cloudflare-token"
    SETTING_ID = "dns-cloudflare"

    def __init__(self, token, zones, *, session, timeout=15):
        self.token = token
        self.zones = tuple(zone.lower().rstrip(".") for zone in zones)
        self.session = session
        self.timeout = timeout

    @classmethod
    def configure(cls, database, vault, *, token, zones):
        normalized = sorted({zone.lower().rstrip(".") for zone in zones if zone})
        if not token or not normalized:
            raise ValueError("Cloudflare token and at least one zone are required")
        purpose = "dns-provider:cloudflare-token"
        database.put_secret(
            cls.SECRET_ID,
            vault.encrypt(token.encode("utf-8"), purpose=purpose),
            {"provider": "cloudflare"},
        )
        try:
            database.put_setting(cls.SETTING_ID, {"zones": normalized})
        except Exception:
            database.delete_secret(cls.SECRET_ID)
            raise

    @classmethod
    def load(cls, database, vault, *, session=None, timeout=15):
        import requests

        config = database.get_setting(cls.SETTING_ID)
        blob = database.get_secret(cls.SECRET_ID)
        if config is None or blob is None:
            raise CloudflareError("Cloudflare DNS provider is not configured")
        token = vault.decrypt(blob, purpose=blob.purpose).decode("utf-8")
        return cls(
            token,
            config["zones"],
            session=session or requests.Session(),
            timeout=timeout,
        )

    def verify_token(self):
        result = self._request("GET", "/user/tokens/verify")
        if result.get("status") != "active":
            raise CloudflareError("Cloudflare API token is not active")
        return True

    def present(self, records):
        zones = self._list_zones()
        presented = []
        seen = set()
        try:
            for record in records:
                name = record.fqdn.lower().rstrip(".")
                key = (name, record.value)
                if key in seen:
                    continue
                seen.add(key)
                zone = self._select_zone(name, zones)
                result = self._request(
                    "POST",
                    f"/zones/{zone['id']}/dns_records",
                    json={
                        "type": "TXT",
                        "name": name,
                        "content": record.value,
                        "ttl": 60,
                    },
                )
                presented.append(
                    PresentedRecord(
                        fqdn=name,
                        value=record.value,
                        provider="cloudflare",
                        zone_id=zone["id"],
                        record_id=result["id"],
                    )
                )
        except Exception:
            self.cleanup(tuple(presented))
            raise
        return tuple(presented)

    def cleanup(self, presented):
        cleaned = 0
        errors = []
        for record in presented:
            response = self._raw_request(
                "DELETE",
                f"/zones/{record.zone_id}/dns_records/{record.record_id}",
            )
            if response.status_code == 404:
                cleaned += 1
                continue
            try:
                self._result(response)
                cleaned += 1
            except CloudflareError as error:
                errors.append(str(error))
        return CleanupResult(cleaned=cleaned, errors=tuple(errors))

    def _list_zones(self):
        zones = []
        page = 1
        while True:
            response = self._raw_request("GET", "/zones", params={"page": page})
            payload = self._payload(response)
            zones.extend(payload.get("result") or [])
            info = payload.get("result_info") or {}
            if page >= int(info.get("total_pages", 1)):
                break
            page += 1
        return zones

    def _select_zone(self, fqdn, available):
        configured = sorted(
            (
                zone
                for zone in self.zones
                if fqdn == zone or fqdn.endswith(f".{zone}")
            ),
            key=len,
            reverse=True,
        )
        available_by_name = {zone["name"].lower(): zone for zone in available}
        for zone_name in configured:
            if zone_name in available_by_name:
                return available_by_name[zone_name]
        raise CloudflareError("DNS name is not in an accessible configured zone")

    def _request(self, method, path, **kwargs):
        return self._result(self._raw_request(method, path, **kwargs))

    def _raw_request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self.token}"
        headers["Content-Type"] = "application/json"
        return self.session.request(
            method,
            f"{self.API_BASE}{path}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )

    def _result(self, response):
        payload = self._payload(response)
        return payload.get("result")

    @staticmethod
    def _payload(response):
        try:
            payload = response.json()
        except Exception as error:
            raise CloudflareError(
                f"Cloudflare returned invalid JSON (HTTP {response.status_code})"
            ) from error
        if response.status_code >= 400 or not payload.get("success"):
            errors = payload.get("errors") or []
            message = errors[0].get("message") if errors else "request failed"
            raise CloudflareError(
                f"Cloudflare request failed (HTTP {response.status_code}): {message}"
            )
        return payload
