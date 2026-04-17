from unifi_mcp.errors import UnifiError, ErrorCategory


def test_error_categories_exist():
    assert ErrorCategory.CONNECTION_ERROR == "CONNECTION_ERROR"
    assert ErrorCategory.AUTH_ERROR == "AUTH_ERROR"
    assert ErrorCategory.NOT_FOUND == "NOT_FOUND"
    assert ErrorCategory.VALIDATION_ERROR == "VALIDATION_ERROR"
    assert ErrorCategory.CONFLICT == "CONFLICT"
    assert ErrorCategory.PRODUCT_UNAVAILABLE == "PRODUCT_UNAVAILABLE"
    assert ErrorCategory.FIRMWARE_UNSUPPORTED == "FIRMWARE_UNSUPPORTED"


def test_unifi_error_has_category_and_message():
    error = UnifiError(ErrorCategory.AUTH_ERROR, "API key rejected")
    assert error.category == "AUTH_ERROR"
    assert error.message == "API key rejected"
    assert str(error) == "[AUTH_ERROR] API key rejected"


def test_unifi_error_to_dict():
    error = UnifiError(ErrorCategory.NOT_FOUND, "Device not found", endpoint="/api/device/abc")
    result = error.to_dict()
    assert result["error"] is True
    assert result["category"] == "NOT_FOUND"
    assert result["message"] == "Device not found"
    assert result["endpoint"] == "/api/device/abc"


def test_status_code_to_category():
    from unifi_mcp.errors import status_to_category
    assert status_to_category(401) == ErrorCategory.AUTH_ERROR
    assert status_to_category(403) == ErrorCategory.AUTH_ERROR
    assert status_to_category(404) == ErrorCategory.NOT_FOUND
    assert status_to_category(400) == ErrorCategory.VALIDATION_ERROR
    assert status_to_category(409) == ErrorCategory.CONFLICT
    assert status_to_category(500) is None
