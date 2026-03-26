from __future__ import annotations

from dataclasses import dataclass


def normalize_tenant_token(value: object) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text


def default_frontend_test_warehouse_name(tenant_code: object) -> str:
    return f"S07 TEST MAIN HUB - {normalize_tenant_token(tenant_code)}"


def default_frontend_test_agency_name(tenant_code: object) -> str:
    return f"S07 TEST DISTRIBUTOR AGENCY - {normalize_tenant_token(tenant_code)}"


@dataclass(frozen=True)
class TemporaryFrontendUserSpec:
    username: str
    email: str
    user_name: str
    first_name: str
    last_name: str
    full_name: str
    job_title: str
    role_code: str
    access_level: str = "FULL"


def temporary_frontend_user_specs(tenant_code: object) -> tuple[TemporaryFrontendUserSpec, ...]:
    token = normalize_tenant_token(tenant_code)
    slug = token.lower()
    return (
        TemporaryFrontendUserSpec(
            username=f"rm_{slug}_requester_tst",
            email=f"{slug}.requester+tst@odpem.gov.jm",
            user_name=f"RM_{token}_REQUESTER_TST",
            first_name=token,
            last_name="Requester",
            full_name=f"{token} Agency Requester",
            job_title="Agency Requester",
            role_code="AGENCY_DISTRIBUTOR",
        ),
        TemporaryFrontendUserSpec(
            username=f"rm_{slug}_receiver_tst",
            email=f"{slug}.receiver+tst@odpem.gov.jm",
            user_name=f"RM_{token}_RECEIVER_TST",
            first_name=token,
            last_name="Receiver",
            full_name=f"{token} Agency Receiver",
            job_title="Agency Receiver",
            role_code="AGENCY_DISTRIBUTOR",
        ),
    )
