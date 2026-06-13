from enum import Enum


class InvalidTransition(ValueError):
    pass


class RenewalState(str, Enum):
    DRAFT = "draft"
    AWAITING_DNS = "awaiting_dns"
    VALIDATING = "validating"
    ISSUING = "issuing"
    AWAITING_EXTERNAL_CA = "awaiting_external_ca"
    ISSUED = "issued"
    DEPLOYMENT_PENDING = "deployment_pending"
    DEPLOYED = "deployed"
    CLEANUP_REQUIRED = "cleanup_required"
    CANCELLED = "cancelled"
    FAILED = "failed"


ALLOWED_TRANSITIONS = {
    RenewalState.DRAFT: {
        RenewalState.AWAITING_DNS,
        RenewalState.AWAITING_EXTERNAL_CA,
        RenewalState.ISSUING,
        RenewalState.CANCELLED,
        RenewalState.FAILED,
    },
    RenewalState.AWAITING_DNS: {
        RenewalState.VALIDATING,
        RenewalState.CANCELLED,
        RenewalState.CLEANUP_REQUIRED,
        RenewalState.FAILED,
    },
    RenewalState.VALIDATING: {
        RenewalState.ISSUING,
        RenewalState.CLEANUP_REQUIRED,
        RenewalState.FAILED,
    },
    RenewalState.ISSUING: {
        RenewalState.ISSUED,
        RenewalState.CLEANUP_REQUIRED,
        RenewalState.FAILED,
    },
    RenewalState.AWAITING_EXTERNAL_CA: {
        RenewalState.ISSUED,
        RenewalState.CANCELLED,
        RenewalState.FAILED,
    },
    RenewalState.ISSUED: {
        RenewalState.DEPLOYMENT_PENDING,
        RenewalState.FAILED,
    },
    RenewalState.DEPLOYMENT_PENDING: {
        RenewalState.DEPLOYED,
        RenewalState.FAILED,
    },
    RenewalState.CLEANUP_REQUIRED: {
        RenewalState.CANCELLED,
        RenewalState.FAILED,
    },
    RenewalState.DEPLOYED: set(),
    RenewalState.CANCELLED: set(),
    RenewalState.FAILED: set(),
}


def validate_transition(current, target):
    current = RenewalState(current)
    target = RenewalState(target)
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"Cannot transition from {current.value} to {target.value}")
