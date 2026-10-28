"""Safe unit-aware arithmetic for immutable scientific metric definitions."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import TypeAlias

from reefvision.domain.scientific_units import UNITS, normalize_quantity

FORMULA_ENGINE_VERSION = "reefvision-safe-arithmetic-1"

Dimension: TypeAlias = tuple[tuple[str, int], ...]

_DIMENSION_EXPONENTS: dict[str, Dimension] = {
    "dimensionless": (),
    "length": (("length", 1),),
    "area": (("length", 2),),
    "time": (("time", 1),),
    "speed": (("length", 1), ("time", -1)),
    "temperature": (("temperature", 1),),
    "practical_salinity": (("practical_salinity", 1),),
    "mass_salinity": (("mass_salinity", 1),),
    "count": (("count", 1),),
    "count_density": (("count", 1), ("length", -2)),
    "count_rate": (("count", 1), ("time", -1)),
    "angle": (("angle", 1),),
    "pixel_length": (("pixel_length", 1),),
    "pixel_area": (("pixel_length", 2),),
}


class MetricExpressionError(ValueError):
    """A formula or quantity cannot be evaluated without scientific ambiguity."""


@dataclass(frozen=True)
class MetricQuantity:
    value: float
    unit: str
    uncertainty: float | None = None


@dataclass(frozen=True)
class CompiledMetricExpression:
    expression: str
    symbols: tuple[str, ...]
    version: str
    tree: ast.Expression


@dataclass(frozen=True)
class MetricEvaluation:
    value: float
    unit: str
    normalized_value: float
    normalized_unit: str
    uncertainty: float | None
    normalized_uncertainty: float | None
    dimension: dict[str, int]
    derivatives: dict[str, float]


@dataclass(frozen=True)
class _Evaluated:
    value: float
    dimension: Dimension
    derivatives: dict[str, float]


def _dimension_map(dimension: Dimension) -> dict[str, int]:
    return dict(dimension)


def _dimension(values: dict[str, int]) -> Dimension:
    return tuple(sorted((name, power) for name, power in values.items() if power))


def _combine_dimensions(left: Dimension, right: Dimension, sign: int) -> Dimension:
    result = _dimension_map(left)
    for name, power in right:
        result[name] = result.get(name, 0) + sign * power
    return _dimension(result)


def _unit_dimension(unit: str) -> Dimension:
    details = UNITS.get(unit)
    if details is None:
        raise MetricExpressionError(f"Unsupported unit: {unit}")
    dimension_name = details[0]
    try:
        return _DIMENSION_EXPONENTS[dimension_name]
    except KeyError as exc:
        raise MetricExpressionError(
            f"Unit dimension is not supported for calculations: {unit}"
        ) from exc


def _ensure_finite(value: float, description: str) -> float:
    if not math.isfinite(value):
        raise MetricExpressionError(f"{description} must be finite")
    return value


def _validate_node(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        _validate_node(node.body)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        _validate_node(node.left)
        _validate_node(node.right)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        _validate_node(node.operand)
        return
    if isinstance(node, ast.Name):
        return
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        _ensure_finite(float(node.value), "Formula constant")
        return
    raise MetricExpressionError(
        f"Expression element is not allowed: {type(node).__name__}; use only arithmetic"
    )


def compile_expression(expression: str, symbols: set[str]) -> CompiledMetricExpression:
    """Parse and validate arithmetic without compiling or executing Python code."""

    if not expression.strip():
        raise MetricExpressionError("Expression is required")
    if not symbols or any(
        not symbol.isidentifier() or symbol.startswith("_") for symbol in symbols
    ):
        raise MetricExpressionError("Metric symbols must be non-private identifiers")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise MetricExpressionError("Expression is not valid arithmetic") from exc
    _validate_node(tree)
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    undeclared = referenced - symbols
    if undeclared:
        raise MetricExpressionError(f"Expression uses undeclared symbol: {sorted(undeclared)[0]}")
    unused = symbols - referenced
    if unused:
        raise MetricExpressionError(f"Declared symbol is not used: {sorted(unused)[0]}")
    return CompiledMetricExpression(
        expression=expression,
        symbols=tuple(sorted(referenced)),
        version=FORMULA_ENGINE_VERSION,
        tree=tree,
    )


def _derivatives(
    left: dict[str, float],
    right: dict[str, float],
    left_scale: float,
    right_scale: float,
) -> dict[str, float]:
    symbols = left.keys() | right.keys()
    return {
        symbol: _ensure_finite(
            left.get(symbol, 0) * left_scale + right.get(symbol, 0) * right_scale,
            "Formula derivative",
        )
        for symbol in symbols
    }


def _evaluate(node: ast.AST, values: dict[str, _Evaluated]) -> _Evaluated:
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.Constant):
        assert isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        return _Evaluated(float(node.value), (), {})
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values)
        sign = -1.0 if isinstance(node.op, ast.USub) else 1.0
        return _Evaluated(
            _ensure_finite(sign * operand.value, "Formula result"),
            operand.dimension,
            {name: sign * derivative for name, derivative in operand.derivatives.items()},
        )
    if not isinstance(node, ast.BinOp):
        raise MetricExpressionError("Expression element is not allowed")
    left = _evaluate(node.left, values)
    right = _evaluate(node.right, values)
    if isinstance(node.op, (ast.Add, ast.Sub)):
        if left.dimension != right.dimension:
            raise MetricExpressionError("Addition and subtraction require compatible dimensions")
        sign = -1.0 if isinstance(node.op, ast.Sub) else 1.0
        return _Evaluated(
            _ensure_finite(left.value + sign * right.value, "Formula result"),
            left.dimension,
            _derivatives(left.derivatives, right.derivatives, 1, sign),
        )
    if isinstance(node.op, ast.Mult):
        return _Evaluated(
            _ensure_finite(left.value * right.value, "Formula result"),
            _combine_dimensions(left.dimension, right.dimension, 1),
            _derivatives(left.derivatives, right.derivatives, right.value, left.value),
        )
    if right.value == 0:
        raise MetricExpressionError("Division by zero is not allowed")
    denominator = right.value * right.value
    return _Evaluated(
        _ensure_finite(left.value / right.value, "Formula result"),
        _combine_dimensions(left.dimension, right.dimension, -1),
        _derivatives(
            left.derivatives,
            right.derivatives,
            1 / right.value,
            -left.value / denominator,
        ),
    )


def _display_value(normalized_value: float, unit: str, *, difference: bool = False) -> float:
    _, _, scale, offset = UNITS[unit]
    value = (normalized_value - (0 if difference else offset)) / scale
    return _ensure_finite(value, "Converted result")


def evaluate_expression(
    compiled: CompiledMetricExpression,
    inputs: dict[str, MetricQuantity],
    output_unit: str,
) -> MetricEvaluation:
    """Evaluate normalized quantities and propagate independent input uncertainty."""

    if set(inputs) != set(compiled.symbols):
        raise MetricExpressionError("Input symbols must exactly match the compiled expression")
    output_dimension = _unit_dimension(output_unit)
    normalized_inputs: dict[str, _Evaluated] = {}
    normalized_uncertainties: dict[str, float | None] = {}
    for symbol, quantity in inputs.items():
        _ensure_finite(quantity.value, f"Input {symbol}")
        try:
            normalized_value, _ = normalize_quantity(quantity.value, quantity.unit)
            input_uncertainty = (
                normalize_quantity(quantity.uncertainty, quantity.unit, difference=True)[0]
                if quantity.uncertainty is not None
                else None
            )
        except ValueError as exc:
            raise MetricExpressionError(
                f"Input {symbol} requires a supported unit and finite value"
            ) from exc
        normalized_inputs[symbol] = _Evaluated(
            value=normalized_value,
            dimension=_unit_dimension(quantity.unit),
            derivatives={symbol: 1.0},
        )
        normalized_uncertainties[symbol] = input_uncertainty

    evaluated = _evaluate(compiled.tree.body, normalized_inputs)
    if evaluated.dimension != output_dimension:
        raise MetricExpressionError(
            "Declared output unit is incompatible with the expression dimension"
        )
    normalized_uncertainty: float | None = None
    if not any(value is None for value in normalized_uncertainties.values()):
        known_uncertainties = {
            symbol: value for symbol, value in normalized_uncertainties.items() if value is not None
        }
        normalized_uncertainty = math.sqrt(
            sum(
                (evaluated.derivatives[symbol] * known_uncertainties[symbol]) ** 2
                for symbol in compiled.symbols
            )
        )
        _ensure_finite(normalized_uncertainty, "Propagated uncertainty")
    normalized_unit = UNITS[output_unit][1]
    return MetricEvaluation(
        value=_display_value(evaluated.value, output_unit),
        unit=output_unit,
        normalized_value=evaluated.value,
        normalized_unit=normalized_unit,
        uncertainty=(
            _display_value(normalized_uncertainty, output_unit, difference=True)
            if normalized_uncertainty is not None
            else None
        ),
        normalized_uncertainty=normalized_uncertainty,
        dimension=_dimension_map(evaluated.dimension),
        derivatives=evaluated.derivatives,
    )
