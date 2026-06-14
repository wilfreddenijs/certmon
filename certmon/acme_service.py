import time
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


ACME_DIRECTORIES = {
    "staging": "https://acme-staging-v02.api.letsencrypt.org/directory",
    "production": "https://acme-v02.api.letsencrypt.org/directory",
}


class ACMEAccountKeyLost(RuntimeError):
    pass


class ACMEOrderError(RuntimeError):
    def __init__(self, code, message, *, retry_at=None):
        super().__init__(message)
        self.code = code
        self.retry_at = retry_at


class ACMEAccountService:
    def __init__(self, database, vault, client_factory, *, directories=None):
        self.database = database
        self.vault = vault
        self.client_factory = client_factory
        self.directories = dict(directories or ACME_DIRECTORIES)

    def register(
        self,
        environment,
        *,
        email,
        terms_of_service_agreed,
        replace_lost_key=False,
    ):
        if environment not in self.directories:
            raise ValueError(f"Unknown ACME environment: {environment}")
        if not (email or "").strip():
            raise ValueError("ACME contact email is required")
        if terms_of_service_agreed is not True:
            raise ValueError("Explicit Terms of Service acceptance is required")

        setting_id = self._setting_id(environment)
        secret_id = self._secret_id(environment)
        existing = self.database.get_setting(setting_id)
        existing_blob = self.database.get_secret(secret_id)
        replaced_account_url = None
        if existing is not None and existing_blob is None:
            if not replace_lost_key:
                raise ACMEAccountKeyLost(
                    "ACME account metadata exists but its private key is unavailable"
                )
            replaced_account_url = existing.get("account_url")
            existing = None

        if existing is not None:
            return existing

        account_key = _generate_account_key()
        client = self.client_factory(self.directories[environment], account_key)
        registration = client.register(
            email=email.strip(), terms_of_service_agreed=True
        )
        metadata = {
            "environment": environment,
            "directory_url": self.directories[environment],
            "email": email.strip(),
            "account_url": registration["account_url"],
            "terms_of_service_url": registration.get("terms_of_service_url"),
            "terms_of_service_agreed": True,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        if replaced_account_url:
            metadata["replaced_account_url"] = replaced_account_url

        purpose = f"acme-account-key:{environment}"
        blob = self.vault.encrypt(account_key, purpose=purpose)
        self.database.put_secret(
            secret_id, blob, {"environment": environment, "email": email.strip()}
        )
        try:
            self.database.put_setting(setting_id, metadata)
        except Exception:
            self.database.delete_secret(secret_id)
            raise
        return metadata

    def load(self, environment):
        metadata = self.database.get_setting(self._setting_id(environment))
        if metadata is None:
            return None
        blob = self.database.get_secret(self._secret_id(environment))
        if blob is None:
            raise ACMEAccountKeyLost(
                "ACME account metadata exists but its private key is unavailable"
            )
        return metadata, self.vault.decrypt(blob, purpose=blob.purpose)

    @staticmethod
    def _setting_id(environment):
        return f"acme-account:{environment}"

    @staticmethod
    def _secret_id(environment):
        return f"acme-account-key:{environment}"


def _generate_account_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


class ACMEOrderService:
    def __init__(self, database, account_service, client_factory):
        self.database = database
        self.account_service = account_service
        self.client_factory = client_factory

    def create_order(self, job_id, csr_pem):
        job = self._job(job_id)
        client = self._client(job["environment"])
        order = client.create_order(
            identifiers=tuple(job["identifiers"]), csr_pem=csr_pem
        )
        challenges = []
        authorization_urls = []
        for authorization in order.get("authorizations", ()):
            authorization_urls.append(authorization["url"])
            challenge = next(
                (
                    item
                    for item in authorization.get("challenges", ())
                    if item.get("type") == "dns-01"
                ),
                None,
            )
            if challenge is None:
                raise ACMEOrderError(
                    "acme_dns_challenge_unavailable",
                    f"No DNS-01 challenge for {authorization.get('identifier')}",
                )
            challenges.append(
                {
                    "identifier": authorization["identifier"],
                    "authorization_url": authorization["url"],
                    "challenge_url": challenge["url"],
                    "fqdn": challenge["fqdn"],
                    "value": challenge["value"],
                }
            )
        record = {
            "job_id": job_id,
            "environment": job["environment"],
            "order_url": order["order_url"],
            "status": order.get("status", "pending"),
            "authorization_urls": authorization_urls,
            "dns_challenges": challenges,
            "csr_pem": csr_pem.decode("utf-8"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.database.put_setting(self._setting_id(job_id), record)
        return {
            "order_url": record["order_url"],
            "status": record["status"],
            "dns_challenges": challenges,
        }

    def poll_authorizations(
        self,
        job_id,
        *,
        max_attempts=10,
        deadline_seconds=300,
        sleep=time.sleep,
    ):
        order = self._order(job_id)
        client = self._client(order["environment"])
        deadline = datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
        total_attempts = 0
        for authorization_url in order["authorization_urls"]:
            for _ in range(max_attempts):
                if datetime.now(timezone.utc) >= deadline:
                    raise ACMEOrderError(
                        "acme_poll_timeout", "ACME authorization polling timed out"
                    )
                total_attempts += 1
                result = client.poll_authorization(authorization_url)
                status = result.get("status")
                if status == "valid":
                    break
                if status == "invalid":
                    self._raise_problem(result)
                retry_at = parse_retry_after(result.get("retry_after"))
                delay = 1
                if retry_at is not None:
                    delay = max(
                        0,
                        (retry_at - datetime.now(timezone.utc)).total_seconds(),
                    )
                sleep(min(delay, deadline_seconds))
            else:
                raise ACMEOrderError(
                    "acme_poll_timeout",
                    f"Authorization did not complete: {authorization_url}",
                )
        order["status"] = "ready"
        self.database.put_setting(self._setting_id(job_id), order)
        return {"status": "ready", "attempts": total_attempts}

    def finalize(self, job_id):
        order = self._order(job_id)
        client = self._client(order["environment"])
        result = client.finalize_order(
            order["order_url"], order["csr_pem"].encode("utf-8")
        )
        if result.get("status") == "invalid":
            self._raise_problem(result)
        order["status"] = result.get("status", "valid")
        self.database.put_setting(self._setting_id(job_id), order)
        return result

    def reconcile(self, job):
        order = self._order(job["id"])
        result = self._client(order["environment"]).get_order(order["order_url"])
        status = result.get("status")
        if status == "invalid":
            code = translate_acme_problem(result.get("problem") or {})
            message = (result.get("problem") or {}).get(
                "detail", "ACME order is invalid"
            )
            retry_at = parse_retry_after(result.get("retry_after"))
            if retry_at:
                message = f"{message}; retry after {retry_at.isoformat()}"
            return "failed", {"error_code": code, "error_message": message}
        if status in {"ready", "processing"}:
            return "issuing", {}
        if status == "valid":
            return "issuing", {}
        return "awaiting_dns", {}

    def _raise_problem(self, result):
        problem = result.get("problem") or {}
        retry_at = parse_retry_after(result.get("retry_after"))
        raise ACMEOrderError(
            translate_acme_problem(problem),
            problem.get("detail", "ACME request failed"),
            retry_at=retry_at,
        )

    def _client(self, environment):
        loaded = self.account_service.load(environment)
        if loaded is None:
            raise ValueError(f"No ACME account configured for {environment}")
        metadata, account_key = loaded
        return self.client_factory(metadata, account_key)

    def _job(self, job_id):
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["issuer_type"] != "acme":
            raise ValueError("Job is not an ACME renewal")
        if not job["environment"]:
            raise ValueError("ACME environment is required")
        return job

    def _order(self, job_id):
        order = self.database.get_setting(self._setting_id(job_id))
        if order is None:
            raise KeyError(f"No ACME order for job {job_id}")
        return order

    @staticmethod
    def _setting_id(job_id):
        return f"acme-order:{job_id}"


def translate_acme_problem(problem):
    problem_type = (problem or {}).get("type", "")
    if problem_type.endswith(":rateLimited"):
        return "acme_rate_limited"
    if problem_type.endswith(":rejectedIdentifier"):
        return "acme_rejected_identifier"
    if problem_type.endswith(":unauthorized"):
        return "acme_validation_failed"
    return "acme_request_failed"


def parse_retry_after(value, *, now=None):
    if value in (None, ""):
        return None
    now = now or datetime.now(timezone.utc)
    try:
        return now + timedelta(seconds=max(0, int(value)))
    except (TypeError, ValueError):
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


class NativeACMEAccountClient:
    def __init__(self, directory_url, account_key):
        from acme import client
        from josepy import JWKRSA

        self.net = client.ClientNetwork(
            JWKRSA.load(account_key), user_agent="CertMon"
        )
        directory = client.ClientV2.get_directory(directory_url, self.net)
        self.client = client.ClientV2(directory, self.net)

    def register(self, *, email, terms_of_service_agreed):
        from acme import messages

        registration = self.client.new_account(
            messages.NewRegistration.from_data(
                email=email, terms_of_service_agreed=terms_of_service_agreed
            )
        )
        return {
            "account_url": registration.uri,
            "terms_of_service_url": registration.terms_of_service,
        }


class NativeACMEOrderClient:
    def __init__(self, account_metadata, account_key):
        from acme import client, messages
        from josepy import JWKRSA

        account = messages.RegistrationResource(
            uri=account_metadata["account_url"], body=messages.Registration()
        )
        self.net = client.ClientNetwork(
            JWKRSA.load(account_key), account=account, user_agent="CertMon"
        )
        directory = client.ClientV2.get_directory(
            account_metadata["directory_url"], self.net
        )
        self.client = client.ClientV2(directory, self.net)
        self.key = self.net.key

    def create_order(self, *, identifiers, csr_pem):
        from acme import challenges

        order = self.client.new_order(csr_pem)
        authorizations = []
        for authorization in order.authorizations:
            identifier = authorization.body.identifier.value
            if authorization.body.wildcard and not identifier.startswith("*."):
                identifier = f"*.{identifier}"
            challenge_records = []
            for challenge in authorization.body.challenges:
                if not isinstance(challenge.chall, challenges.DNS01):
                    continue
                challenge_records.append(
                    {
                        "type": "dns-01",
                        "url": challenge.uri,
                        "fqdn": challenge.chall.validation_domain_name(
                            identifier.lstrip("*.")
                        ),
                        "value": challenge.chall.validation(self.key),
                    }
                )
            authorizations.append(
                {
                    "url": authorization.uri,
                    "identifier": identifier,
                    "challenges": challenge_records,
                }
            )
        return {
            "order_url": order.uri,
            "status": _status_name(order.body.status),
            "authorizations": authorizations,
        }

    def poll_authorization(self, authorization_url):
        from acme import messages

        response = self.client._post_as_get(authorization_url)
        body = messages.Authorization.from_json(response.json())
        result = {
            "status": _status_name(body.status),
            "retry_after": response.headers.get("Retry-After"),
        }
        problem = _authorization_problem(body)
        if problem:
            result["problem"] = problem
        return result

    def finalize_order(self, order_url, csr_pem):
        order = self._order_resource(order_url, csr_pem)
        finalized = self.client.finalize_order(
            order, datetime.now(timezone.utc) + timedelta(seconds=90)
        )
        blocks = re.findall(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----\s*",
            finalized.fullchain_pem or "",
            flags=re.DOTALL,
        )
        return {
            "status": _status_name(finalized.body.status),
            "certificate_pem": blocks[0].encode("ascii") if blocks else b"",
            "chain_pem": "".join(blocks[1:]).encode("ascii"),
        }

    def get_order(self, order_url):
        from acme import messages

        response = self.client._post_as_get(order_url)
        body = messages.Order.from_json(response.json())
        result = {
            "status": _status_name(body.status),
            "retry_after": response.headers.get("Retry-After"),
        }
        if body.error is not None:
            result["problem"] = body.error.to_partial_json()
        return result

    def _order_resource(self, order_url, csr_pem):
        from acme import messages

        response = self.client._post_as_get(order_url)
        return messages.OrderResource(
            uri=order_url,
            body=messages.Order.from_json(response.json()),
            authorizations=(),
            csr_pem=csr_pem,
        )


def _authorization_problem(body):
    for challenge in body.challenges or ():
        if challenge.error is not None:
            return challenge.error.to_partial_json()
    return None


def _status_name(status):
    return getattr(status, "name", str(status))
