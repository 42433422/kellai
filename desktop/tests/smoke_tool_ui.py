"""Real local tool UI, isolated host transport and accounts; no provider traffic."""
import json, os, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright, expect

root = Path(__file__).resolve().parents[2]
state = {'claimed': False, 'connected': False}
pending = {'request_id': 'local-ui-smoke', 'authorization_secret': 'isolated-fixture-handoff-secret-12345678901234567890', 'protocol_version': 2,
 'requested_scopes': [{'id': s, 'label': s, 'description': 'fixture'} for s in ['channels.read','messages.read','messages.send']], 'expires_at': '2099-01-01T00:00:00Z'}
class Host(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def respond(self,data):
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'success':True,'data':data}).encode())
 def do_GET(self):
  assert self.path == '/api/kellai/binding/status'
  self.respond({'state':'connected' if state['connected'] else 'pending','pending': None if state['connected'] else pending})
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
  if self.path.endswith('/handoff'):
   assert not state['claimed']; state['claimed']=True; self.respond(pending)
  elif self.path.endswith('/approve'):
   assert body['authorization_secret']==pending['authorization_secret']
   assert set(body['accepted_scopes'])=={'channels.read','messages.read'}
   state['connected']=True; self.respond({'state':'connected'})
  else: raise AssertionError(self.path)

server=ThreadingHTTPServer(('127.0.0.1',17599),Host)
threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory(prefix='kellai-ui-') as data:
 env={**os.environ,'KELLAI_DATA_DIR':data,'KELLAI_WORKSPACE_ID':'1','KELLAI_PORT':'8793','KELLAI_CHANNEL_WORKER_ENABLED':'0','KELLAI_VAULT_KEY':Fernet.generate_key().decode(),'KELLAI_XCMAX_API_BASE':'http://127.0.0.1:17599'}
 artifacts=Path(os.environ.get('KELLAI_UI_ARTIFACT_DIR',data));artifacts.mkdir(parents=True,exist_ok=True)
 log=open(artifacts/'server.log','w')
 backend=subprocess.Popen([sys.executable,'-c','from app.main import run; run()'],cwd=root/'backend',env=env,stdout=log,stderr=log)
 frontend=subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1'],cwd=root/'desktop',env=env,stdout=log,stderr=log)
 try:
  for url in ['http://127.0.0.1:8793/health','http://127.0.0.1:1420']:
   for _ in range(100):
    try: urllib.request.urlopen(url,timeout=1); break
    except OSError: time.sleep(.1)
   else: raise AssertionError('server failed: '+url)
  with sync_playwright() as p:
   browser=p.chromium.launch(executable_path=os.environ.get('KELLAI_TEST_BROWSER_PATH'),headless=True,args=['--no-sandbox'])
   page=browser.new_page(viewport={'width':1280,'height':900})
   failures=[]
   page.on('pageerror',lambda error: failures.append(str(error)))
   page.goto('http://127.0.0.1:1420')
   page.get_by_role('button',name='接收连接请求',exact=True).click()
   expect(page.get_by_role('heading',name='待确认的连接请求')).to_be_visible()
   expect(page.get_by_role('checkbox')).to_have_count(3)
   page.get_by_role('checkbox').nth(0).check(); page.get_by_role('checkbox').nth(1).check()
   page.get_by_role('button',name='授权连接',exact=True).click()
   expect(page.get_by_role('heading',name='已授权 XCMAX')).to_be_visible()
   page.get_by_role('button',name='账号连接',exact=True).click()
   for name in ['渠道账号 A','渠道账号 B']:
    page.get_by_role('button',name='添加账号',exact=True).click()
    page.get_by_label('平台',exact=True).select_option('telegram')
    dialog=page.get_by_role('dialog')
    dialog.locator('#root_name').fill(name)
    token=dialog.locator('#root_config_bot_token')
    expect(token).to_have_attribute('type','password')
    token.fill('fixture-token-'+name[-1])
    dialog.get_by_role('button',name='保存连接').click()
    expect(page.get_by_role('heading',name=name)).to_be_visible()
   # Account edits read masks, never the original secret.
   page.locator('article.card').filter(has=page.get_by_role('heading',name='渠道账号 A')).get_by_role('button',name='编辑',exact=True).click()
   expect(page.get_by_role('dialog').locator('#root_config_bot_token')).to_have_value('********')
   page.get_by_role('dialog').get_by_role('button',name='取消',exact=True).click()
   page.get_by_role('button',name='统一聊天',exact=True).click()
   for name in ['渠道账号 A','渠道账号 B']:
    page.get_by_role('button',name='添加通道联系人',exact=True).click()
    dialog=page.get_by_role('dialog')
    dialog.get_by_label('账号连接',exact=True).select_option(label=name+' · telegram')
    dialog.get_by_label('平台联系地址').fill('same-platform-address')
    dialog.get_by_label('显示名称').fill(name+'联系人')
    dialog.get_by_role('button',name='添加联系人',exact=True).click()
    expect(page.locator('.contact').filter(has_text=name+'联系人')).to_be_visible()
   expect(page.locator('.contact')).to_have_count(2)
   seed='''from app.services.tenant_context import tenant_scope
from app.channels.config_store import list_connections,connection_scope
from app.services.message_store import save_message,register_contact
from app.channels.base import UnifiedMessage
with tenant_scope(1):
 for account in list_connections():
  with connection_scope(account['connection_id']):
   person=register_contact(connection_id=account['connection_id'],channel_type='telegram',contact_id='same-platform-address',contact_name=account['name']+'联系人')
   save_message(UnifiedMessage(id='same-message-id',customer_id=person['customer_id'],connection_id=account['connection_id'],channel_type='telegram',contact_id='same-platform-address',contact_name=account['name']+'联系人',direction='inbound',content=account['name']+'的独立消息',created_at='2026-11-23T10:00:00Z',metadata={'team_id':1}))
'''
   subprocess.run([sys.executable,'-c',seed],cwd=root/'backend',env=env,check=True,capture_output=True)
   for name in ['渠道账号 A','渠道账号 B']:
    page.locator('.contact').filter(has_text=name+'联系人').click()
    expect(page.locator('.message')).to_have_count(1)
    expect(page.locator('.message')).to_contain_text(name+'的独立消息')
   page.screenshot(path=artifacts/'unified-chat.png',full_page=True)
   page.get_by_label('选择账号',exact=True).select_option(label='渠道账号 A · telegram')
   expect(page.locator('.contact')).to_have_count(1)
   page.get_by_role('button',name='同步消息',exact=True).click()
   expect(page.get_by_text('已同步 0 条消息',exact=True)).to_be_visible()
   page.set_viewport_size({'width':650,'height':820})
   page.screenshot(path=artifacts/'unified-chat-narrow.png',full_page=True)
   assert not failures,failures
   browser.close()
   print('PASS: real local handoff, subset approval, two account forms, masked secrets, same-address conversations isolated, account filter, inbox sync, narrow viewport; zero page errors')
 finally:
  frontend.terminate();backend.terminate();frontend.wait(timeout=10);backend.wait(timeout=10);server.shutdown();log.close()
