#!/usr/bin/env python3
"""Post-deploy smoke test gating traffic promotion in cloudbuild.yaml.

Runs against a --no-traffic, --tag'd candidate revision's own URL, before
cloudbuild.yaml promotes it to serve real traffic. Deliberately lightweight
and stdlib-only (no pip install step, no credentials) — it exists to catch a
revision that passes Cloud Run's startup probe but is otherwise broken (e.g.
a bad env var wired to a working /api/health but a broken read path), not to
exercise write paths or IAM. See smoke_test_image_pipeline.py for the
heavier, credentialed, manually-run check that covers uploads.

    python scripts/smoke_test_deploy.py --url https://candidate-abc123---mfs-backend-xyz.a.run.app
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


class SmokeTestFailure(Exception):
    pass


def _get(url: str, timeout: float = 15.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310 - url is always this script's own --url/base argument (a Cloud Run revision URL Cloud Build constructs), never external input
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _get_tolerating_cold_start(url: str, attempts: int = 4, timeout: float = 20.0) -> tuple[int, bytes]:
    """Like _get, but retries through a cold start.

    A --no-traffic candidate revision scales back to zero the moment it
    finishes passing Cloud Run's own startup probe — nothing routes real
    traffic to it to keep it warm — so this script's own first request is
    what wakes the instance again. Found live: the promotion pipeline's
    first real run timed out here (15s default) against an instance that
    had gone cold mere seconds after booting successfully. Only the first
    call needs this; by the time it returns, the instance is warm for the
    checks that follow.
    """
    last_exc: BaseException = TimeoutError("no attempts made")
    for attempt in range(1, attempts + 1):
        try:
            return _get(url, timeout=timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < attempts:
                print(f"  (cold start? attempt {attempt}/{attempts} failed: {exc} — retrying)")
                time.sleep(5)
    raise last_exc


def _post_json(url: str, payload: dict, timeout: float = 15.0) -> tuple[int, bytes, dict]:
    """Like _get, but a POST with a JSON body, returning response headers
    too — the MCP auth-challenge check below needs to read
    WWW-Authenticate, which no other check in this script has needed."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - url is always this script's own --url argument
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


_MCP_INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "smoke-test", "version": "0"},
    },
}


def _check_mcp_requires_auth(base: str) -> None:
    """S9: a bare POST /mcp (no bearer token) must be rejected with a 401
    whose WWW-Authenticate challenge points at the protected-resource
    metadata endpoint — the OAuth discovery step every real MCP client
    depends on to find WorkOS AuthKit (see docs/DEPLOYMENT.md's MCP token
    binding section). Factored out of run() as its own function, the same
    reason _get_tolerating_cold_start is: so this exact assertion can be
    unit-tested (test_smoke_test_deploy.py) without a live Cloud Run
    revision, by patching _post_json the way existing tests patch _get."""
    status, _, headers = _post_json(f"{base}/mcp", _MCP_INITIALIZE_BODY)
    _check("POST /mcp without a token returns 401", status == 401, f"HTTP {status}")
    www_authenticate = headers.get("WWW-Authenticate", "")
    _check(
        "401 challenge points at protected-resource metadata",
        "resource_metadata" in www_authenticate,
        f"WWW-Authenticate: {www_authenticate!r}",
    )


def _check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        raise SmokeTestFailure(f"{label}: {detail}")


def run(args: argparse.Namespace) -> int:
    base = args.url.rstrip("/")
    print(f"Target: {base}")

    try:
        print("\n[1] Health check")
        status, body = _get_tolerating_cold_start(f"{base}/api/health")
        _check("GET /api/health returns 200", status == 200, f"HTTP {status}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        _check("body is JSON with status=ok", isinstance(payload, dict) and payload.get("status") == "ok", f"got {body!r}")

        print("\n[2] Public recipes list")
        status, body = _get(f"{base}/api/recipes")
        _check("GET /api/recipes returns 200", status == 200, f"HTTP {status}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        _check("body is valid JSON", payload is not None, f"got {body!r}")

        print("\n[3] Public categories list")
        status, body = _get(f"{base}/api/categories")
        _check("GET /api/categories returns 200", status == 200, f"HTTP {status}")

        print("\n[4] MCP endpoint requires auth")
        _check_mcp_requires_auth(base)

        print("\nAll checks passed.")
        return 0

    except SmokeTestFailure as exc:
        print(f"\nSMOKE TEST FAILED: {exc}")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"\nSMOKE TEST FAILED: could not reach {base}: {exc}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="Candidate revision URL (the --tag'd, --no-traffic one)")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
