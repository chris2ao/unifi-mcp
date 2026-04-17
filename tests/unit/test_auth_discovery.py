from unifi_mcp.auth.discovery import DiscoveryRegistry


def test_log_and_report():
    registry = DiscoveryRegistry()
    registry.log("/proxy/network/api/s/default/stat/device", "GET", 200)
    report = registry.get_report()
    assert len(report) == 1
    assert report[0]["endpoint"] == "/proxy/network/api/s/default/stat/device"
    assert report[0]["method"] == "GET"
    assert report[0]["status_code"] == 200
    assert "timestamp" in report[0]


def test_multiple_entries():
    registry = DiscoveryRegistry()
    registry.log("/api/a", "GET", 200)
    registry.log("/api/b", "POST", 403)
    registry.log("/api/c", "PUT", 401)
    report = registry.get_report()
    assert len(report) == 3


def test_summary_counts():
    registry = DiscoveryRegistry()
    registry.log("/api/a", "GET", 200)
    registry.log("/api/b", "GET", 200)
    registry.log("/api/c", "POST", 403)
    registry.log("/api/d", "PUT", 401)
    summary = registry.get_summary()
    assert summary["total_requests"] == 4
    assert summary["successful"] == 2
    assert summary["auth_failures"] == 2
    assert summary["success_rate"] == 50.0


def test_auth_failures_filter():
    registry = DiscoveryRegistry()
    registry.log("/api/a", "GET", 200)
    registry.log("/api/b", "POST", 403)
    registry.log("/api/c", "PUT", 401)
    failures = registry.get_auth_failures()
    assert len(failures) == 2
    assert all(f["status_code"] in (401, 403) for f in failures)


def test_clear():
    registry = DiscoveryRegistry()
    registry.log("/api/a", "GET", 200)
    registry.clear()
    assert len(registry.get_report()) == 0
