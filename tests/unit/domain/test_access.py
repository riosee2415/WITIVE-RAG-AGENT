"""Unit tests for app.domain.access."""

from __future__ import annotations

import pytest

from app.domain.access import (
    LEVEL_RANK,
    AccessLevel,
    Level,
    Role,
    level_rank_of,
    min_level_rank,
)

# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


class TestRole:
    def test_values_are_strings(self) -> None:
        assert Role.WITIVE_SUPER_ADMIN == "WITIVE_SUPER_ADMIN"
        assert Role.COMPANY_ADMIN == "COMPANY_ADMIN"
        assert Role.COMPANY_MANAGER == "COMPANY_MANAGER"
        assert Role.COMPANY_USER == "COMPANY_USER"

    def test_all_four_roles_defined(self) -> None:
        assert len(Role) == 4

    def test_role_is_str_subclass(self) -> None:
        assert isinstance(Role.COMPANY_USER, str)


# ---------------------------------------------------------------------------
# AccessLevel enum
# ---------------------------------------------------------------------------


class TestAccessLevel:
    def test_values(self) -> None:
        assert AccessLevel.COMPANY_WIDE == "COMPANY_WIDE"
        assert AccessLevel.DEPARTMENT == "DEPARTMENT"
        assert AccessLevel.LEVEL == "LEVEL"
        assert AccessLevel.EXECUTIVE == "EXECUTIVE"

    def test_all_four_levels_defined(self) -> None:
        assert len(AccessLevel) == 4


# ---------------------------------------------------------------------------
# Level enum
# ---------------------------------------------------------------------------


class TestLevel:
    def test_korean_string_values(self) -> None:
        assert Level.SAWON == "사원"
        assert Level.JUIM == "주임"
        assert Level.DAERI == "대리"
        assert Level.GWAJANG == "과장"
        assert Level.CHAJANG == "차장"
        assert Level.BUJANG == "부장"
        assert Level.ISA == "이사"
        assert Level.SANGMU == "상무"
        assert Level.JUNMU == "전무"
        assert Level.SAJANG == "사장"

    def test_ten_levels_defined(self) -> None:
        assert len(Level) == 10


# ---------------------------------------------------------------------------
# LEVEL_RANK mapping
# ---------------------------------------------------------------------------


class TestLevelRank:
    def test_sawon_is_lowest(self) -> None:
        assert LEVEL_RANK[Level.SAWON] == 1

    def test_sajang_is_highest(self) -> None:
        assert LEVEL_RANK[Level.SAJANG] == 10

    def test_strict_ordering(self) -> None:
        levels_in_order = [
            Level.SAWON,
            Level.JUIM,
            Level.DAERI,
            Level.GWAJANG,
            Level.CHAJANG,
            Level.BUJANG,
            Level.ISA,
            Level.SANGMU,
            Level.JUNMU,
            Level.SAJANG,
        ]
        ranks = [LEVEL_RANK[lv] for lv in levels_in_order]
        assert ranks == sorted(ranks)
        assert len(set(ranks)) == len(ranks), "ranks must be unique"

    def test_mapping_is_immutable(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            LEVEL_RANK[Level.SAWON] = 99  # type: ignore[index]


# ---------------------------------------------------------------------------
# level_rank_of
# ---------------------------------------------------------------------------


class TestLevelRankOf:
    def test_known_level_enum(self) -> None:
        assert level_rank_of(Level.GWAJANG) == 4

    def test_known_level_string(self) -> None:
        assert level_rank_of("부장") == 6

    def test_none_returns_none(self) -> None:
        assert level_rank_of(None) is None

    def test_unknown_string_returns_none(self) -> None:
        assert level_rank_of("팀장") is None

    def test_empty_string_returns_none(self) -> None:
        assert level_rank_of("") is None

    def test_all_known_levels_resolve(self) -> None:
        for lv in Level:
            assert level_rank_of(lv) is not None


# ---------------------------------------------------------------------------
# min_level_rank
# ---------------------------------------------------------------------------


class TestMinLevelRank:
    def test_single_known_level(self) -> None:
        assert min_level_rank([Level.BUJANG]) == 6

    def test_multiple_levels_returns_minimum(self) -> None:
        assert min_level_rank([Level.BUJANG, Level.DAERI, Level.SAJANG]) == 3

    def test_empty_sequence_returns_none(self) -> None:
        assert min_level_rank([]) is None

    def test_all_unknown_returns_none(self) -> None:
        assert min_level_rank(["팀장", "본부장"]) is None

    def test_mixed_known_and_unknown(self) -> None:
        # Unknown strings must be ignored; known ones contribute.
        result = min_level_rank([Level.SAJANG, "팀장"])
        assert result == 10

    def test_string_input_accepted(self) -> None:
        assert min_level_rank(["사원", "사장"]) == 1
