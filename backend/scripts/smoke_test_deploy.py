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
