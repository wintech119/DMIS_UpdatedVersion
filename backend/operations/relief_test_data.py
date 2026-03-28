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
            username=f"relief_{slug}_requester_tst",
            email=f"alicia.bennett+{slug}.requester@agency.example.org",
            user_name=f"ALICIA_BENNETT_{token}_TST",
            first_name="Alicia",
            last_name="Bennett",
            full_name="Alicia Bennett",
            job_title="Distribution Coordinator",
            role_code="AGENCY_DISTRIBUTOR",
        ),
        TemporaryFrontendUserSpec(
            username=f"relief_{slug}_receiver_tst",
            email=f"dwayne.palmer+{slug}.receiver@agency.example.org",
            user_name=f"DWAYNE_PALMER_{token}_TST",
            first_name="Dwayne",
            last_name="Palmer",
            full_name="Dwayne Palmer",
            job_title="Receiving Officer",
            role_code="AGENCY_DISTRIBUTOR",
        ),
    )
