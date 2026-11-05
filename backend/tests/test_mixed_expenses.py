import pytest

from app.domain.mixed_expenses import MixedLine, allocate_mixed_expense


def test_rounding_preserves_original_and_balances_each_rate() -> None:
    lines = [MixedLine(101, 10), MixedLine(100, 8), MixedLine(100, None)]
    result = allocate_mixed_expense(301, lines, 1, 3)
    assert result.business_total == 100
    assert result.personal_total == 201
    assert [line.business for line in result.lines] == [34, 33, 33]
    assert sum(line.business for line in result.lines) == result.business_total
    assert sum(line.personal for line in result.lines) == result.personal_total
    assert all(line.business + line.personal == line.original.gross for line in result.lines)
    assert [line.original.tax_rate for line in result.lines] == [10, 8, None]


@pytest.mark.parametrize("numerator, expected", [(0, 0), (1, 700_000)])
def test_zero_and_full_use(numerator: int, expected: int) -> None:
    result = allocate_mixed_expense(700_000, [MixedLine(700_000)], numerator, 1)
    assert result.business_total == expected
    assert result.business_total + result.personal_total == 700_000


def test_rounding_invariants_over_varied_line_amounts_and_ratios() -> None:
    for first in range(8):
        for second in range(8):
            for denominator in range(1, 8):
                for numerator in range(denominator + 1):
                    result = allocate_mixed_expense(
                        first + second,
                        [MixedLine(first), MixedLine(second)],
                        numerator,
                        denominator,
                    )
                    assert sum(line.business for line in result.lines) == result.business_total
                    assert sum(line.personal for line in result.lines) == result.personal_total
                    assert all(0 <= line.business <= line.original.gross for line in result.lines)
                    assert result.business_total == (first + second) * numerator // denominator


@pytest.mark.parametrize(
    "total,lines,numerator,denominator",
    [
        (100, [MixedLine(99)], 1, 2),
        (100, [], 1, 2),
        (100, [MixedLine(100)], 3, 2),
        (100, [MixedLine(100)], 1, 0),
        (100, [MixedLine(-1), MixedLine(101)], 1, 2),
        (100, [MixedLine(100)], True, 2),
    ],
)
def test_rejects_inconsistent_inputs(
    total: int, lines: list[MixedLine], numerator: int, denominator: int
) -> None:
    with pytest.raises(ValueError):
        allocate_mixed_expense(total, lines, numerator, denominator)
