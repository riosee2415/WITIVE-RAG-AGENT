"""Unit tests for app.domain.tenant."""

from __future__ import annotations

import unicodedata
from datetime import date
from uuid import UUID

import pytest

from app.domain.access import Level, Role
from app.domain.tenant import (
    SYSTEM_CRON_USER_ID,
    TenantContext,
    is_admin,
    is_manager_or_above,
    normalize_departments,
)

_TENANT_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
_USER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000002")
_REQUEST_ID = "req-test-001"


def _ctx(**overrides: object) -> TenantContext:
    defaults: dict[str, object] = {
        "tenant_id": _TENANT_ID,
        "user_id": _USER_ID,
        "role": Role.COMPANY_USER,
        "departments": (),
        "level": None,
        "hire_date": None,
        "request_id": _REQUEST_ID,
    }
    defaults.update(overrides)
    return TenantContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SYSTEM_CRON_USER_ID constant
# ---------------------------------------------------------------------------


class TestSystemCronUserId:
    def test_reserved_uuid(self) -> None:
        assert str(SYSTEM_CRON_USER_ID) == "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# TenantContext frozen / slots
# ---------------------------------------------------------------------------


class TestTenantContextImmutability:
    def test_frozen_raises_on_assign(self) -> None:
        ctx = _ctx()
        with pytest.raises((AttributeError, TypeError)):
            ctx.role = Role.COMPANY_ADMIN  # type: ignore[misc]

    def test_is_hashable(self) -> None:
        ctx = _ctx()
        assert hash(ctx) is not None

    def test_equality(self) -> None:
        ctx1 = _ctx()
        ctx2 = _ctx()
        assert ctx1 == ctx2

    def test_departments_must_be_tuple(self) -> None:
        ctx = _ctx(departments=("hr", "finance"))
        assert isinstance(ctx.departments, tuple)


# ---------------------------------------------------------------------------
# TenantContext.is_system_cron
# ---------------------------------------------------------------------------


class TestIsSystemCron:
    def test_system_cron_user_id_returns_true(self) -> None:
        ctx = _ctx(user_id=SYSTEM_CRON_USER_ID)
        assert ctx.is_system_cron is True

    def test_regular_user_returns_false(self) -> None:
        ctx = _ctx(user_id=_USER_ID)
        assert ctx.is_system_cron is False


# ---------------------------------------------------------------------------
# normalize_departments
# ---------------------------------------------------------------------------


class TestNormalizeDepartments:
    def test_simple_comma_split(self) -> None:
        result = normalize_departments("HR,Finance")
        assert set(result) == {"hr", "finance"}

    def test_strips_whitespace(self) -> None:
        result = normalize_departments("  HR  ,  Finance  ")
        assert set(result) == {"hr", "finance"}

    def test_removes_empty_items(self) -> None:
        result = normalize_departments(",HR,,Finance,")
        assert "" not in result
        assert set(result) == {"hr", "finance"}

    def test_empty_string_returns_empty_tuple(self) -> None:
        assert normalize_departments("") == ()

    def test_sorted_output(self) -> None:
        result = normalize_departments("finance,hr")
        assert list(result) == sorted(result)

    def test_nfc_normalization(self) -> None:
        # NFC normalise: compose NFD form into NFC
        nfd_string = unicodedata.normalize("NFD", "인사부")
        result = normalize_departments(nfd_string)
        for dept in result:
            assert unicodedata.is_normalized("NFC", dept)

    def test_korean_preserved_as_is(self) -> None:
        result = normalize_departments("인사부,재무부")
        assert "인사부" in result
        assert "재무부" in result

    def test_ascii_lowercased(self) -> None:
        result = normalize_departments("HR,Finance,IT")
        assert "hr" in result
        assert "finance" in result
        assert "it" in result

    def test_single_item(self) -> None:
        result = normalize_departments("hr")
        assert result == ("hr",)


# ---------------------------------------------------------------------------
# is_admin / is_manager_or_above
# ---------------------------------------------------------------------------


class TestIsAdmin:
    def test_super_admin_is_admin(self) -> None:
        assert is_admin(Role.WITIVE_SUPER_ADMIN) is True

    def test_company_admin_is_admin(self) -> None:
        assert is_admin(Role.COMPANY_ADMIN) is True

    def test_manager_is_not_admin(self) -> None:
        assert is_admin(Role.COMPANY_MANAGER) is False

    def test_user_is_not_admin(self) -> None:
        assert is_admin(Role.COMPANY_USER) is False


class TestIsManagerOrAbove:
    def test_super_admin(self) -> None:
        assert is_manager_or_above(Role.WITIVE_SUPER_ADMIN) is True

    def test_company_admin(self) -> None:
        assert is_manager_or_above(Role.COMPANY_ADMIN) is True

    def test_company_manager(self) -> None:
        assert is_manager_or_above(Role.COMPANY_MANAGER) is True

    def test_company_user_is_not(self) -> None:
        assert is_manager_or_above(Role.COMPANY_USER) is False


# ---------------------------------------------------------------------------
# TenantContext with level / hire_date
# ---------------------------------------------------------------------------


class TestTenantContextFields:
    def test_level_can_be_set(self) -> None:
        ctx = _ctx(level=Level.GWAJANG)
        assert ctx.level is Level.GWAJANG

    def test_hire_date_can_be_set(self) -> None:
        ctx = _ctx(hire_date=date(2020, 1, 1))
        assert ctx.hire_date == date(2020, 1, 1)
