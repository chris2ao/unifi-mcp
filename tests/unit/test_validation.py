"""Tests for unifi_mcp.validation boundary helpers."""
import pytest

from unifi_mcp.validation import (
    check_enum,
    check_id,
    check_mac,
    check_range,
    normalize_mac,
    validation_error,
)


def test_validation_error_shape():
    assert validation_error("bad") == {
        "error": True,
        "category": "VALIDATION_ERROR",
        "message": "bad",
    }


@pytest.mark.parametrize(
    "value",
    [
        "abc",
        "5f2a0c3e1b2c3d4e5f6a7b8c",
        "00000000-0000-0000-0000-0000000000a1",
        "a",
        "A1_b.c:d-e",
        "x" * 128,
    ],
)
def test_check_id_accepts_valid(value):
    assert check_id(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        123,
        ["abc"],
        "../etc",
        "a..b",
        "a/b",
        "a\\b",
        "a?b",
        "a#b",
        "a b",
        "a\nb",
        "abc\n",
        "-leading",
        ".hidden",
        "x" * 129,
        "a%2Fb",
    ],
)
def test_check_id_rejects_invalid(value):
    err = check_id(value, "device_id")
    assert err is not None
    assert err["error"] is True
    assert err["category"] == "VALIDATION_ERROR"
    assert "device_id" in err["message"]


def test_check_id_default_field_name():
    err = check_id("")
    assert "id" in err["message"]


@pytest.mark.parametrize(
    "value",
    [
        "aa:bb:cc:dd:ee:ff",
        "AA:BB:CC:DD:EE:FF",
        "aa-bb-cc-dd-ee-ff",
        "aabbccddeeff",
        "AABBCCDDEEFF",
        "00:11:22:33:44:55",
    ],
)
def test_check_mac_accepts(value):
    assert check_mac(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        42,
        "aa:bb:cc:dd:ee",
        "aa:bb:cc:dd:ee:ff:00",
        "aa:bb-cc:dd:ee:ff",
        "gg:bb:cc:dd:ee:ff",
        "aabbccddeef",
        "aa.bb.cc.dd.ee.ff",
        "aa:bb:cc:dd:ee:ff/x",
        "aa:bb:cc:dd:ee:ff\n",
        "aabbccddeeff\n",
    ],
)
def test_check_mac_rejects(value):
    err = check_mac(value, "client_mac")
    assert err is not None
    assert err["category"] == "VALIDATION_ERROR"
    assert "client_mac" in err["message"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
        ("aa-bb-cc-dd-ee-ff", "aa:bb:cc:dd:ee:ff"),
        ("AABBCCDDEEFF", "aa:bb:cc:dd:ee:ff"),
        ("aa:bb:cc:00:00:01", "aa:bb:cc:00:00:01"),
    ],
)
def test_normalize_mac(value, expected):
    assert normalize_mac(value) == expected


def test_normalize_mac_rejects_invalid():
    with pytest.raises(ValueError):
        normalize_mac("not-a-mac")


def test_check_enum():
    assert check_enum("a", ["a", "b"], "mode") is None
    assert check_enum("b", ("a", "b"), "mode") is None
    assert check_enum(1, {1, 2}, "level") is None
    err = check_enum("c", ["a", "b"], "mode")
    assert err["category"] == "VALIDATION_ERROR"
    assert "mode" in err["message"]
    assert "a, b" in err["message"]


def test_check_enum_accepts_generator():
    assert check_enum("x", (v for v in ["x", "y"]), "f") is None


def test_check_range():
    assert check_range(5, 1, 10, "n") is None
    assert check_range(1, 1, 10, "n") is None
    assert check_range(10, 1, 10, "n") is None
    assert check_range(2.5, 1, 10, "n") is None
    for bad in (0, 11, -1, 10.01):
        err = check_range(bad, 1, 10, "n")
        assert err["category"] == "VALIDATION_ERROR"
        assert "n" in err["message"]


@pytest.mark.parametrize("bad", [True, False, "5", None, [5], float("nan")])
def test_check_range_rejects_non_numbers(bad):
    err = check_range(bad, 0, 10, "limit")
    assert err is not None
    assert "limit" in err["message"]
