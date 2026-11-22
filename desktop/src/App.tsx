import { useEffect, useId, useRef, useState, useSyncExternalStore } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Form from '@rjsf/core';
import validator from '@rjsf/validator-ajv8';
import type { RJSFSchema, UiSchema } from '@rjsf/utils';
import { ArrowUpRight, Cable, Check, CircleHelp, KeyRound, Mail, Plus, RefreshCw, ShieldCheck, Unplug, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { beginHandoff, currentAccountKey, errorMessage, getSession, request, setToolSession, subscribeSession } from './api/client';
import { receiptLabel, receiptState, scopeLabels, type Account, type Channel, type Contact, type Message, type PairStatus, type PendingPairing, type Receipt } from './types';

async function openExternal(url: string) {
  const parsed = new URL(url);
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password) throw new Error('授权地址必须是 HTTPS 网站');
  if ('__TAURI_INTERNALS__' in window) {
    const { openUrl } = await import('@tauri-apps/plugin-opener');
    await openUrl(url);
  } else window.open(url, '_blank', 'noopener,noreferrer');
}

function ErrorNote({ error }: { error: unknown }) {
  return error ? <div className="notice error" role="alert">{errorMessage(error)}</div> : null;
}

export function passwordWidgets(schema?: RJSFSchema): UiSchema {
  const result: UiSchema = {};
  for (const [key, raw] of Object.entries(schema?.properties || {})) {
    if (typeof raw !== 'object') continue;
    result[key] = raw.writeOnly || raw.format === 'password'
      ? { 'ui:widget': 'password', 'ui:autocomplete': 'new-password' }
      : passwordWidgets(raw);
  }
  return result;
}

function AccountEditor({ channels, account, onClose }: { channels: Channel[]; account?: Account; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const platformId = useId();
  const authTypeId = useId();
  const cache = useQueryClient();
  const [kind, setKind] = useState(account?.channel_type || channels[0]?.channel_type || '');
  const [authType, setAuthType] = useState<Account['auth_type']>(account?.auth_type || channels[0]?.auth_types?.[0] || 'credentials');
  const [values, setValues] = useState<Record<string, unknown>>({ name: account?.name || '', config: account?.config || {}, enabled: account?.enabled ?? true });
  const channel = channels.find((item) => item.channel_type === kind);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  const saving = useMutation({ mutationFn: async (formData: Record<string, unknown>) => {
    const common = { name: formData.name, config: formData.config || {}, enabled: formData.enabled };
    return account
      ? request<Account>('patch', `/accounts/${encodeURIComponent(account.connection_id)}`, { ...common, expected_version: account.version })
      : request<Account>('post', '/accounts', { ...common, channel_type: kind, auth_type: authType });
  }, onSuccess: async () => { await cache.invalidateQueries({ queryKey: ['accounts'] }); toast.success('账号连接已保存'); onClose(); } });
  const schema: RJSFSchema = { type: 'object', required: ['name', 'config'], properties: {
    name: { type: 'string', title: '账号名称', minLength: 1, maxLength: 100 },
    config: { ...(channel?.config_schema || { type: 'object', properties: {} }), title: '连接信息' },
    enabled: { type: 'boolean', title: '允许使用这个连接', default: true },
  } };
  return <dialog ref={dialog} onCancel={onClose} className="editor">
    <header><h2>{account ? '编辑账号连接' : '添加账号连接'}</h2><button className="icon" aria-label="关闭" onClick={onClose}><X size={20} /></button></header>
    <p className="muted">凭据保存在本机受保护的账号库。已保存的秘密以掩码显示，保持掩码即可沿用。</p>
    <div className="field"><label htmlFor={platformId}>平台</label><select id={platformId} value={kind} disabled={Boolean(account)} onChange={(event) => { setKind(event.target.value); setValues({ name: '', config: {}, enabled: true }); setAuthType(channels.find((item) => item.channel_type === event.target.value)?.auth_types?.[0] || 'credentials'); }}>
      {channels.map((item) => <option key={item.channel_type} value={item.channel_type}>{item.display_name || item.name || item.channel_type}</option>)}
    </select></div>
    {(channel?.auth_types?.length || 0) > 1 && <div className="field"><label htmlFor={authTypeId}>授权方式</label><select id={authTypeId} value={authType} disabled={Boolean(account)} onChange={(event) => setAuthType(event.target.value as Account['auth_type'])}>
      {channel?.auth_types?.map((type) => <option key={type} value={type}>{{ credentials: '平台凭据', oauth2: 'OAuth 授权', browser: '浏览器会话' }[type]}</option>)}
    </select></div>}
    <ErrorNote error={saving.error} />
    <Form key={`${kind}:${authType}`} schema={schema} uiSchema={passwordWidgets(schema)} validator={validator}
      formData={values} onChange={(event) => setValues(event.formData || {})} disabled={saving.isPending}
      onSubmit={(event) => saving.mutate(event.formData || {})}>
      <footer><button type="button" onClick={onClose}>取消</button><button type="submit" className="primary" disabled={saving.isPending || !channel?.config_schema}>{saving.isPending ? '正在保存…' : '保存连接'}</button></footer>
    </Form>
    {!channel?.config_schema && <div className="notice">该平台暂未提供可配置的接入方式。</div>}
  </dialog>;
}

function Accounts() {
  const cache = useQueryClient();
  const [editor, setEditor] = useState<Account | 'new' | null>(null);
  const namespace = currentAccountKey();
  const accounts = useQuery({ queryKey: ['accounts', namespace], queryFn: () => request<Account[]>('get', '/accounts') });
  const channels = useQuery({ queryKey: ['channels', namespace], queryFn: () => request<Channel[]>('get', '/channels') });
  const operation = useMutation({ mutationFn: async ({ account, action }: { account: Account; action: 'test' | 'toggle' | 'delete' | 'oauth' }) => {
    const path = `/accounts/${encodeURIComponent(account.connection_id)}`;
    if (action === 'test') {
      const result = await request<{ connected: boolean; message: string }>('post', `${path}/test`, {});
      if (!result.connected) throw new Error(result.message || '连接尚未验证通过');
      return result.message || '账号鉴权通过；实际收发以回执为准';
    }
    if (action === 'toggle') { await request('patch', path, { enabled: !account.enabled, expected_version: account.version }); return account.enabled ? '连接已停用' : '连接已启用'; }
    if (action === 'delete') { await request('delete', path); return '连接已移除'; }
    const result = await request<{ authorization_url: string }>('post', `${path}/oauth/start`, {});
    await openExternal(result.authorization_url);
    return '请在浏览器完成授权，然后刷新账号状态';
  }, onSuccess: async (message) => { toast.success(message); await cache.invalidateQueries({ queryKey: ['accounts'] }); }, onError: (error) => toast.error(errorMessage(error)) });
  return <section>
    <div className="section-title"><div><h2>账号连接</h2><p>每个外部账号独立保存、独立启停，按连接核对收发。</p></div><div className="actions">
      <button aria-label="刷新账号" onClick={() => void accounts.refetch()}><RefreshCw size={16} /></button>
      <button className="primary" disabled={!channels.data?.length} onClick={() => setEditor('new')}><Plus size={16} />添加账号</button></div></div>
    <ErrorNote error={accounts.error || channels.error} />
    {accounts.isLoading ? <p className="muted">正在读取本机账号…</p> : !accounts.data?.length ? <div className="empty"><KeyRound size={32} /><h3>添加第一个外部账号</h3><p>连接后，XCMAX 可以在授权范围内使用它。</p></div> : <div className="account-grid">{accounts.data.map((account) => {
      const channel = channels.data?.find((item) => item.channel_type === account.channel_type);
      return <article className="card" key={account.connection_id}>
        <div className="card-top"><span className="platform"><Cable size={18} />{channel?.display_name || channel?.name || account.channel_type}</span><span className={`badge ${account.enabled && account.connected ? 'good' : ''}`}>{!account.enabled ? '已停用' : account.connected ? '已连接' : '待验证'}</span></div>
        <h3>{account.name}</h3><p className="identifier">{account.connection_id}</p>
        <div className="capabilities"><span>接收：{channel?.capabilities?.receive ? '已实现' : '未开放'}</span><span>发送：{channel?.capabilities?.send ? '已实现' : '未开放'}</span></div>
        {channel?.capabilities?.limitations?.slice(0, 2).map((line) => <p className="limitation" key={line}>{line}</p>)}
        <div className="actions card-actions"><button onClick={() => setEditor(account)}>编辑</button><button disabled={operation.isPending || !account.enabled} onClick={() => operation.mutate({ account, action: 'test' })}>验证连接</button>
          {account.auth_type === 'oauth2' && <button disabled={operation.isPending || !account.enabled} onClick={() => operation.mutate({ account, action: 'oauth' })}>登录授权<ArrowUpRight size={14} /></button>}
          <button disabled={operation.isPending} onClick={() => operation.mutate({ account, action: 'toggle' })}>{account.enabled ? '停用' : '启用'}</button>
          <button className="danger" disabled={operation.isPending} onClick={() => { if (window.confirm(`移除“${account.name}”的连接凭据？已有统一聊天会保留。`)) operation.mutate({ account, action: 'delete' }); }}>移除</button>
        </div>
      </article>;
    })}</div>}
    {editor && channels.data && <AccountEditor channels={channels.data} account={editor === 'new' ? undefined : editor} onClose={() => setEditor(null)} />}
  </section>;
}

function Pairing() {
  const cache = useQueryClient();
  const namespace = currentAccountKey();
  const state = useQuery({ queryKey: ['pairing', namespace], queryFn: () => request<PairStatus>('get', '/integrations/xcmax/status'), refetchInterval: 5000 });
  const pending = useQuery({ queryKey: ['pairing-pending', namespace], queryFn: () => request<PendingPairing | null>('get', '/integrations/xcmax/pending'), refetchInterval: 5000 });
  const [checked, setChecked] = useState<string[]>([]);
  const item = pending.data;
  useEffect(() => { setChecked([]); }, [item?.request_id]);
  const scopes = (item?.requested_scopes || []).map((scope) => scope.id).filter((scope) => scope in scopeLabels);
  const action = useMutation({ mutationFn: ({ kind, scopes: accepted }: { kind: 'approve' | 'cancel' | 'disconnect'; scopes?: string[] }) => request('post', `/integrations/xcmax/${kind}`,
    kind === 'disconnect' ? {} : { request_id: item?.request_id, ...(kind === 'approve' ? { accepted_scopes: accepted } : {}) }),
  onSuccess: async (_, variables) => { await cache.invalidateQueries({ queryKey: ['pairing'] }); await cache.invalidateQueries({ queryKey: ['pairing-pending'] }); toast.success(variables.kind === 'disconnect' ? '本机授权已撤销，请在 XCMAX 查看并清除失效连接' : '授权状态已更新'); }, onError: (error) => toast.error(errorMessage(error)) });
  return <section><div className="section-title"><div><h2>XCMAX 授权</h2><p>业务任务和审批由 XCMAX 管理，客来来按授权执行通道操作。</p></div></div>
    <ErrorNote error={state.error || pending.error} />
    <article className="card pairing-card"><ShieldCheck size={28} /><h3>{state.data?.connected ? '已授权 XCMAX' : '等待 XCMAX 授权'}</h3>
      {state.data?.message && <p className="muted">{state.data.message}</p>}
      <ul className="scope-list">{state.data?.connection?.authorized_scopes?.map((scope) => <li key={scope}><Check size={16} />{scopeLabels[scope] || scope}</li>)}</ul>
      {state.data?.connected && <button className="danger" disabled={action.isPending} onClick={() => { if (window.confirm('断开后 XCMAX 将无法继续使用客来来的账号与通道。确认断开？')) action.mutate({ kind: 'disconnect' }); }}><Unplug size={16} />撤销宿主连接</button>}
    </article>
    {item && <article className="card pairing-card"><h3>待确认的连接请求</h3><p>选择允许 XCMAX 使用的范围。</p>
      {scopes.map((scope) => <label className="checkbox" key={scope}><input type="checkbox" checked={checked.includes(scope)} onChange={(event) => setChecked((old) => event.target.checked ? [...old, scope] : old.filter((value) => value !== scope))} />{scopeLabels[scope]}</label>)}
      <div className="actions"><button disabled={action.isPending} onClick={() => action.mutate({ kind: 'cancel' })}>拒绝</button><button className="primary" disabled={!checked.length || action.isPending} onClick={() => action.mutate({ kind: 'approve', scopes: checked })}>授权连接</button></div>
    </article>}
  </section>;
}

function ContactEditor({ accounts, initialConnection, onClose }: { accounts: Account[]; initialConnection: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const accountId = useId();
  const cache = useQueryClient();
  const [connectionId, setConnectionId] = useState(initialConnection || accounts[0]?.connection_id || '');
  const [address, setAddress] = useState('');
  const [name, setName] = useState('');
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  const saving = useMutation({ mutationFn: () => request<Contact>('post', '/contacts', {
    connection_id: connectionId, contact_id: address.trim(), contact_name: name.trim(),
  }), onSuccess: async () => { await cache.invalidateQueries({ queryKey: ['contacts'] }); toast.success('通道联系人已添加'); onClose(); } });
  return <dialog ref={dialog} onCancel={onClose} className="editor"><header><h2>添加通道联系人</h2><button className="icon" aria-label="关闭" onClick={onClose}><X size={20} /></button></header>
    <p className="muted">填写这个账号已有权限联系的平台地址，如 chat_id、openid 或会话编号。添加联系人不会发送消息。</p>
    <ErrorNote error={saving.error} /><form onSubmit={(event) => { event.preventDefault(); saving.mutate(); }}>
      <div className="field"><label htmlFor={accountId}>账号连接</label><select id={accountId} required value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>{accounts.map((account) => <option key={account.connection_id} value={account.connection_id}>{account.name} · {account.channel_type}</option>)}</select></div>
      <label>平台联系地址<input required maxLength={256} value={address} onChange={(event) => setAddress(event.target.value)} /></label>
      <label>显示名称<input maxLength={256} value={name} onChange={(event) => setName(event.target.value)} placeholder="选填" /></label>
      <footer><button type="button" onClick={onClose}>取消</button><button className="primary" disabled={saving.isPending || !connectionId || !address.trim()}>{saving.isPending ? '正在保存…' : '添加联系人'}</button></footer>
    </form></dialog>;
}

function Traffic() {
  const cache = useQueryClient();
  const accountFilterId = useId();
  const namespace = currentAccountKey();
  const [addingContact, setAddingContact] = useState(false);
  const [connectionId, setConnectionId] = useState('');
  const [contact, setContact] = useState<Contact | null>(null);
  const [requestId, setRequestId] = useState('');
  const accounts = useQuery({ queryKey: ['accounts', namespace], queryFn: () => request<Account[]>('get', '/accounts') });
  const channels = useQuery({ queryKey: ['channels', namespace], queryFn: () => request<Channel[]>('get', '/channels') });
  const activeAccounts = accounts.data?.filter((account) => account.enabled && channels.data?.find((channel) => channel.channel_type === account.channel_type)?.capabilities?.contacts) || [];
  const selectedAccount = accounts.data?.find((account) => account.connection_id === connectionId);
  const canSync = selectedAccount?.enabled && channels.data?.find((channel) => channel.channel_type === selectedAccount.channel_type)?.capabilities?.sync;
  const sync = useMutation({ mutationFn: () => request<{ synced: number }>('post', '/channels/sync-inbox', { connection_id: connectionId, limit: 100 }),
    onSuccess: async (data) => { await cache.invalidateQueries({ queryKey: ['contacts'] }); await cache.invalidateQueries({ queryKey: ['messages'] }); toast.success('已同步 ' + data.synced + ' 条消息'); }, onError: (error) => toast.error(errorMessage(error)) });
  const contacts = useQuery({ queryKey: ['contacts', namespace, connectionId], queryFn: () => request<{ contacts: Contact[]; total: number }>('get', connectionId ? `/contacts?connection_id=${encodeURIComponent(connectionId)}` : '/contacts') });
  const messages = useQuery({ queryKey: ['messages', namespace, contact?.connection_id, contact?.customer_id], enabled: Boolean(contact),
    queryFn: () => request<{ messages: Message[] }>('get', `/contacts/${contact!.customer_id}/messages?connection_id=${encodeURIComponent(contact!.connection_id)}`) });
  const receipt = useMutation({ mutationFn: async () => {
    const original = requestId.trim();
    const result = await request<Receipt>('get', `/messages/requests/${encodeURIComponent(original)}`);
    if (result.request_id !== original) throw new Error('回执与原请求不符');
    return result;
  } });
  return <section><div className="section-title"><div><h2>统一聊天</h2><p>汇总各账号的会话和消息，发送任务在 XCMAX 中发起。</p></div><div className="actions"><button disabled={!activeAccounts.length} onClick={() => setAddingContact(true)}><Plus size={16} />添加通道联系人</button><button disabled={!canSync || sync.isPending} title="选择具体账号后，同步该账号已接入的收件箱" onClick={() => sync.mutate()}><RefreshCw size={16} />{sync.isPending ? '正在同步…' : '同步消息'}</button></div></div><ErrorNote error={accounts.error || channels.error} />
    <div className="account-filter"><label htmlFor={accountFilterId}>选择账号</label><select id={accountFilterId} value={connectionId} onChange={(event) => { setConnectionId(event.target.value); setContact(null); }}><option value="">全部账号</option>{accounts.data?.map((account) => <option key={account.connection_id} value={account.connection_id}>{account.name} · {account.channel_type}</option>)}</select></div>
    <div className="traffic"><aside><h3>通道联系人</h3><ErrorNote error={contacts.error} />{contacts.isFetching && <p className="muted">正在加载…</p>}
      {contacts.data?.contacts.map((item) => <button className={`contact ${contact?.customer_id === item.customer_id && contact.connection_id === item.connection_id ? 'selected' : ''}`} key={`${item.connection_id}:${item.customer_id}:${item.contact_id}`} onClick={() => setContact(item)}><strong>{item.contact_name || item.contact_id}</strong><small>{accounts.data?.find((account) => account.connection_id === item.connection_id)?.name || item.channel_type} · {item.contact_id}</small></button>)}
      {!contacts.isFetching && !contacts.data?.contacts.length && <p className="muted">{connectionId ? '这个账号暂无通道联系人' : '暂无通道联系人'}</p>}
    </aside><div className="conversation"><div className="conversation-title"><h3>{contact?.contact_name || '消息记录'}</h3><button disabled={!contact || messages.isFetching} onClick={() => void messages.refetch()}><RefreshCw size={14} />刷新</button></div><ErrorNote error={messages.error} />
      {messages.data?.messages.map((message) => <article className={`message ${message.direction === 'outbound' ? 'outbound' : ''}`} key={message.id}><p>{message.content}</p><small>{message.created_at}{message.metadata?.delivery_state ? ` · ${receiptLabel(message.metadata.delivery_state)}` : ''}</small></article>)}
      {!messages.data?.messages.length && <div className="empty compact"><Mail size={24} /><p>{contact ? '暂无消息记录' : '选择联系人查看原始消息'}</p></div>}
    </div></div>
    {addingContact && <ContactEditor accounts={activeAccounts} initialConnection={activeAccounts.some((account) => account.connection_id === connectionId) ? connectionId : ''} onClose={() => setAddingContact(false)} />}
    <article className="card receipt"><h3>查询原发送回执</h3><p className="muted">查询只读取原请求，不会再次发送消息。</p><form onSubmit={(event) => { event.preventDefault(); receipt.mutate(); }}><label>请求编号<input value={requestId} onChange={(event) => { setRequestId(event.target.value); receipt.reset(); }} required maxLength={200} placeholder="填写 XCMAX 中的发送请求编号" /></label><button disabled={receipt.isPending || !requestId.trim()}>查询回执</button></form><ErrorNote error={receipt.error} />
      {receipt.data && <dl><dt>状态</dt><dd>{receiptLabel(receiptState(receipt.data))}</dd><dt>账号连接</dt><dd>{receipt.data.connection_id}</dd><dt>平台消息编号</dt><dd>{receipt.data.provider_message_id || '尚无平台回执'}</dd></dl>}
    </article>
  </section>;
}

export default function App() {
  const session = useSyncExternalStore(subscribeSession, getSession);
  const cache = useQueryClient();
  const [tab, setTab] = useState<'accounts' | 'traffic' | 'pairing'>('accounts');
  const handoff = useMutation({ mutationFn: beginHandoff, onSuccess: () => setTab('pairing') });
  useEffect(() => subscribeSession(() => cache.clear()), [cache]);
  const openHost = async () => {
    try {
      if ('__TAURI_INTERNALS__' in window) { const { invoke } = await import('@tauri-apps/api/core'); await invoke('open_xcmax_desktop'); }
      else toast('请打开本机 XCMAX，在客来来工具中发起连接');
    } catch (error) { toast.error(errorMessage(error)); }
  };
  if (!session) return <main className="welcome"><img src="/brand/kellai-mark.svg" alt="" /><span className="eyebrow">XCMAX 工具</span><h1>客来来</h1><p>管理外部账号，连接收发通道。</p><div className="welcome-card"><Cable size={30} /><h2>从 XCMAX 连接</h2><p>打开 XCMAX 的客来来工具并发起连接，然后在这里接收授权请求。</p><ErrorNote error={handoff.error} /><div className="actions"><button onClick={() => void openHost()}>打开 XCMAX<ArrowUpRight size={16} /></button><button className="primary" disabled={handoff.isPending} onClick={() => handoff.mutate()}>{handoff.isPending ? '正在连接…' : '接收连接请求'}</button></div></div></main>;
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><img src="/brand/kellai-mark.svg" alt="" /><div><strong>客来来</strong><span>账号与通道工具</span></div></div><nav aria-label="工具导航">
    <button className={tab === 'accounts' ? 'active' : ''} onClick={() => setTab('accounts')}><KeyRound size={18} />账号连接</button>
    <button className={tab === 'traffic' ? 'active' : ''} onClick={() => setTab('traffic')}><Mail size={18} />统一聊天</button>
    <button className={tab === 'pairing' ? 'active' : ''} onClick={() => setTab('pairing')}><ShieldCheck size={18} />XCMAX 授权</button>
  </nav><div className="sidebar-bottom"><span><CircleHelp size={16} />业务处理在 XCMAX 中完成</span><button onClick={() => setToolSession(null)}>锁定工具</button></div></aside><main className="workspace"><header className="workspace-header"><span>本机工作区 {session.user.team_id}</span><button onClick={() => void openHost()}>打开 XCMAX<ArrowUpRight size={15} /></button></header>{tab === 'accounts' ? <Accounts /> : tab === 'traffic' ? <Traffic /> : <Pairing />}</main></div>;
}
