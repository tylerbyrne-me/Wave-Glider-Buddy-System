"""
SFMC REST API exploration probe (read-only).

Discovers auth flow and candidate endpoints, then fetches sample payloads for
checklist field mapping. Uses credentials from project-root .env:

  SFMC_BASE_URL=https://your-sfmc-host
  SFMC_CLIENT_ID=...
  SFMC_CLIENT_SECRET=...

Run from project root with WorkPython:

  conda activate WorkPython
  python exploration/sfmc/probe_sfmc.py --discover --insecure
  python exploration/sfmc/probe_sfmc.py --fetch --insecure
  python exploration/sfmc/probe_sfmc.py --fetch --glider hostglider1 --insecure
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
_DISCOVERY_LOG = Path(__file__).resolve().parent / "discovery_log.jsonl"

# NodeJS wrapper program names from Teledyne SFMC User Manual Appendix E.
_WRAPPER_PROGRAMS = (
    "get_active_deployment_details",
    "get_available_glider_scripts",
    "get_glider_folder_listing",
    "get_data_transmission_plan",
    "get_surface_plan",
    "get_waypoint_plan",
    "get_abort_plan",
    "output_glider_dialog_data",
    "output_glider_script_events",
)

_TOKEN_PATHS = (
    "/sfmc/api/signin",
    "/sfmc/api/auth/token",
    "/sfmc/api/token",
    "/api/auth/token",
    "/api/v1/auth/token",
    "/api/token",
    "/oauth/token",
    "/oauth2/token",
    "/token",
    "/rest/auth/token",
    "/rest/token",
    "/api/oauth/token",
    "/api/login",
    "/api/authenticate",
)

# Confirmed live on our instance: nginx 404 on /api/*, JSON 401 on /sfmc/api/*.
_RESOURCE_PATHS = (
    "/sfmc/api/get-active-deployment-details",
    "/sfmc/api/get-available-glider-scripts",
    "/sfmc/api/get-glider-folder-listing",
    "/sfmc/api/get-data-transmission-plan",
    "/sfmc/api/get-surface-plan",
    "/sfmc/api/get-waypoint-plan",
    "/sfmc/api/get-abort-plan",
    "/sfmc/api/deployments/active",
    "/sfmc/api/gliders",
    "/sfmc/api/version",
    "/sfmc/api/status",
    "/api/deployments/active",
    "/api/v1/deployments/active",
    "/api/active_deployments",
    "/api/active-deployments",
    "/api/glider/deployments/active",
    "/api/gliders",
    "/api/v1/gliders",
    "/api/deployments",
    "/api/v1/deployments",
    "/rest/deployments/active",
    "/rest/gliders",
    "/api/version",
    "/api/health",
    "/api/status",
    "/sfmc/version",
)

for _prog in _WRAPPER_PROGRAMS:
    _RESOURCE_PATHS += (
        f"/sfmc/api/{_prog.replace('_', '-')}",
        f"/sfmc/api/{_prog}",
    )


@dataclass
class SfmcConfig:
    base_url: str
    client_id: str
    client_secret: str
    verify_tls: bool = True
    timeout_seconds: float = 30.0


@dataclass
class ProbeResult:
    method: str
    url: str
    status_code: int
    auth_label: str
    content_type: str | None = None
    body_preview: str | None = None
    is_json: bool = False
    json_keys: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_sfmc_config() -> SfmcConfig:
    env = _load_dotenv(_project_root / ".env")
    base_url = (env.get("SFMC_BASE_URL") or "").rstrip("/")
    client_id = env.get("SFMC_CLIENT_ID") or ""
    client_secret = env.get("SFMC_CLIENT_SECRET") or ""
    missing = [
        name
        for name, val in (
            ("SFMC_BASE_URL", base_url),
            ("SFMC_CLIENT_ID", client_id),
            ("SFMC_CLIENT_SECRET", client_secret),
        )
        if not val
    ]
    if missing:
        raise SystemExit(
            f"Missing .env keys: {', '.join(missing)}. "
            "Add SFMC_BASE_URL, SFMC_CLIENT_ID, SFMC_CLIENT_SECRET to project-root .env."
        )
    return SfmcConfig(base_url=base_url, client_id=client_id, client_secret=client_secret)


def _normalize_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme:
        return f"https://{base_url.rstrip('/')}"
    return base_url.rstrip("/")


def _preview_body(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    # Never echo JWTs / access tokens in console or discovery logs.
    compact = re.sub(
        r'("(?:token|access_token|accessToken)"\s*:\s*")[^"]+(")',
        r"\1<redacted>\2",
        compact,
        flags=re.IGNORECASE,
    )
    compact = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "<redacted-jwt>",
        compact,
    )
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _parse_json_keys(text: str) -> tuple[bool, list[str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False, []
    if isinstance(payload, dict):
        return True, sorted(str(k) for k in payload.keys())
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return True, sorted(str(k) for k in payload[0].keys())
    return True, []


def _build_auth_variants(client_id: str, client_secret: str) -> list[tuple[str, dict[str, str], httpx.Auth | None]]:
    basic_token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return [
        ("basic_auth", {}, httpx.BasicAuth(client_id, client_secret)),
        ("header_authorization_basic", {"Authorization": f"Basic {basic_token}"}, None),
        ("header_apikey_colon", {"Authorization": f"ApiKey {client_id}:{client_secret}"}, None),
        ("header_x_client_id_secret", {"X-Client-Id": client_id, "X-Client-Secret": client_secret}, None),
        ("header_client_id_secret", {"Client-Id": client_id, "Client-Secret": client_secret}, None),
        ("header_sfmc_client", {"SFMC-Client-Id": client_id, "SFMC-Client-Secret": client_secret}, None),
    ]


def _token_post_bodies(client_id: str, client_secret: str) -> list[tuple[str, dict[str, Any], str]]:
    """Return (label, body, content_kind) where content_kind is json or form."""
    return [
        (
            "teledyne_signin",
            {"clientId": client_id, "secret": client_secret},
            "json",
        ),
        (
            "oauth_client_credentials",
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            "json",
        ),
        (
            "oauth_client_credentials_form",
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            "form",
        ),
        (
            "client_id_secret_json",
            {"client_id": client_id, "client_secret": client_secret},
            "json",
        ),
        (
            "client_id_secret_form",
            {"client_id": client_id, "client_secret": client_secret},
            "form",
        ),
        (
            "clientId_clientSecret_json",
            {"clientId": client_id, "clientSecret": client_secret},
            "json",
        ),
    ]


def _request_once(
    client: httpx.Client,
    *,
    method: str,
    url: str,
    auth_label: str,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
) -> ProbeResult:
    started = time.perf_counter()
    try:
        if form_body is not None:
            response = client.request(method, url, headers=headers, auth=auth, data=form_body)
        else:
            response = client.request(method, url, headers=headers, auth=auth, json=json_body)
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            method=method,
            url=url,
            status_code=-1,
            auth_label=auth_label,
            body_preview=str(exc),
            elapsed_ms=elapsed_ms,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    content_type = response.headers.get("content-type")
    text = response.text or ""
    is_json, json_keys = _parse_json_keys(text) if text.strip() else (False, [])
    return ProbeResult(
        method=method,
        url=url,
        status_code=response.status_code,
        auth_label=auth_label,
        content_type=content_type,
        body_preview=_preview_body(text),
        is_json=is_json,
        json_keys=json_keys,
        elapsed_ms=elapsed_ms,
    )


def _append_discovery_log(entry: dict[str, Any]) -> None:
    _DISCOVERY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DISCOVERY_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def _print_result(result: ProbeResult) -> None:
    status = result.status_code if result.status_code >= 0 else "ERR"
    keys = f" keys={result.json_keys[:8]}" if result.json_keys else ""
    preview = f" | {result.body_preview}" if result.body_preview else ""
    print(
        f"[{status:>4}] {result.method:4} {result.url} "
        f"({result.auth_label}, {result.elapsed_ms:.0f}ms){keys}{preview}"
    )


def _is_interesting(result: ProbeResult) -> bool:
    if result.status_code in (200, 201, 204):
        return True
    if result.status_code in (401, 403):
        return True
    if result.status_code >= 500:
        return False
    return result.status_code not in (404, 405, -1)


def discover_endpoints(config: SfmcConfig, *, max_requests: int = 120, sfmc_only: bool = False) -> list[ProbeResult]:
    base = _normalize_base_url(config.base_url)
    results: list[ProbeResult] = []
    seen_urls: set[str] = set()
    bearer_tokens: list[str] = []

    print(f"SFMC discovery against {base}")
    print(f"TLS verify={config.verify_tls}  max_requests={max_requests}\n")

    with httpx.Client(verify=config.verify_tls, timeout=config.timeout_seconds, follow_redirects=True) as client:
        auth_variants = _build_auth_variants(config.client_id, config.client_secret)
        probe_paths = list(dict.fromkeys(_RESOURCE_PATHS))
        if sfmc_only:
            probe_paths = [p for p in probe_paths if p.startswith("/sfmc/")]
        token_paths = _TOKEN_PATHS
        if sfmc_only:
            token_paths = tuple(p for p in _TOKEN_PATHS if p.startswith("/sfmc/"))

        # Phase A: token acquisition attempts
        print("=== Auth: token POST candidates ===")
        for token_path in token_paths:
            if len(results) >= max_requests:
                break
            url = urljoin(f"{base}/", token_path.lstrip("/"))
            for body_label, body, content_kind in _token_post_bodies(config.client_id, config.client_secret):
                if len(results) >= max_requests:
                    break
                for auth_label_suffix, headers, auth in [
                    ("", {}, None),
                    ("+basic", {}, httpx.BasicAuth(config.client_id, config.client_secret)),
                ]:
                    label = f"token_body:{body_label}{auth_label_suffix}"
                    result = _request_once(
                        client,
                        method="POST",
                        url=url,
                        auth_label=label,
                        headers=headers,
                        auth=auth,
                        json_body=body if content_kind == "json" else None,
                        form_body=body if content_kind == "form" else None,
                    )
                    results.append(result)
                    _print_result(result)
                    _append_discovery_log({"phase": "token_post", **result.__dict__})
                    if result.is_json and result.status_code in (200, 201):
                        full = client.post(
                            url,
                            headers=headers,
                            auth=auth,
                            json=body if content_kind == "json" else None,
                            data=body if content_kind == "form" else None,
                        )
                        try:
                            payload = full.json()
                        except json.JSONDecodeError:
                            payload = {}
                        token = (
                            payload.get("access_token")
                            or payload.get("token")
                            or payload.get("accessToken")
                        )
                        if isinstance(token, str) and token:
                            bearer_tokens.append(token)

        # Phase B: GET with auth header variants (no pre-token)
        print("\n=== Auth: GET resource candidates (direct credentials) ===")
        for path in probe_paths:
            if len(results) >= max_requests:
                break
            url = urljoin(f"{base}/", path.lstrip("/"))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            for auth_label, headers, auth in auth_variants:
                if len(results) >= max_requests:
                    break
                result = _request_once(
                    client,
                    method="GET",
                    url=url,
                    auth_label=auth_label,
                    headers=headers,
                    auth=auth,
                )
                if not _is_interesting(result):
                    continue
                results.append(result)
                _print_result(result)
                _append_discovery_log({"phase": "resource_get", **result.__dict__})

        # Phase B2: POST RPC-style (wrapper programs may POST JSON bodies)
        print("\n=== Auth: POST resource candidates (RPC-style) ===")
        rpc_paths = [p for p in probe_paths if "get-" in p or "get_" in p][:8]
        rpc_body = {
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
        for path in rpc_paths:
            if len(results) >= max_requests:
                break
            url = urljoin(f"{base}/", path.lstrip("/"))
            for auth_label, headers, auth in auth_variants[:3]:
                if len(results) >= max_requests:
                    break
                result = _request_once(
                    client,
                    method="POST",
                    url=url,
                    auth_label=f"post_rpc:{auth_label}",
                    headers=headers,
                    auth=auth,
                    json_body=rpc_body,
                )
                if not _is_interesting(result):
                    continue
                results.append(result)
                _print_result(result)
                _append_discovery_log({"phase": "resource_post", **result.__dict__})

        # Phase C: GET with bearer tokens from Phase A
        if bearer_tokens:
            print("\n=== Auth: GET with bearer token(s) from token POST ===")
            for token in bearer_tokens[:3]:
                headers = {"Authorization": f"Bearer {token}"}
                for path in probe_paths[:20]:
                    if len(results) >= max_requests:
                        break
                    url = urljoin(f"{base}/", path.lstrip("/"))
                    result = _request_once(
                        client,
                        method="GET",
                        url=url,
                        auth_label="bearer_from_token_post",
                        headers=headers,
                    )
                    if not _is_interesting(result):
                        continue
                    results.append(result)
                    _print_result(result)
                    _append_discovery_log({"phase": "resource_get_bearer", **result.__dict__})

    successes = [r for r in results if r.status_code in (200, 201)]
    auth_gates = [r for r in results if r.status_code in (401, 403)]
    print(f"\nDiscovery summary: {len(results)} logged, {len(successes)} success, {len(auth_gates)} auth-gated")
    if successes:
        print("Successful endpoints:")
        for r in successes:
            print(f"  - {r.method} {r.url} ({r.auth_label})")
    else:
        print("No 200/201 responses yet — see README fallbacks (DevTools / sfmc.tgz).")
    return results


def _save_sample(name: str, payload: Any) -> Path:
    _SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = _SAMPLES_DIR / f"{stamp}_{name}.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote sample: {path.relative_to(_project_root)}")
    return path


def fetch_samples(
    config: SfmcConfig,
    *,
    glider_name: str | None = None,
    discovery_results: list[ProbeResult] | None = None,
) -> None:
    base = _normalize_base_url(config.base_url)
    auth_variants = _build_auth_variants(config.client_id, config.client_secret)

    # Prefer URLs that succeeded in discovery; else fall back to common paths.
    success_urls: list[str] = []
    if discovery_results:
        success_urls = [r.url for r in discovery_results if r.status_code in (200, 201)]
    if not success_urls and _DISCOVERY_LOG.is_file():
        for line in _DISCOVERY_LOG.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("status_code") in (200, 201) and entry.get("url"):
                success_urls.append(str(entry["url"]))

    candidate_urls = success_urls or [
        urljoin(f"{base}/", p.lstrip("/"))
        for p in (
            "/sfmc/api/get-active-deployment-details",
            "/sfmc/api/get-available-glider-scripts",
            "/sfmc/api/get-glider-folder-listing",
            "/sfmc/api/get-surface-plan",
            "/sfmc/api/get-waypoint-plan",
            "/sfmc/api/deployments/active",
            "/sfmc/api/gliders",
        )
    ]

    print(f"SFMC fetch against {base}")
    fetched: dict[str, Any] = {"fetched_at_utc": datetime.now(UTC).isoformat(), "responses": {}}

    with httpx.Client(verify=config.verify_tls, timeout=config.timeout_seconds, follow_redirects=True) as client:
        bearer_token: str | None = None
        for token_path in ("/sfmc/api/auth/token", "/sfmc/api/token"):
            url = urljoin(f"{base}/", token_path.lstrip("/"))
            for _, body, content_kind in _token_post_bodies(config.client_id, config.client_secret):
                result = _request_once(
                    client,
                    method="POST",
                    url=url,
                    auth_label="token_post",
                    auth=httpx.BasicAuth(config.client_id, config.client_secret),
                    json_body=body if content_kind == "json" else None,
                    form_body=body if content_kind == "form" else None,
                )
                if result.status_code in (200, 201) and result.is_json:
                    try:
                        payload = json.loads(result.body_preview or "{}")
                    except json.JSONDecodeError:
                        payload = {}
                    token = payload.get("access_token") or payload.get("token")
                    if isinstance(token, str) and token:
                        bearer_token = token
                        _save_sample("auth_token", payload)
                        break
            if bearer_token:
                break

        auth_attempts: list[tuple[str, dict[str, str], httpx.Auth | None]] = []
        if bearer_token:
            auth_attempts.append(("bearer", {"Authorization": f"Bearer {bearer_token}"}, None))
        auth_attempts.extend(auth_variants)

        for url in candidate_urls[:12]:
            for auth_label, headers, auth in auth_attempts:
                if auth_label == "basic_auth":
                    auth = httpx.BasicAuth(config.client_id, config.client_secret)
                if auth_label == "header_authorization_basic":
                    token = base64.b64encode(
                        f"{config.client_id}:{config.client_secret}".encode()
                    ).decode()
                    headers = {"Authorization": f"Basic {token}"}

                result = _request_once(
                    client,
                    method="GET",
                    url=url,
                    auth_label=auth_label,
                    headers=headers,
                    auth=auth,
                )
                if result.status_code not in (200, 201) or not result.is_json:
                    continue

                response = client.get(url, headers=headers, auth=auth)
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    continue

                slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", urlparse(url).path.strip("/")) or "root"
                _save_sample(slug, payload)
                fetched["responses"][url] = {
                    "auth_label": auth_label,
                    "top_level_type": type(payload).__name__,
                    "keys": sorted(payload.keys()) if isinstance(payload, dict) else None,
                }
                break

        if glider_name:
            glider_paths = [
                f"/sfmc/api/get-glider-folder-listing?glider={glider_name}",
                f"/sfmc/api/get-available-glider-scripts?glider={glider_name}",
                f"/sfmc/api/gliders/{glider_name}/folder-listing",
                f"/sfmc/api/gliders/{glider_name}/scripts",
            ]
            for path in glider_paths:
                url = urljoin(f"{base}/", path.lstrip("/"))
                for auth_label, headers, auth in auth_attempts:
                    if auth_label == "basic_auth":
                        auth = httpx.BasicAuth(config.client_id, config.client_secret)
                    response = client.get(url, headers=headers, auth=auth)
                    if response.status_code not in (200, 201):
                        continue
                    try:
                        payload = response.json()
                    except json.JSONDecodeError:
                        continue
                    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", path.strip("/"))
                    _save_sample(slug, payload)
                    fetched["responses"][url] = {"auth_label": auth_label}
                    break

    summary_path = _save_sample("fetch_summary", fetched)
    print(f"Fetch summary: {summary_path}")


def v1_smoke(config: SfmcConfig, *, glider_name: str) -> None:
    """
    Teledyne-documented auth + read endpoints (from sfmc Node package).

    POST /sfmc/api/signin {clientId, secret} → Bearer token
    GET  /sfmc/api/v1/active-deployment/{glider}
    GET  /sfmc/api/v1/scripts-for-glider/{glider}
    GET  /sfmc/api/v1/glider-folder-file-listing/{glider}/archive?filter=*_goto_*.ma
    """
    base = _normalize_base_url(config.base_url)
    print(f"SFMC v1 smoke against {base} glider={glider_name}")
    print(f"TLS verify={config.verify_tls}\n")

    with httpx.Client(verify=config.verify_tls, timeout=config.timeout_seconds, follow_redirects=True) as client:
        signin_url = f"{base}/sfmc/api/signin"
        body = {"clientId": config.client_id, "secret": config.client_secret}
        result = _request_once(
            client,
            method="POST",
            url=signin_url,
            auth_label="teledyne_signin",
            json_body=body,
        )
        _print_result(result)
        _append_discovery_log({"phase": "v1_smoke_signin", **result.__dict__})
        if result.status_code not in (200, 201):
            print("Signin failed — check SFMC_CLIENT_ID / SFMC_CLIENT_SECRET and host.")
            return

        full = client.post(signin_url, json=body)
        try:
            token_payload = full.json()
        except json.JSONDecodeError:
            print("Signin returned non-JSON")
            return
        # Never dump full token to console; only confirm presence.
        token = token_payload.get("token") or token_payload.get("access_token")
        if not token:
            print(f"Signin OK but no token field; keys={sorted(token_payload.keys())}")
            _save_sample("signin_keys_only", {"keys": sorted(token_payload.keys())})
            return
        print(f"Signin OK (token length={len(str(token))})")
        headers = {"Authorization": f"Bearer {token}"}

        paths = [
            f"/sfmc/api/v1/active-deployment/{glider_name}",
            f"/sfmc/api/v1/scripts-for-glider/{glider_name}",
            f"/sfmc/api/v1/newest-mission-details/{glider_name}",
            f"/sfmc/api/v1/glider-folder-file-listing/{glider_name}/archive",
            f"/sfmc/api/v1/glider-folder-file-listing/{glider_name}/from-glider",
        ]
        for path in paths:
            url = f"{base}{path}"
            params = None
            if "folder-file-listing" in path and path.endswith("/archive"):
                params = {"page": 0, "filter": "*_goto_*.ma"}
            elif "folder-file-listing" in path:
                params = {"page": 0, "filter": "*"}
            response = client.get(url, headers=headers, params=params)
            preview = _preview_body(response.text or "")
            print(f"[{response.status_code:>4}] GET  {url} | {preview}")
            _append_discovery_log(
                {
                    "phase": "v1_smoke_get",
                    "method": "GET",
                    "url": url,
                    "status_code": response.status_code,
                    "auth_label": "bearer",
                    "body_preview": preview,
                }
            )
            if response.status_code == 200:
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    continue
                slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", path.strip("/"))
                _save_sample(slug, payload)

        # Glider id + optional network log tail (glider-requests; may need Bearer or session).
        details_url = f"{base}/sfmc/api/v1/gliders/{glider_name}"
        details_resp = client.get(details_url, headers=headers)
        print(f"[{details_resp.status_code:>4}] GET  {details_url} | {_preview_body(details_resp.text or '')}")
        glider_id = None
        log_name = None
        if details_resp.status_code == 200:
            try:
                details = details_resp.json()
            except json.JSONDecodeError:
                details = None
            if isinstance(details, dict):
                _save_sample(f"v1_gliders_{glider_name}", details)
                data = details.get("data") if isinstance(details.get("data"), dict) else details
                if isinstance(data, dict) and data.get("id") is not None:
                    try:
                        glider_id = int(data["id"])
                    except (TypeError, ValueError):
                        glider_id = None

        deploy_url = f"{base}/sfmc/api/v1/active-deployment/{glider_name}"
        deploy_resp = client.get(deploy_url, headers=headers)
        if deploy_resp.status_code == 200:
            try:
                deploy = deploy_resp.json()
            except json.JSONDecodeError:
                deploy = None
            if isinstance(deploy, dict):
                # Prefer newest logFilePath under connections
                stamps: list[tuple[str, str]] = []
                stack = [deploy]
                while stack:
                    cur = stack.pop()
                    if isinstance(cur, dict):
                        for k, v in cur.items():
                            if str(k).lower() in ("logfilepath", "logfile", "logfilename") and v:
                                name = str(v).replace("\\", "/").rsplit("/", 1)[-1]
                                m = re.search(r"(\d{8}T\d{6})", name)
                                if m and "_network_net_" in name.lower():
                                    stamps.append((m.group(1), name))
                            else:
                                stack.append(v)
                    elif isinstance(cur, list):
                        stack.extend(cur)
                if stamps:
                    stamps.sort(key=lambda item: item[0], reverse=True)
                    log_name = stamps[0][1]

        if glider_id is not None and log_name:
            log_url = (
                f"{base}/sfmc/glider-requests/get-last-x-bytes-of-glider-log-file/"
                f"{glider_id}/{log_name}/8000"
            )
            log_resp = client.get(log_url, headers=headers)
            preview = _preview_body(log_resp.text or "")
            print(f"[{log_resp.status_code:>4}] GET  {log_url} | {preview}")
            _append_discovery_log(
                {
                    "phase": "v1_smoke_log_tail",
                    "method": "GET",
                    "url": log_url,
                    "status_code": log_resp.status_code,
                    "auth_label": "bearer",
                    "body_preview": preview,
                }
            )
            if log_resp.status_code == 200:
                try:
                    log_payload = log_resp.json()
                except json.JSONDecodeError:
                    log_payload = None
                if isinstance(log_payload, dict):
                    # Redact bulky dialog; store metadata + length only
                    data = log_payload.get("data")
                    _save_sample(
                        f"log_tail_{glider_name}",
                        {
                            "success": log_payload.get("success"),
                            "startPosition": log_payload.get("startPosition"),
                            "endPosition": log_payload.get("endPosition"),
                            "logFileName": log_name,
                            "gliderId": glider_id,
                            "data_chars": len(data) if isinstance(data, str) else None,
                            "data_has_devices_tms": (
                                isinstance(data, str) and "devices:(t/m/s)" in data
                            ),
                        },
                    )
        elif glider_id is not None:
            print(f"Log tail skipped: gliderId={glider_id} but no network logFilePath found")
        else:
            print("Log tail skipped: could not resolve glider id")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Teledyne SFMC REST API (read-only).")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Try auth patterns and candidate endpoint paths; append discovery_log.jsonl",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch JSON samples from best-known endpoints into exploration/sfmc/samples/",
    )
    parser.add_argument(
        "--v1-smoke",
        action="store_true",
        help="Teledyne signin + /sfmc/api/v1 read endpoints (requires --glider)",
    )
    parser.add_argument(
        "--glider",
        default=None,
        help="SFMC glider name (e.g. peggy) for --v1-smoke / --fetch",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (common for self-signed SFMC certs)",
    )
    parser.add_argument(
        "--sfmc-only",
        action="store_true",
        help="Limit discovery to /sfmc/api/* paths (recommended after initial scan)",
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=120,
        help="Cap discovery requests (default: 120)",
    )
    args = parser.parse_args()

    if not args.discover and not args.fetch and not args.v1_smoke:
        args.v1_smoke = True

    config = load_sfmc_config()
    config.verify_tls = not args.insecure

    if args.v1_smoke:
        v1_smoke(config, glider_name=args.glider or "peggy")

    discovery_results: list[ProbeResult] = []
    if args.discover:
        discovery_results = discover_endpoints(
            config, max_requests=args.max_requests, sfmc_only=args.sfmc_only
        )
    if args.fetch:
        fetch_samples(config, glider_name=args.glider, discovery_results=discovery_results)


if __name__ == "__main__":
    main()
