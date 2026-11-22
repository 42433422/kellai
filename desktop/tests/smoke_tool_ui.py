"""Real local tool UI with isolated host, inbox and receipt fixtures; no provider traffic."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.fernet import Fernet
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATE = {"claimed": False, "connected": False, "token": ""}
PENDING = {
    "request_id": "local-ui-smoke",
    "authorization_secret": "isolated-fixture-handoff-secret-12345678901234567890",
    "protocol_version": 2,
    "requested_scopes": [
        {"id": scope, "label": scope, "description": "fixture"}
        for scope in ["channels.read", "messages.read", "messages.send"]
    ],
    "expires_at": "2099-01-01T00:00:00Z",
}


class Host(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"success": True, "data": data}).encode())

    def do_GET(self):
        assert self.path == "/api/kellai/binding/status"
        self.respond({"state": "connected" if STATE["connected"] else "pending",
                      "pending": None if STATE["connected"] else PENDING})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or "{}")
        if self.path.endswith("/handoff"):
            assert not STATE["claimed"]
            STATE["claimed"] = True
            self.respond(PENDING)
        elif self.path.endswith("/approve"):
            assert body["authorization_secret"] == PENDING["authorization_secret"]
            assert set(body["accepted_scopes"]) == {"channels.read", "messages.read"}
            STATE.update(connected=True, token=body["access_token"])
            self.respond({"state": "connected"})
        else:
            raise AssertionError(self.path)


def seed(env, source):
    result = subprocess.run([sys.executable, "-c", source], cwd=ROOT / "backend",
                            env=env, check=True, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def stop(process):
    if process.poll() is None:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=10)


def sync_account(page, name, expected):
    page.get_by_label("选择账号", exact=True).select_option(label=name + " · telegram")
    expect(page.locator(".contact")).to_have_count(1)
    with page.expect_response(lambda response: response.url.endswith("/channels/sync-inbox")) as pending:
        page.get_by_role("button", name="同步消息", exact=True).click()
    response = pending.value
    assert response.status == 200, response.text()
    assert response.json()["data"]["synced"] == expected, response.text()


def exercise(page, env):
    page.goto("http://127.0.0.1:1420")
    page.get_by_role("button", name="接收连接请求", exact=True).click()
    expect(page.get_by_role("heading", name="待确认的连接请求")).to_be_visible()
    expect(page.get_by_role("checkbox")).to_have_count(3)
    page.get_by_role("checkbox").nth(0).check()
    page.get_by_role("checkbox").nth(1).check()
    page.get_by_role("button", name="授权连接", exact=True).click()
    expect(page.get_by_role("heading", name="已授权 XCMAX")).to_be_visible()
    expect(page.locator(".scope-list li")).to_have_count(2)
    page.get_by_role("button", name="账号连接", exact=True).click()
    for name in ["渠道账号 A", "渠道账号 B"]:
        page.get_by_role("button", name="添加账号", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("平台", exact=True).select_option("telegram")
        dialog.locator("#root_name").fill(name)
        token = dialog.locator("#root_config_bot_token")
        expect(token).to_have_attribute("type", "password")
        token.fill("fixture-token-" + name[-1])
        dialog.get_by_role("button", name="保存连接").click()
        expect(page.get_by_role("heading", name=name)).to_be_visible()
    page.locator("article.card").filter(has=page.get_by_role("heading", name="渠道账号 A")).get_by_role("button", name="编辑", exact=True).click()
    expect(page.get_by_role("dialog").locator("#root_config_bot_token")).to_have_value("********")
    page.get_by_role("dialog").get_by_role("button", name="取消", exact=True).click()
    page.get_by_role("button", name="统一聊天", exact=True).click()
    for name in ["渠道账号 A", "渠道账号 B"]:
        page.get_by_role("button", name="添加通道联系人", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("账号连接", exact=True).select_option(label=name + " · telegram")
        dialog.get_by_label("平台联系地址").fill("same-platform-address")
        dialog.get_by_label("显示名称").fill(name + "联系人")
        dialog.get_by_role("button", name="添加联系人", exact=True).click()
        expect(page.locator(".contact").filter(has_text=name + "联系人")).to_be_visible()
    expect(page.locator(".contact")).to_have_count(2)

    # Exercise the real inbox consumer, with colliding provider IDs across accounts.
    seed(env, '''from app.services.tenant_context import tenant_scope
from app.channels.config_store import list_connections, connection_scope
from app.services.message_store import push_inbox
with tenant_scope(1):
 for account in list_connections():
  with connection_scope(account['connection_id']):
   push_inbox('telegram', connection_id=account['connection_id'], contact_id='same-platform-address',
       contact_name=account['name']+'联系人', direction='inbound', content=account['name']+'的独立消息',
       msg_id='same-message-id', metadata={'team_id': 1})
''')
    for name in ["渠道账号 A", "渠道账号 B"]:
        sync_account(page, name, 1)
        page.locator(".contact").filter(has_text=name + "联系人").click()
        expect(page.locator(".message")).to_have_count(1)
        expect(page.locator(".message")).to_contain_text(name + "的独立消息")
    sync_account(page, "渠道账号 A", 0)
    page.locator(".contact").click()
    expect(page.locator(".message")).to_have_count(1)

    # Populate the production ledger without invoking a provider. These are fixtures,
    # not proof of external sending or platform delivery.
    fixture = seed(env, '''import json
from app.services.tenant_context import tenant_scope
from app.channels.config_store import list_connections, connection_scope
from app.services.message_store import list_contacts
from app.services.outbound_delivery import prepare_external, complete_external, reconcile_receipt
from app.channels.base import UnifiedMessage
with tenant_scope(1):
 account=next(a for a in list_connections() if a['name']=='渠道账号 A')
 with connection_scope(account['connection_id']):
  person=list_contacts(connection_id=account['connection_id'])[0]
  for key in ['ui-unknown', 'ui-read']:
   message=UnifiedMessage(id='', customer_id=person['customer_id'], connection_id=account['connection_id'],
       channel_type='telegram', contact_id=person['contact_id'], contact_name=person['contact_name'],
       direction='outbound', content='原请求回执 '+key, created_at='2026-11-23T10:00:00Z', metadata={'team_id':1})
   reservation=prepare_external(message, idempotency_key=key, team_id=1)
   result=({'success':True, 'message_id':'fixture-provider-message', 'delivery_state':'accepted'} if key=='ui-read'
       else {'success':False, 'error':'provider_result_unknown', 'delivery_state':'unknown'})
   complete_external(idempotency_key=key, delivery_token=reservation['delivery_token'], result=result, team_id=1)
  assert reconcile_receipt(connection_id=account['connection_id'], team_id=1, channel_type='telegram',
      provider_message_id='fixture-provider-message', state='read')
  print(json.dumps({'connection_id':account['connection_id']}))
''')
    page.locator(".conversation-title").get_by_role("button", name="刷新", exact=True).click()
    expect(page.locator(".message.outbound")).to_contain_text("已读")
    for key, expected in [("ui-unknown", "结果待核验，请查询原请求"), ("ui-read", "已读")]:
        page.get_by_label("请求编号").fill(key)
        page.get_by_role("button", name="查询回执", exact=True).click()
        expect(page.locator(".receipt dd").nth(0)).to_have_text(expected)
        expect(page.locator(".receipt dd").nth(1)).to_have_text(fixture["connection_id"])
    expect(page.locator(".receipt dd").nth(2)).to_have_text("fixture-provider-message")

    gateway = "http://127.0.0.1:8793/api/kellai/integrations/xcmax"
    headers = {"Authorization": "Bearer " + STATE["token"]}
    assert page.request.get(gateway + "/channels", headers=headers).status == 200
    # Querying a sending receipt requires the scope deliberately left unchecked.
    assert page.request.get(gateway + "/messages/requests/ui-read", headers=headers).status == 403
    page.screenshot(path=ARTIFACTS / "unified-chat.png", full_page=True)
    page.set_viewport_size({"width": 650, "height": 820})
    page.screenshot(path=ARTIFACTS / "unified-chat-narrow.png", full_page=True)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "horizontal overflow"
    page.get_by_role("button", name="XCMAX 授权", exact=True).click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="撤销宿主连接", exact=True).click()
    expect(page.get_by_role("heading", name="等待 XCMAX 授权")).to_be_visible()
    assert page.request.get(gateway + "/channels", headers=headers).status == 401
    # Revoking the host does not delete the operator's original receipt/history.
    page.get_by_role("button", name="统一聊天", exact=True).click()
    page.get_by_label("请求编号").fill("ui-unknown")
    page.get_by_role("button", name="查询回执", exact=True).click()
    expect(page.locator(".receipt dd").nth(0)).to_have_text("结果待核验，请查询原请求")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.get_by_role("button", name="锁定工具", exact=True).click()
    expect(page.get_by_role("heading", name="从 XCMAX 连接")).to_be_visible()


server = ThreadingHTTPServer(("127.0.0.1", 17599), Host)
threading.Thread(target=server.serve_forever, daemon=True).start()
with tempfile.TemporaryDirectory(prefix="kellai-ui-") as data:
    env = {**os.environ, "KELLAI_DATA_DIR": data, "KELLAI_WORKSPACE_ID": "1", "KELLAI_PORT": "8793",
           "KELLAI_CHANNEL_WORKER_ENABLED": "0", "KELLAI_VAULT_KEY": Fernet.generate_key().decode(),
           "KELLAI_XCMAX_API_BASE": "http://127.0.0.1:17599"}
    ARTIFACTS = Path(os.environ.get("KELLAI_UI_ARTIFACT_DIR", data))
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with (ARTIFACTS / "server.log").open("w") as log:
        backend = subprocess.Popen([sys.executable, "-c", "from app.main import run; run()"], cwd=ROOT / "backend",
                                   env=env, stdout=log, stderr=log, start_new_session=os.name == "posix")
        frontend = subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1"], cwd=ROOT / "desktop",
                                    env=env, stdout=log, stderr=log, start_new_session=os.name == "posix")
        try:
            for url in ["http://127.0.0.1:8793/health", "http://127.0.0.1:1420"]:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(url, timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise AssertionError("server failed: " + url)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=os.environ.get("KELLAI_TEST_BROWSER_PATH"),
                                                     headless=True, args=["--no-sandbox"])
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = context.new_page()
                errors, sends = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: sends.append(request.url) if "/messages/send" in request.url else None)
                try:
                    exercise(page, env)
                    assert not errors, errors
                    assert not sends, "the visual tool must not dispatch messages"
                except BaseException:
                    page.screenshot(path=ARTIFACTS / "failure.png", full_page=True)
                    (ARTIFACTS / "failure.html").write_text(page.content(), encoding="utf-8")
                    raise
                finally:
                    context.tracing.stop(path=ARTIFACTS / "trace.zip")
                    browser.close()
                print("PASS: local handoff, subset scope, two account forms, masked secrets, isolated inbox sync/dedupe, "
                      "unknown/read receipts, narrow layout, host revocation, retained history and lock; no sends or page errors")
        finally:
            stop(frontend)
            stop(backend)
            server.shutdown()
            server.server_close()
