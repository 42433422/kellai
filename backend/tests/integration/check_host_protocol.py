"""Opt-in cross-checkout HTTP/ASGI contract test with real host SQL sessions.

Run this script using the explicitly selected host Python environment. See the
repository README for invocation. It is intentionally not collected by pytest
and never clones, fetches, updates, or installs either project's dependencies.
The only credential backend fixture replaces native OS keyring I/O; the
production native backend selector, routers, and session resolver remain active.
"""
from __future__ import annotations

import argparse
import base64
from datetime import timedelta
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    host_default = os.environ.get("KELLAI_TEST_HOST_CHECKOUT")
    parser.add_argument("--host-checkout", type=Path, default=host_default, required=not host_default,
                        help="Explicit XCMAX git checkout containing FHD/ (or KELLAI_TEST_HOST_CHECKOUT)")
    backend = Path(__file__).resolve().parents[2]
    python_name = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    parser.add_argument("--tool-python", type=Path,
                        default=os.environ.get("KELLAI_TEST_TOOL_PYTHON") or backend / ".venv" / python_name,
                        help="Prepared Kellai Python environment; defaults to backend/.venv")
    parser.add_argument("--expected-host-revision", default=os.environ.get("KELLAI_TEST_HOST_REVISION"),
                        help="Require this exact 40-character host commit; never resolves a remote branch")
    parser.add_argument("--allow-dirty-host", action="store_true",
                        help="Explicitly permit development changes; result records host_dirty=true")
    options = parser.parse_args(argv)
    options.host_checkout = options.host_checkout.expanduser().resolve()
    # Preserve a virtualenv's symlink path: resolving it to the base interpreter
    # would discard pyvenv.cfg and import a different dependency environment.
    options.tool_python = options.tool_python.expanduser().absolute()
    if not (options.host_checkout / "FHD/app/fastapi_routes/kellai_binding.py").is_file():
        parser.error("--host-checkout must contain the XCMAX FHD account-tool integration")
    if not options.tool_python.is_file():
        parser.error("--tool-python must point to an already prepared Kellai interpreter")
    if options.expected_host_revision and not re.fullmatch(r"[0-9a-fA-F]{40}", options.expected_host_revision):
        parser.error("--expected-host-revision must be a full 40-character commit SHA")
    try:
        revision = subprocess.check_output(["git", "-C", str(options.host_checkout), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(options.host_checkout), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        parser.error("Unable to inspect the explicit host git checkout")
    if options.expected_host_revision and revision != options.expected_host_revision.lower():
        parser.error("The host checkout does not match --expected-host-revision")
    if dirty and not options.allow_dirty_host:
        parser.error("Host checkout has tracked changes; use a clean pinned checkout or explicitly --allow-dirty-host")
    return options, backend, revision, dirty


def main(argv=None):
    options, TOOL, revision, dirty = parse_args(argv)
    HOST = options.host_checkout / "FHD"
    RUNTIME = Path(tempfile.mkdtemp(prefix="kellai-real-protocol-"))
    os.environ.update(
        DATABASE_URL=f"sqlite:///{RUNTIME / 'host.sqlite'}",
        VECTOR_DB_URL=f"sqlite:///{RUNTIME / 'host.sqlite'}",
        XCAGI_DATA_DIR=str(RUNTIME / "host-data"),
        XCAGI_DESKTOP_MODE="0",
        SECRET_KEY=secrets.token_hex(32),
        FHD_INTENT_SEMANTIC_ENABLED="0",
    )
    sys.path.insert(0, str(HOST))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    import httpx
    import keyring
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import db as host_db
    from app.db import session as db_session
    from app.db.db_base import Base
    from app.db.models.user import User, Session as UserSession
    from app.domain.shared_services.session_service import SessionService
    from app.application.facades import session_facade
    from app.domain.shared_services import kellai_binding_store
    from app.fastapi_routes import kellai_binding
    from app.infrastructure import kellai_client
    from app.utils.time import utc_now_naive


    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]


    vault_values = {}


    class NativeKeyringIOFixture:
        __module__ = "keyring.backends.SecretService"
        priority = 1

        def set_password(self, service, name, value):
            vault_values[(service, name)] = value

        def get_password(self, service, name):
            return vault_values.get((service, name))

        def delete_password(self, service, name):
            vault_values.pop((service, name), None)


    native = NativeKeyringIOFixture()
    keyring.get_keyring = lambda: native
    binding_path = RUNTIME / "kellai-binding.json"
    kellai_binding_store._store_path = lambda: binding_path
    engine = create_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    host_db.HostSessionLocal = factory
    db_session.SessionLocal = factory
    session_facade.get_session_service = SessionService
    sid, other_sid = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with factory.begin() as database:
        database.add_all([
            User(id=7, username="owner", password="not-used", tenant_id=7, role="user", tier="enterprise"),
            User(id=8, username="other", password="not-used", tenant_id=8, role="user", tier="enterprise"),
        ])
        database.flush()
        for user_id, session_id in ((7, sid), (8, other_sid)):
            database.add(UserSession(session_id=session_id, user_id=user_id,
                                    expires_at=utc_now_naive() + timedelta(hours=1),
                                    account_kind="enterprise", market_is_admin=False,
                                    market_is_enterprise=True))

    host_port, tool_port = free_port(), free_port()
    host_url, tool_url = f"http://127.0.0.1:{host_port}", f"http://127.0.0.1:{tool_port}"
    kellai_client._BASE = tool_url + "/api/kellai/integrations/xcmax/"
    host_app = FastAPI()
    host_app.include_router(kellai_binding.router)
    host_server = uvicorn.Server(uvicorn.Config(host_app, host="127.0.0.1", port=host_port,
                                              log_level="warning", access_log=False))
    host_thread = threading.Thread(target=host_server.run, daemon=True)
    host_thread.start()
    tool_env = {**{key: value for key, value in os.environ.items() if not key.startswith("KELLAI_")},
                "PYTHONPATH": str(TOOL), "KELLAI_DATA_DIR": str(RUNTIME / "tool-data"),
                "KELLAI_WORKSPACE_ID": "1", "KELLAI_XCMAX_API_BASE": host_url,
                "KELLAI_VAULT_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode()}
    tool_log = (RUNTIME / "tool.log").open("w")
    tool_process = subprocess.Popen(
        [str(options.tool_python), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(tool_port), "--log-level", "warning"], cwd=TOOL, env=tool_env,
        stdout=tool_log, stderr=subprocess.STDOUT,
    )
    checks = []


    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)


    def expect(response, code, label):
        check(response.status_code == code, f"{label}: HTTP {code} (observed {response.status_code})")
        return response.json()


    def wait_ready(client):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if host_server.started and client.get(tool_url + "/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            if tool_process.poll() is not None:
                raise AssertionError("tool server exited before readiness")
            time.sleep(0.05)
        raise AssertionError("local servers did not become ready")


    try:
        with httpx.Client(trust_env=False, timeout=10) as client:
            wait_ready(client)
            hp = host_url + "/api/kellai/binding"
            tp = tool_url + "/api/kellai"
            pair = {"X-Kellai-Local-Pairing": "1"}
            host_headers = {**pair, "X-XCMAX-Client-Shell": "enterprise", "X-Session-ID": sid}
            other_headers = {**host_headers, "X-Session-ID": other_sid}
            expect(client.post(hp + "/start", headers={**pair, "X-XCMAX-Client-Shell": "enterprise"}),
                   400, "real sid is required before pairing")
            start = expect(client.post(hp + "/start", headers=host_headers, json={
                "requested_scopes": ["channels.read", "messages.read", "messages.send"]}), 200, "authenticated host starts pairing")["data"]
            check("authorization_secret" not in json.dumps(start), "host start does not expose handoff secret")
            login_response = client.post(tp + "/auth/xcmax-desktop", headers={"X-Kellai-Desktop-Handoff": "1"})
            login = expect(login_response, 200, "tool consumes host handoff over actual HTTP")
            operator_headers = {"Authorization": "Bearer " + login["access_token"]}
            expect(client.post(hp + "/handoff", headers=pair), 409, "host handoff cannot be claimed twice")
            expect(client.get(hp + "/status", headers=other_headers), 403, "another real sid cannot read pending pairing")
            pending_response = client.get(tp + "/integrations/xcmax/pending", headers=operator_headers)
            pending = expect(pending_response, 200, "tool reads claimed pending metadata without host sid")["data"]
            check(pending["request_id"] == start["request_id"], "pending request stays identical across processes")
            check([scope["id"] for scope in pending["requested_scopes"]] ==
                  ["channels.read", "messages.read", "messages.send"], "pending contains actual requested scope objects")
            check("authorization_secret" not in pending_response.text, "pending metadata does not expose secret")
            approved_response = client.post(tp + "/integrations/xcmax/approve", headers=operator_headers,
                json={"request_id": pending["request_id"], "accepted_scopes": ["channels.read"]})
            approved = expect(approved_response, 200, "tool approves least privilege subset over actual HTTP")["data"]
            check(approved["authorized_scopes"] == ["channels.read"], "host records only consented scope")
            stored = json.loads(binding_path.read_text())
            check(stored["connection"]["xcmax_user_id"] == 7 and stored["connection"]["xcmax_tenant_id"] == "7",
                  "real sid owner and tenant are persisted in binding")
            check("access_token" not in stored["connection"] and stored["connection"].get("access_token_ref"),
                  "host binding contains OS key reference only")
            grant_token = native.get_password(kellai_binding_store._KEYRING_SERVICE,
                                             stored["connection"]["access_token_ref"])
            check(grant_token and grant_token not in binding_path.read_text(), "raw grant token is absent from binding JSON")
            check(grant_token not in approved_response.text and grant_token not in login_response.text,
                  "approval and operator response do not expose host grant token")
            tool_binding = RUNTIME / "tool-data/tenants/1/integrations/xcmax.json"
            check(grant_token not in tool_binding.read_text(), "tool keeps grant verification hash only")
            expect(client.post(tp + "/accounts", headers=operator_headers, json={
                "channel_type": "oauth2", "auth_type": "oauth2", "name": "Read-only credential account",
                "config": {"provider": "github", "client_id": "integration-fixture", "client_secret": "fixture-secret"}}),
                200, "operator creates an encrypted credential account")
            channels_response = client.get(hp + "/channels", headers=host_headers)
            channels = expect(channels_response, 200, "host reads granted account metadata through tool gateway")["data"]["channels"]
            check(len(channels) == 1 and channels[0]["channel_type"] == "oauth2", "account connection identity crosses both routes")
            check(not channels[0]["capabilities"]["send"] and not channels[0]["capabilities"]["receive"],
                  "credential-only OAuth account never reports messaging capabilities")
            check("fixture-secret" not in channels_response.text and grant_token not in channels_response.text,
                  "host-visible account metadata contains no account or grant secret")
            expect(client.get(hp + "/contacts", headers=host_headers), 403, "ungranted messages.read is denied")
            expect(client.get(hp + "/channels", headers=other_headers), 403, "another real sid cannot use grant")
            state = expect(client.get(hp + "/status", headers=host_headers), 200, "host verifies live grant status")["data"]
            check(state["state"] == "connected", "host status reports active grant as connected")
            pair_bearer = {"Authorization": "Bearer " + grant_token}
            expect(client.get(tp + "/integrations/xcmax/grant-status", headers=pair_bearer), 200,
                   "pair bearer has distinct scope-independent grant status route")
            revoked = expect(client.post(tp + "/integrations/xcmax/disconnect", headers=operator_headers), 200,
                             "tool revokes local grant without impersonating host sid")["data"]
            check(revoked.get("local_grant_revoked") is True and revoked.get("host_metadata_cleared") is False,
                  "tool accurately reports local revocation and remaining host cleanup")
            expect(client.get(tp + "/integrations/xcmax/grant-status", headers=pair_bearer), 401,
                   "old bearer stops authorizing immediately after tool revocation")
            revoked_read = expect(client.get(hp + "/channels", headers=host_headers), 401,
                                  "ordinary host read observes tool revocation before status probe")
            check(revoked_read.get("detail", {}).get("code") == "xcmax_grant_revoked",
                  "host read preserves the explicit grant revocation code")
            state = expect(client.get(hp + "/status", headers=host_headers), 200,
                           "host status preserves observed tool revocation")["data"]
            check(state["state"] in {"revoked", "requires_reconnect"}, "host does not show revoked grant as connected")
            expect(client.post(hp + "/disconnect", headers=host_headers), 200, "authenticated host cleans binding metadata")
            check(json.loads(binding_path.read_text())["connection"] is None, "host cleanup removes binding reference")
            check(not vault_values, "consumed handoff and revoked grant references are cleaned from keyring fixture")
            expect(client.get(hp + "/channels", headers=host_headers), 409, "cleaned host binding cannot read accounts")
        result = {"passed": len(checks), "checks": checks,
                          "runtime": str(RUNTIME), "host_checkout": str(options.host_checkout),
                          "host_revision": revision, "host_dirty": bool(dirty),
                          "host_python": sys.executable, "tool_python": str(options.tool_python),
                          "os_keyring": "I/O fixture; real selector retained",
                          "session_auth": "real SQLite User/Session and production resolver",
                          "transport": "two real loopback HTTP servers, production ASGI routers"}
        (RUNTIME / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        host_server.should_exit = True
        tool_process.terminate()
        try:
            tool_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tool_process.kill()
            tool_process.wait(timeout=5)
        host_thread.join(timeout=5)
        tool_log.close()
        engine.dispose()


if __name__ == "__main__":
    main()
