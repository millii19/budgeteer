from budgeteer.parsing import parse_amount_to_cents


def test_parse_amount_with_comma() -> None:
    assert parse_amount_to_cents("12,34") == 1234


def test_parse_amount_with_dot() -> None:
    assert parse_amount_to_cents("12.34") == 1234


def test_parse_amount_rejects_zero() -> None:
    try:
        parse_amount_to_cents("0")
    except ValueError as exc:
        assert "greater than zero" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
