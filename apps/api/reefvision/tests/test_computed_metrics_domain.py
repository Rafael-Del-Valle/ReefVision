import math

import pytest

from reefvision.domain.computed_metrics import (
    FORMULA_ENGINE_VERSION,
    MetricExpressionError,
    MetricQuantity,
    compile_expression,
    evaluate_expression,
)


def test_evaluates_precedence_and_converts_compatible_length_units() -> None:
    compiled = compile_expression("(length + offset) * 2", {"length", "offset"})

    result = evaluate_expression(
        compiled,
        {
            "length": MetricQuantity(value=1, unit="m"),
            "offset": MetricQuantity(value=50, unit="cm"),
        },
        output_unit="cm",
    )

    assert compiled.version == FORMULA_ENGINE_VERSION
    assert compiled.symbols == ("length", "offset")
    assert result.value == pytest.approx(300)
    assert result.unit == "cm"
    assert result.normalized_value == pytest.approx(3)
    assert result.normalized_unit == "m"
    assert result.dimension == {"length": 1}
    assert result.derivatives == {"length": 2, "offset": 2}


@pytest.mark.parametrize(
    ("expression", "inputs", "output_unit", "expected"),
    [
        (
            "organisms / surveyed_area",
            {
                "organisms": MetricQuantity(value=20, unit="count"),
                "surveyed_area": MetricQuantity(value=100, unit="cm2"),
            },
            "count/m2",
            2000,
        ),
        (
            "events / duration",
            {
                "events": MetricQuantity(value=4, unit="count"),
                "duration": MetricQuantity(value=30, unit="min"),
            },
            "count/h",
            8,
        ),
        (
            "covered / total",
            {
                "covered": MetricQuantity(value=1, unit="m2"),
                "total": MetricQuantity(value=4, unit="m2"),
            },
            "%",
            25,
        ),
    ],
)
def test_evaluates_density_rates_and_percentages(
    expression: str,
    inputs: dict[str, MetricQuantity],
    output_unit: str,
    expected: float,
) -> None:
    result = evaluate_expression(
        compile_expression(expression, set(inputs)),
        inputs,
        output_unit=output_unit,
    )

    assert result.value == pytest.approx(expected)


def test_propagates_independent_standard_uncertainty_from_original_units() -> None:
    result = evaluate_expression(
        compile_expression("distance / duration", {"distance", "duration"}),
        {
            "distance": MetricQuantity(value=10, unit="m", uncertainty=0.3),
            "duration": MetricQuantity(value=2, unit="s", uncertainty=0.1),
        },
        output_unit="m/s",
    )

    assert result.value == pytest.approx(5)
    assert result.derivatives == {"distance": pytest.approx(0.5), "duration": pytest.approx(-2.5)}
    assert result.uncertainty == pytest.approx(math.sqrt(0.15**2 + 0.25**2))
    assert result.normalized_uncertainty == result.uncertainty


def test_missing_input_uncertainty_keeps_result_uncertainty_unknown() -> None:
    result = evaluate_expression(
        compile_expression("a + b", {"a", "b"}),
        {
            "a": MetricQuantity(value=1, unit="m", uncertainty=0.1),
            "b": MetricQuantity(value=2, unit="m"),
        },
        output_unit="m",
    )

    assert result.uncertainty is None
    assert result.normalized_uncertainty is None


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('whoami')",
        "value.real",
        "value ** 2",
        "[value][0]",
        "True + value",
    ],
)
def test_rejects_syntax_outside_the_arithmetic_whitelist(expression: str) -> None:
    with pytest.raises(MetricExpressionError, match="not allowed"):
        compile_expression(expression, {"value"})


def test_rejects_missing_or_undeclared_symbols() -> None:
    with pytest.raises(MetricExpressionError, match="undeclared symbol"):
        compile_expression("a + b", {"a"})
    compiled = compile_expression("a + b", {"a", "b"})
    with pytest.raises(MetricExpressionError, match="exactly match"):
        evaluate_expression(
            compiled,
            {"a": MetricQuantity(value=1, unit="m")},
            output_unit="m",
        )


def test_rejects_incompatible_dimensions_and_output_units() -> None:
    with pytest.raises(MetricExpressionError, match="compatible dimensions"):
        evaluate_expression(
            compile_expression("length + duration", {"length", "duration"}),
            {
                "length": MetricQuantity(value=1, unit="m"),
                "duration": MetricQuantity(value=1, unit="s"),
            },
            output_unit="m",
        )
    with pytest.raises(MetricExpressionError, match="output unit"):
        evaluate_expression(
            compile_expression("length * 2", {"length"}),
            {"length": MetricQuantity(value=1, unit="m")},
            output_unit="s",
        )


@pytest.mark.parametrize(
    ("quantity", "expression", "message"),
    [
        (MetricQuantity(value=1, unit="count"), "value / 0", "zero"),
        (MetricQuantity(value=float("inf"), unit="count"), "value + 1", "finite"),
        (MetricQuantity(value=1, unit="furlong"), "value + 1", "supported unit"),
    ],
)
def test_rejects_invalid_or_non_finite_quantities(
    quantity: MetricQuantity, expression: str, message: str
) -> None:
    with pytest.raises(MetricExpressionError, match=message):
        evaluate_expression(
            compile_expression(expression, {"value"}),
            {"value": quantity},
            output_unit="count",
        )


@pytest.mark.parametrize(
    ("expression", "output_unit"),
    [("a / b", "1"), ("a - b", "degF"), ("a + b", "K"), ("a * 2", "degC")],
)
def test_rejects_ambiguous_absolute_temperature_arithmetic(expression, output_unit) -> None:
    inputs = {"a": MetricQuantity(300, "K"), "b": MetricQuantity(150, "K")}
    if "b" not in expression:
        inputs.pop("b")
    with pytest.raises(MetricExpressionError, match="temperature arithmetic"):
        evaluate_expression(compile_expression(expression, set(inputs)), inputs, output_unit)


def test_absolute_temperature_identity_still_converts_units() -> None:
    result = evaluate_expression(
        compile_expression("temperature", {"temperature"}),
        {"temperature": MetricQuantity(300, "K", 2)},
        "degF",
    )
    assert result.value == pytest.approx(80.33)
    assert result.uncertainty == pytest.approx(3.6)


def test_small_quotient_has_finite_correct_derivatives() -> None:
    result = evaluate_expression(
        compile_expression("a / b", {"a", "b"}),
        {"a": MetricQuantity(1e-200, "m", 1e-201), "b": MetricQuantity(1e-200, "m", 1e-201)},
        "1",
    )
    assert result.value == 1
    assert result.derivatives == {"a": pytest.approx(1e200), "b": pytest.approx(-1e200)}
    assert result.uncertainty == pytest.approx(math.sqrt(0.02))


def test_large_uncertainties_use_stable_norm() -> None:
    result = evaluate_expression(
        compile_expression("a + b", {"a", "b"}),
        {"a": MetricQuantity(1, "m", 1e200), "b": MetricQuantity(1, "m", 1e200)},
        "m",
    )
    assert result.uncertainty == pytest.approx(math.sqrt(2) * 1e200)


@pytest.mark.parametrize("expression", ["a + " + "9" * 400, "a+" * 600 + "a"])
def test_numeric_and_expression_limits_raise_domain_errors(expression) -> None:
    with pytest.raises(MetricExpressionError):
        compile_expression(expression, {"a"})


def test_overflowing_uncertainty_is_a_domain_error() -> None:
    with pytest.raises(MetricExpressionError, match="finite"):
        evaluate_expression(
            compile_expression("a * 2", {"a"}), {"a": MetricQuantity(1, "m", 1e308)}, "m"
        )


@pytest.mark.parametrize("uncertainty", [10**400, -1])
def test_invalid_uncertainty_raises_domain_error(uncertainty) -> None:
    with pytest.raises(MetricExpressionError):
        evaluate_expression(
            compile_expression("a", {"a"}), {"a": MetricQuantity(1, "m", uncertainty)}, "m"
        )
