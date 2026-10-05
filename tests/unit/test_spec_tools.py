"""Tests for scripts/spec_diff.py and scripts/spec_coverage.py (no network)."""

import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "specs"
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


spec_diff = _load("spec_diff")
spec_coverage = _load("spec_coverage")

OLD = json.loads((FIXTURES / "tiny-old.json").read_text())
NEW = json.loads((FIXTURES / "tiny-new.json").read_text())

LLMS = """
## OpenAPI Specifications
- [Network OpenAPI Spec](https://developer.ui.com/network/v10.6.106/openapi.json): x
- [Protect OpenAPI Spec](https://developer.ui.com/protect/v7.3.70/openapi.json): x
- [Site Manager OpenAPI Spec](https://developer.ui.com/site-manager/v1.0.0/openapi.json): x
"""


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ----------------------------------------------------------- diff logic


def test_extract_operations_and_flatten():
    ops = spec_diff.extract_operations(OLD)
    assert set(ops) == {
        "GET /v1/sites/{siteId}/widgets",
        "POST /v1/sites/{siteId}/widgets",
        "GET /v1/sites/{siteId}/gadgets",
    }
    body = ops["POST /v1/sites/{siteId}/widgets"]["body"]
    assert body["name"]["required"] is True
    assert body["mode"]["enum"] == ["A", "B"]
    assert body["tags"]["type"] == "array<string>"
    assert "nested.level" in body
    assert ops["GET /v1/sites/{siteId}/widgets"]["params"]["path:siteId"]["required"]


def test_recursive_schema_terminates():
    spec = {
        "paths": {"/x": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Node"}}}}}}},
        "components": {"schemas": {"Node": {"type": "object", "properties": {
            "child": {"$ref": "#/components/schemas/Node"}, "v": {"type": "string"}}}}},
    }
    body = spec_diff.extract_operations(spec)["POST /x"]["body"]
    assert "v" in body


def test_diff_specs_detects_all_change_kinds():
    result = spec_diff.diff_specs(OLD, NEW)
    assert result["added_operations"] == ["DELETE /v1/sites/{siteId}/gizmos"]
    assert result["removed_operations"] == ["GET /v1/sites/{siteId}/gadgets"]
    changes = result["changed_operations"][0]["changes"]
    assert any("added `color`" in c for c in changes)
    assert any("removed `tags`" in c for c in changes)
    assert any("`mode` enum added: C" in c for c in changes)
    assert any("`nested.level` type integer -> string" in c for c in changes)


def test_diff_enum_removed_and_required_change():
    old = {"paths": {"/x": {"post": {"requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "required": ["a"],
        "properties": {"a": {"type": "string", "enum": ["X", "Y"]}}}}}}}}}}
    new = {"paths": {"/x": {"post": {"requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "properties": {"a": {"type": "string", "enum": ["X"]}}}}}}}}}}
    changes = spec_diff.diff_specs(old, new)["changed_operations"][0]["changes"]
    assert any("enum removed: Y" in c for c in changes)
    assert any("no longer required" in c for c in changes)


def test_identical_specs_no_changes():
    result = spec_diff.build_result("tiny", "1.0.0", "1.0.0", OLD, OLD)
    assert spec_diff.has_changes(result) is False
    assert "No changes." in spec_diff.render_markdown([result])


def test_param_enum_diff():
    def make(values):
        return {"paths": {"/x": {"get": {"parameters": [
            {"name": "k", "in": "query", "schema": {"type": "string", "enum": values}}]}}}}
    changes = spec_diff.diff_specs(make(["a"]), make(["a", "b"]))["changed_operations"][0]["changes"]
    assert changes == ["param `query:k` enum added: b"]


# ----------------------------------------------------------- parsing and files


def test_parse_llms_versions():
    assert spec_diff.parse_llms_versions(LLMS) == {
        "network": "10.6.106", "protect": "7.3.70", "site-manager": "1.0.0"}


def test_find_vendored_picks_newest(tmp_path):
    for name in ("protect-7.3.9.json", "protect-7.3.70.json", "network-10.6.106.json"):
        (tmp_path / name).write_text("{}")
    version, path = spec_diff.find_vendored("protect", tmp_path)
    assert version == "7.3.70" and path.name == "protect-7.3.70.json"
    assert spec_diff.find_vendored("site-manager", tmp_path) is None


def test_write_vendored_replaces_old_version(tmp_path):
    (tmp_path / "protect-7.3.70.json").write_text("{}")
    target = spec_diff.write_vendored("protect", "7.4.0", {"b": 1, "a": 2}, tmp_path)
    assert target.name == "protect-7.4.0.json"
    assert not (tmp_path / "protect-7.3.70.json").exists()
    text = target.read_text()
    assert text.index('"a"') < text.index('"b"') and text.endswith("\n")


def test_vendored_files_are_stable_pretty_json():
    for path in (ROOT / "docs" / "specs").glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert text == spec_diff.dump_spec(json.loads(text)), path.name


# ----------------------------------------------------------- http (mocked)


def test_http_get_console_uses_get_and_header(monkeypatch):
    seen = {}

    class FakeOpener:
        def open(self, request, timeout=None):
            seen["method"] = request.get_method()
            seen["url"] = request.full_url
            seen["key"] = request.get_header("X-api-key")
            return FakeResponse(json.dumps(OLD).encode())

    def fake_build_opener(*handlers):
        seen["handlers"] = handlers
        for h in handlers:
            ctx = getattr(h, "_context", None)
            if ctx is not None:
                seen["verify"] = ctx.verify_mode
        return FakeOpener()

    monkeypatch.setattr(spec_diff.urllib.request, "build_opener", fake_build_opener)
    spec = spec_diff.fetch_console_network_spec("192.0.2.1", "k-test")
    assert spec["info"]["version"] == "1.0.0"
    assert seen["method"] == "GET"
    assert seen["url"] == "https://192.0.2.1/proxy/network/api-docs/integration.json"
    assert seen["key"] == "k-test"
    assert seen["verify"] == spec_diff.ssl.CERT_NONE


def test_http_get_failure_is_runtime_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(spec_diff.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="down"):
        spec_diff._http_get("https://example.invalid/x")


def _fake_world(monkeypatch, console_spec, remote_spec):
    def fake_get(url, headers=None, verify=True, follow_redirects=True):
        if url.endswith("llms.txt"):
            return LLMS.encode()
        if "api-docs" in url:
            return json.dumps(console_spec).encode()
        return json.dumps(remote_spec).encode()

    monkeypatch.setattr(spec_diff, "_http_get", fake_get)


def _vendor(tmp_path, spec, service, version):
    (tmp_path / f"{service}-{version}.json").write_text(spec_diff.dump_spec(spec))


def test_collect_online_diffs_and_flags(monkeypatch, tmp_path):
    network_old = {**OLD, "info": {"title": "N", "version": "10.6.106"}}
    network_new = {**NEW, "info": {"title": "N", "version": "10.7.0"}}
    _vendor(tmp_path, network_old, "network", "10.6.106")
    _vendor(tmp_path, OLD, "protect", "7.3.70")
    _fake_world(monkeypatch, network_new, OLD)
    results, fetched = spec_diff.collect_online(tmp_path, "h", "k")
    by_service = {r["service"]: r for r in results}
    assert by_service["network"]["version_changed"] is True
    assert by_service["network"]["added_operations"]
    assert by_service["protect"]["version_changed"] is False
    assert by_service["site-manager"]["error"].startswith("no vendored spec")
    assert set(fetched) == {"network", "protect", "site-manager"}


def test_collect_online_missing_credentials(monkeypatch, tmp_path):
    _fake_world(monkeypatch, OLD, OLD)
    results, _ = spec_diff.collect_online(tmp_path, None, None)
    assert "UNIFI_HOST" in results[0]["error"]


def test_collect_online_llms_failure(monkeypatch, tmp_path):
    def fail(url, headers=None, verify=True, follow_redirects=True):
        raise RuntimeError("offline")

    monkeypatch.setattr(spec_diff, "_http_get", fail)
    results, fetched = spec_diff.collect_online(tmp_path, "h", "k")
    assert all(r["error"] for r in results) and not fetched


# ----------------------------------------------------------- main / CLI


def test_main_offline_markdown_and_exit_codes(capsys):
    a, b = str(FIXTURES / "tiny-old.json"), str(FIXTURES / "tiny-new.json")
    assert spec_diff.main(["--offline", a, b]) == 0
    out = capsys.readouterr().out
    assert "Added operations" in out and "gizmos" in out
    assert spec_diff.main(["--offline", a, b, "--fail-on-change"]) == 1
    assert spec_diff.main(["--offline", a, a, "--fail-on-change"]) == 0


def test_main_offline_json(capsys):
    a, b = str(FIXTURES / "tiny-old.json"), str(FIXTURES / "tiny-new.json")
    assert spec_diff.main(["--offline", a, b, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["results"][0]["removed_operations"] == ["GET /v1/sites/{siteId}/gadgets"]


def test_main_update_writes_vendored(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(spec_diff, "SPEC_DIR", tmp_path)
    monkeypatch.setattr(spec_diff, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("UNIFI_HOST", "192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "k")
    _fake_world(monkeypatch, {**NEW, "info": {"title": "N", "version": "10.7.0"}}, NEW)
    assert spec_diff.main(["--update"]) == 0
    assert (tmp_path / "network-10.7.0.json").exists()
    assert (tmp_path / "protect-7.3.70.json").exists()
    assert "Updated vendored specs" in capsys.readouterr().out


# ----------------------------------------------------------- coverage


@pytest.mark.parametrize(
    "raw,prefix,expected",
    [
        ("/proxy/network/integration/v1/sites/{site_id}/zones/{zone_id}", "/proxy/network/integration", "/v1/sites/{}/zones/{}"),
        ("/proxy/network/integration/v1/sites/{{site_id}}/zones?limit=5", "/proxy/network/integration", "/v1/sites/{}/zones"),
        ("/v1/sites/{siteId}/zones/", "", "/v1/sites/{}/zones"),
        ("/proxy/protect/integration/v1/cameras/{}", "/proxy/protect/integration", "/v1/cameras/{}"),
    ],
)
def test_normalize_path(raw, prefix, expected):
    assert spec_coverage.normalize_path(raw, prefix) == expected


def test_collect_tool_literals(tmp_path):
    (tmp_path / "mod.py").write_text(
        'A = "/proxy/network/integration/v1/sites/{site_id}/widgets"\n'
        'B = f"/proxy/network/integration/v1/sites/{{site_id}}/widgets/{wid}"\n'
        'C = ("/proxy/protect/integration"\n     "/v1/cameras")\n'
        'D = "not a path"\n'
    )
    (tmp_path / "broken.py").write_text("def (:\n")
    literals = spec_coverage.collect_tool_literals(tmp_path)
    assert "/proxy/protect/integration/v1/cameras" in literals
    assert "not a path" not in literals
    assert any(x.endswith("/widgets/{}") for x in literals)


def test_compute_coverage_by_service_prefix():
    literals = {
        "/proxy/network/integration/v1/sites/{site_id}/widgets",
        "/proxy/protect/integration/v1/sites/{}/gadgets",  # wrong service, must not count
    }
    report = spec_coverage.compute_coverage("network", OLD, literals)
    covered = {(r["method"], r["path"]) for r in report["rows"] if r["covered"]}
    assert covered == {("GET", "/v1/sites/{siteId}/widgets"), ("POST", "/v1/sites/{siteId}/widgets")}
    assert report["percent"] == 66.7 and report["total"] == 3
    assert spec_coverage.compute_coverage("empty", {"paths": {}}, literals)["percent"] == 0.0


def test_load_reports_and_check_min(tmp_path, monkeypatch, capsys):
    specs = tmp_path / "specs"
    specs.mkdir()
    shutil.copy(FIXTURES / "tiny-old.json", specs / "network-1.0.0.json")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "m.py").write_text('P = "/proxy/network/integration/v1/sites/{site_id}/widgets"\n')
    reports = spec_coverage.load_reports(specs, tools)
    assert len(reports) == 1 and reports[0]["percent"] == 66.7

    monkeypatch.setattr(spec_coverage, "load_reports", lambda: reports)
    assert spec_coverage.main([]) == 0
    assert "| GET | `/v1/sites/{siteId}/widgets` | yes |" in capsys.readouterr().out
    assert spec_coverage.main(["--check-min", "50"]) == 0
    assert spec_coverage.main(["--check-min", "90"]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_real_vendored_specs_load():
    reports = spec_coverage.load_reports()
    assert {r["service"].split()[0] for r in reports} == {"network", "protect", "site-manager"}
    assert all(r["total"] > 0 for r in reports)


def test_published_spec_url_uses_v_prefix(monkeypatch):
    urls = []

    def fake_get(url, headers=None, verify=True, follow_redirects=True):
        urls.append(url)
        return b"{}"

    monkeypatch.setattr(spec_diff, "_http_get", fake_get)
    spec_diff.fetch_published_spec("protect", "7.3.70")
    assert urls == ["https://developer.ui.com/protect/v7.3.70/openapi.json"]


# ----------------------------------------------------------- polymorphic and response diffs


def _poly_spec(extra_field=False, new_variant=False, response_field="ipv4Address", max_len=10):
    a_props = {"ipv4Address": {"type": "string"}}
    if extra_field:
        a_props["ttl"] = {"type": "integer"}
    mapping = {"A_RECORD": "#/components/schemas/ARecord"}
    schemas = {
        "Policy": {
            "type": "object",
            "required": ["type"],
            "properties": {"type": {"type": "string"}, "enabled": {"type": "boolean"}},
            "discriminator": {"propertyName": "type", "mapping": mapping},
        },
        "ARecord": {
            "allOf": [{"$ref": "#/components/schemas/Policy"}, {"type": "object", "properties": a_props}]
        },
        "Item": {
            "type": "object",
            "properties": {response_field: {"type": "string", "maxLength": max_len}},
        },
    }
    if new_variant:
        mapping["HTTPS_RECORD"] = "#/components/schemas/HttpsRecord"
        schemas["HttpsRecord"] = {
            "allOf": [{"$ref": "#/components/schemas/Policy"}, {"type": "object", "properties": {"target": {"type": "string"}}}]
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "poly", "version": "1"},
        "paths": {
            "/policies": {
                "post": {
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Policy"}}}},
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Item"}}}}
                    },
                }
            }
        },
        "components": {"schemas": schemas},
    }


def _changes(old, new):
    result = spec_diff.diff_specs(old, new)
    return [c for entry in result["changed_operations"] for c in entry["changes"]]


def test_discriminator_subtype_fields_are_flattened():
    body = spec_diff.extract_operations(_poly_spec())["POST /policies"]["body"]
    assert "[A_RECORD].ipv4Address" in body
    assert body["type"]["enum"] == ["A_RECORD"]


def test_discriminator_subtype_field_added_is_reported():
    changes = _changes(_poly_spec(), _poly_spec(extra_field=True))
    assert any("[A_RECORD].ttl" in c and "added" in c for c in changes)


def test_discriminator_new_variant_is_reported():
    changes = _changes(_poly_spec(), _poly_spec(new_variant=True))
    assert any("enum added: HTTPS_RECORD" in c for c in changes)
    assert any("[HTTPS_RECORD].target" in c for c in changes)


def test_response_field_rename_is_reported():
    changes = _changes(_poly_spec(), _poly_spec(response_field="refs"))
    assert any(c.startswith("response removed `ipv4Address`") for c in changes)
    assert any(c.startswith("response added `refs`") for c in changes)


def test_limit_change_is_reported():
    changes = _changes(_poly_spec(), _poly_spec(max_len=20))
    assert any("limits maxLength=10 -> maxLength=20" in c for c in changes)


# ----------------------------------------------------------- key handling


def test_console_fetch_refuses_plain_http():
    with pytest.raises(RuntimeError, match="https"):
        spec_diff.fetch_console_network_spec("http://192.0.2.1", "k-test")


def test_console_fetch_does_not_follow_redirects():
    import urllib.request

    handler = spec_diff._NoRedirect()
    req = urllib.request.Request("https://192.0.2.1/x", headers={"X-API-Key": "k"})
    assert handler.redirect_request(req, None, 302, "Found", {}, "http://attacker.example/x") is None


def test_env_verify_ssl_parsing():
    assert spec_diff.env_verify_ssl({"UNIFI_VERIFY_SSL": "true"}) is True
    assert spec_diff.env_verify_ssl({"UNIFI_VERIFY_SSL": "0"}) is False
    assert spec_diff.env_verify_ssl({}) is False


def test_console_fetch_passes_verify_flag(monkeypatch):
    seen = {}

    def fake_get(url, headers=None, verify=True, follow_redirects=True):
        seen.update(verify=verify, follow=follow_redirects)
        return json.dumps(OLD).encode()

    monkeypatch.setattr(spec_diff, "_http_get", fake_get)
    spec_diff.fetch_console_network_spec("192.0.2.1", "k", verify=True)
    assert seen == {"verify": True, "follow": False}


def test_collect_online_rejects_unusable_console_version(monkeypatch, tmp_path):
    _vendor(tmp_path, OLD, "network", "1.0.0")
    bad = {**OLD, "info": {"title": "N", "version": "../../x"}}
    _fake_world(monkeypatch, bad, OLD)
    results, fetched = spec_diff.collect_online(tmp_path, "192.0.2.1", "k")
    network = next(r for r in results if r["service"] == "network")
    assert "unusable spec version" in network["error"]
    assert "network" not in fetched


def test_collect_tool_literals_resolves_module_constants(tmp_path):
    (tmp_path / "mod.py").write_text(
        '_ROOT = "/proxy/network/integration/v1/sites/{site_id}"\n'
        '_BASE = _ROOT + "/policies"\n'
        'async def a(c, pid):\n'
        '    return await c.get(f"{_BASE}/{pid}")\n'
        'async def b(c):\n'
        '    return await c.get(_BASE + "/ordering")\n'
        'async def d(c):\n'
        '    return await c.get(_BASE)\n'
    )
    literals = spec_coverage.collect_tool_literals(tmp_path)
    assert "/proxy/network/integration/v1/sites/{site_id}/policies/{}" in literals
    assert "/proxy/network/integration/v1/sites/{site_id}/policies/ordering" in literals
    assert "/proxy/network/integration/v1/sites/{site_id}/policies" in literals
