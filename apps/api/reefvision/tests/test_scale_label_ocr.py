from reefvision.services.scale_label_ocr import parse_scale_label


def test_parse_scale_label_supports_common_micrometer_variants() -> None:
    parsed = parse_scale_label("500 um")
    assert parsed is not None
    assert parsed.value == 500
    assert parsed.normalized_unit == "µm"

    parsed = parse_scale_label("Scale 250 μm")
    assert parsed is not None
    assert parsed.value == 250
    assert parsed.normalized_unit == "µm"


def test_parse_scale_label_supports_decimal_metric_units() -> None:
    parsed = parse_scale_label("1.5 mm")
    assert parsed is not None
    assert parsed.value == 1.5
    assert parsed.normalized_unit == "mm"


def test_parse_scale_label_rejects_text_without_physical_value() -> None:
    assert parse_scale_label("sample 42") is None
