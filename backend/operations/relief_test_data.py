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
    tenant_scope: str = "tenant"
    bind_to_agency: bool = True
    bind_to_warehouse: bool = True


def temporary_local_harness_default_user() -> TemporaryFrontendUserSpec:
    return TemporaryFrontendUserSpec(
        username="local_system_admin_tst",
        email="system.admin+local@dmis.example.org",
        user_name="LOCAL_SYSTEM_ADMIN_TST",
        first_name="Morgan",
        last_name="Campbell",
        full_name="Morgan Campbell",
        job_title="System Administrator",
        role_code="SYSTEM_ADMINISTRATOR",
        tenant_scope="national",
        bind_to_agency=False,
        bind_to_warehouse=False,
    )


def temporary_frontend_user_specs(tenant_code: object) -> tuple[TemporaryFrontendUserSpec, ...]:
    token = normalize_tenant_token(tenant_code)
    slug = token.lower()
    return (
        TemporaryFrontendUserSpec(
            username="local_odpem_deputy_director_tst",
            email="natalie.williams+national.deputy-director@odpem.gov.jm",
            user_name="NATALIE_WILLIAMS_ODPEM_DEPUTY_DIRECTOR_TST",
            first_name="Natalie",
            last_name="Williams",
            full_name="Natalie Williams",
            job_title="ODPEM Deputy Director",
            role_code="ODPEM_DDG",
            tenant_scope="national",
            bind_to_agency=False,
            bind_to_warehouse=False,
        ),
        TemporaryFrontendUserSpec(
            username="local_odpem_logistics_manager_tst",
            email="kemar.campbell+national.logistics-manager@odpem.gov.jm",
            user_name="KEMAR_CAMPBELL_ODPEM_LOGISTICS_MANAGER_TST",
            first_name="Kemar",
            last_name="Campbell",
            full_name="Kemar Campbell",
            job_title="ODPEM Logistics Manager",
            role_code="ODPEM_LOGISTICS_MANAGER",
            tenant_scope="national",
            bind_to_agency=False,
            bind_to_warehouse=False,
        ),
        TemporaryFrontendUserSpec(
            username="local_odpem_logistics_officer_tst",
            email="chantal.ellis+national.logistics-officer@odpem.gov.jm",
            user_name="CHANTAL_ELLIS_ODPEM_LOGISTICS_OFFICER_TST",
            first_name="Chantal",
            last_name="Ellis",
            full_name="Chantal Ellis",
            job_title="ODPEM Logistics Officer",
            role_code="LOGISTICS_OFFICER",
            tenant_scope="national",
            bind_to_agency=False,
            bind_to_warehouse=False,
        ),
        TemporaryFrontendUserSpec(
            username=f"relief_{slug}_requester_tst",
            email=f"alicia.bennett+{slug}.requester@agency.example.org",
            user_name=f"ALICIA_BENNETT_{token}_REQUESTER_TST",
            first_name="Alicia",
            last_name="Bennett",
            full_name="Alicia Bennett",
            job_title="Distribution Coordinator",
            role_code="AGENCY_DISTRIBUTOR",
        ),
    )


def local_auth_harness_usernames(tenant_code: object) -> tuple[str, ...]:
    return (
        temporary_local_harness_default_user().username,
        *tuple(profile.username for profile in temporary_frontend_user_specs(tenant_code)),
    )
