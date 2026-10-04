class AuditService:
    def __init__(self, database):
        self.database = database

    def record(
        self,
        event_type,
        *,
        user=None,
        source_ip=None,
        target=None,
        success=True,
        details=None,
    ):
        username = None
        if isinstance(user, dict):
            username = user.get("username")
        elif user:
            username = str(user)
        self.database.record_audit_event(
            event_type=event_type,
            username=username,
            source_ip=source_ip,
            target=target,
            success=success,
            details=self._redact(details or {}),
        )

    def list(self, limit=200):
        return self.database.list_audit_events(limit=limit)

    def _redact(self, details):
        redacted = {}
        for key, value in details.items():
            if "password" in key.lower() or "token" in key.lower() or "secret" in key.lower():
                redacted[key] = "[redacted]"
            else:
                redacted[key] = value
        return redacted
