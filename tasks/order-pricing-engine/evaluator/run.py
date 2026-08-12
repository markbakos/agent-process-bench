import argparse
import json
import sys
sys.dont_write_bytecode = True
from decimal import Decimal
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--round", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    tests, errors = [], []

    def check(name, fn):
        try:
            fn()
            tests.append(True)
        except Exception as exc:
            tests.append(False)
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    try:
        sys.path.insert(0, str(args.workspace / "src"))
        import order_pricing as module
        price_order = module.price_order
        index = int(args.round[1:])

        def base():
            result = price_order({"lines": [{"unit_price": 1200, "quantity": 2}, {"unit_price": 600, "quantity": 1}]})
            assert result["subtotal"] == 3000
            assert result["shipping"] == (500 if index == 0 else 400)
            assert result["total"] == result["subtotal"] + result["shipping"]
            boundary = price_order({"lines": [{"unit_price": 2500, "quantity": 2}]})
            assert boundary["shipping"] == (0 if index == 0 else 400)

        def validation():
            for line in ({"unit_price": -1, "quantity": 1}, {"unit_price": 1, "quantity": 0}, {"unit_price": 1, "quantity": True}):
                try:
                    price_order({"lines": [line]})
                except ValueError:
                    pass
                else:
                    raise AssertionError(line)

        check("base pricing", base)
        check("line validation", validation)
        if index >= 2:
            check("half-up rounding", lambda: (module.round_half_up(Decimal("2.5")) == 3 and module.round_half_up(Decimal("-2.5")) == -3) or (_ for _ in ()).throw(AssertionError()))
        if index >= 3:
            def promotion():
                order = {"lines": [{"unit_price": 1, "quantity": 1}, {"unit_price": 1, "quantity": 1}], "promotions": [50]}
                expected = 1 if index == 3 else 2
                assert price_order(order)["discount"] == expected
                stacked = price_order({"lines": [{"unit_price": 100, "quantity": 1}], "promotions": [10, 20]})
                assert stacked["discount"] == (30 if index < 5 else 20)
                assert price_order({"lines": [{"unit_price": 100, "quantity": 1}]})["discount"] == 0
                if index >= 5:
                    tied = price_order({"lines": [{"unit_price": 100, "quantity": 1}], "promotions": [10, 10]})
                    assert tied["applied_promotion_index"] == 0 and price_order({"lines": [{"unit_price": 100, "quantity": 1}]})["applied_promotion_index"] is None
            check("promotions", promotion)
        if index >= 6:
            def tax():
                result = price_order({"lines": [{"unit_price": 101, "quantity": 1}], "promotions": [10], "tax_rate": "7.5"})
                assert result["discount"] == 10 and result["tax"] == 7 and result["total"] == 498
                try:
                    price_order({"lines": [{"unit_price": 1, "quantity": 1}], "tax_rate": -1})
                except ValueError:
                    return
                raise AssertionError("negative tax accepted")
            check("tax", tax)
        status, build = "ok", "passed"
    except Exception as exc:
        tests.append(False)
        errors.append(f"import/build: {type(exc).__name__}: {exc}")
        status, build = "error", "failed"
    result = {"status": status, "tests_passed": sum(tests), "tests_total": len(tests), "build_status": build, "errors": errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
