from datetime import date

from budgeteer.codegen import build_base_transaction_code


def test_transaction_code_contains_relevant_fields() -> None:
    code = build_base_transaction_code(
        recipient_name="Volley Club Supplies",
        category_chain=["Operations", "Equipment", "Balls"],
        transaction_date=date(2026, 3, 25),
    )

    assert code.startswith("VOLLEYCL-OPE")
    assert code.endswith("260325")
