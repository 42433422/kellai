import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  Clock3,
  Link2,
  Loader2,
  RefreshCw,
  Radio,
  Settings,
  ShieldCheck,
  Unplug,
  Users,
} from 'lucide-react';
import { clsx } from 'clsx';
import { getChannels, getDouyinWebPortalStatus } from '../api/settings';
import ChannelLogo, { CHANNEL_BRAND_COLOR } from '../components/ChannelLogo';
import type { Channel } from '../types';

type DouyinWebPortalState = {
  connected: boolean;
  status: string;
  account_name?: string;
  monitor_enabled?: boolean;
  monitor_running?: boolean;
  contact_count?: number;
  last_sync_at?: string;
  last_message_at?: string;
  last_error?: string;
};

type AssetState = 'connected' | 'authorized' | 'expired' | 'pending' | 'offline';

type ChannelAccountAsset = {
  id: string;
  channelType: Channel['type'];
  channelName: string;
  accountName: string;
  accountId: string;
  bindingType: string;
  state: AssetState;
  connected: boolean;
  monitorRunning?: boolean;
  contactCount?: number;
  lastSyncAt?: string;
  lastMessageAt?: string;
  message?: string;
  error?: string;
};

const CHANNEL_LABELS: Record<string, string> = {
  wechat: '微信开放平台',
  wework: '企业微信',
  phone: '电话',
  douyin: '抖音',
  miniprogram: '公众号 / 小程序',
  pdd: '拼多多',
  taobao: '淘宝 / 千牛',
  jd: '京东 / 京麦',
  alibaba: '1688',
  whatsapp: 'WhatsApp',
  telegram: 'Telegram',
  line: 'LINE',
  email: '邮件',
  sms: '短信',
  web: '网页',
};

const ACCOUNT_NAME_KEYS = [
  'account_name',
  'nickname',
  'shop_name',
  'store_name',
  'corp_name',
  'display_name',
  'bot_name',
];

const ACCOUNT_ID_KEYS = [
  'oauth_user_id',
  'oauth_open_id',
  'oauth_openid',
  'open_id',
  'openid',
  'open_kfid',
  'phone_number_id',
  'bot_username',
  'user_id',
  'client_key',
  'client_id',
  'app_key',
  'app_id',
];

const STATE_META: Record<AssetState, { label: string; tone: string; dot: string }> = {
  connected: {
    label: '在线',
    tone: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
    dot: 'bg-emerald-500',
  },
  authorized: {
    label: '已授权',
    tone: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-500/30 dark:bg-blue-500/10 dark:text-blue-300',
    dot: 'bg-blue-500',
  },
  expired: {
    label: '登录已过期',
    tone: 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
    dot: 'bg-red-500',
  },
  pending: {
    label: '待验证',
    tone: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
    dot: 'bg-amber-500',
  },
  offline: {
    label: '离线',
    tone: 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300',
    dot: 'bg-slate-400',
  },
};

function unwrapResponse<T>(response: unknown): T {
  const raw = response as { data?: { data?: T } | T } | T;
  if (raw && typeof raw === 'object' && 'data' in raw) {
    const first = raw.data;
    if (first && typeof first === 'object' && 'data' in first) return first.data as T;
    return first as T;
  }
  return raw as T;
}

function configText(channel: Channel, keys: string[]): string {
  for (const key of keys) {
    const value = String(channel.config?.[key] ?? '').trim();
    if (value && !['true', 'false', 'null', 'undefined'].includes(value.toLowerCase())) return value;
  }
  return '';
}

function isTrue(value: unknown): boolean {
  return ['1', 'true', 'yes', 'ok'].includes(String(value ?? '').trim().toLowerCase());
}

function formatTime(value?: string): string {
  if (!value) return '暂无记录';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function bindingTypeOf(channel: Channel): string {
  if (isTrue(channel.config?.oauth_authorized)) return 'OAuth / 扫码授权';
  const mode = channel.onboarding?.recommended_mode;
  if (mode === 'scan') return '扫码 / 平台授权';
  if (mode === 'form') return 'API 凭据绑定';
  if (mode === 'select') return '线路绑定';
  return '平台账号绑定';
}

function genericAsset(channel: Channel): ChannelAccountAsset | null {
  const accountId = configText(channel, ACCOUNT_ID_KEYS);
  const explicitAccountName = configText(channel, ACCOUNT_NAME_KEYS);
  const oauthAuthorized = isTrue(channel.config?.oauth_authorized);
  const isBound = channel.connected || oauthAuthorized || Boolean(accountId && channel.enabled);
  if (!isBound) return null;

  const channelName = CHANNEL_LABELS[channel.type] || channel.name || channel.type;
  const accountName = explicitAccountName || (
    channel.type === 'wework' && channel.config?.open_kfid
      ? '企业微信客服账号'
      : `${channelName}账号`
  );
  let state: AssetState = 'offline';
  if (channel.connected) state = 'connected';
  else if (oauthAuthorized) state = 'authorized';
  else if (channel.onboarding?.status === 'saved' || channel.enabled) state = 'pending';

  return {
    id: `${channel.type}:primary`,
    channelType: channel.type,
    channelName,
    accountName,
    accountId: accountId || '平台未返回账号标识',
    bindingType: bindingTypeOf(channel),
    state,
    connected: channel.connected,
    message: channel.message,
  };
}

function douyinPortalAsset(portal: DouyinWebPortalState): ChannelAccountAsset | null {
  const accountName = String(portal.account_name || '').trim();
  if (!accountName && !portal.connected) return null;
  const rawStatus = String(portal.status || '').toLowerCase();
  const state: AssetState = portal.connected
    ? 'connected'
    : rawStatus === 'expired'
      ? 'expired'
      : rawStatus === 'disconnected'
        ? 'offline'
        : 'pending';
  return {
    id: 'douyin:web-portal',
    channelType: 'douyin',
    channelName: '抖音',
    accountName: accountName || '抖音渠道账号',
    accountId: '网站私信管理账号',
    bindingType: '网站 Token 登录',
    state,
    connected: portal.connected,
    monitorRunning: Boolean(portal.monitor_running),
    contactCount: Number(portal.contact_count || 0),
    lastSyncAt: portal.last_sync_at,
    lastMessageAt: portal.last_message_at,
    message: portal.connected ? '网站私信账号已绑定客来来' : undefined,
    error: portal.last_error,
  };
}

function StatCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Boxes;
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800/60">
      <div className={clsx('inline-flex rounded-xl p-2', tone)}><Icon className="h-4 w-4" /></div>
      <p className="mt-3 text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
      <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{label}</p>
    </div>
  );
}

export default function AIAssets() {
  const navigate = useNavigate();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [douyinPortal, setDouyinPortal] = useState<DouyinWebPortalState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    const [channelsResult, douyinResult] = await Promise.allSettled([
      getChannels(),
      getDouyinWebPortalStatus(),
    ]);
    if (channelsResult.status === 'fulfilled') {
      const data = unwrapResponse<Channel[]>(channelsResult.value);
      setChannels(Array.isArray(data) ? data : []);
    } else {
      setError('渠道账号读取失败，请确认后端服务已启动。');
    }
    if (douyinResult.status === 'fulfilled') {
      setDouyinPortal(unwrapResponse<DouyinWebPortalState>(douyinResult.value));
    } else {
      setDouyinPortal(null);
    }
    setRefreshedAt(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const assets = useMemo(() => {
    const rows: ChannelAccountAsset[] = [];
    const portalAsset = douyinPortal ? douyinPortalAsset(douyinPortal) : null;
    if (portalAsset) rows.push(portalAsset);
    for (const channel of channels) {
      if (channel.type === 'douyin' && portalAsset) {
        const oauthAuthorized = isTrue(channel.config?.oauth_authorized);
        if (!oauthAuthorized) continue;
      }
      const asset = genericAsset(channel);
      if (asset) rows.push(asset);
    }
    return rows;
  }, [channels, douyinPortal]);

  const connectedCount = assets.filter((asset) => asset.state === 'connected').length;
  const actionCount = assets.filter((asset) => ['expired', 'pending', 'offline'].includes(asset.state)).length;
  const monitoringCount = assets.filter((asset) => asset.monitorRunning).length;

  return (
    <div className="h-full overflow-y-auto pb-8" data-testid="ai-assets-page">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <div className="rounded-xl bg-violet-100 p-2 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300">
              <Boxes className="h-5 w-5" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">AI 资产</h1>
          </div>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">统一查看已绑定、已登录的渠道账号及其真实在线状态。</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
            刷新状态
          </button>
          <button
            type="button"
            onClick={() => navigate('/settings?tab=channels')}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
          >
            <Settings className="h-4 w-4" />
            渠道管理
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-5 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard icon={Boxes} label="已绑定账号" value={assets.length} tone="bg-violet-100 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300" />
        <StatCard icon={CheckCircle2} label="当前在线" value={connectedCount} tone="bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300" />
        <StatCard icon={AlertCircle} label="需要处理" value={actionCount} tone="bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300" />
        <StatCard icon={Radio} label="实时监听" value={monitoringCount} tone="bg-blue-100 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300" />
      </div>

      {loading && assets.length === 0 ? (
        <div className="mt-6 flex min-h-64 items-center justify-center rounded-2xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/60">
          <div className="text-center text-sm text-slate-500 dark:text-slate-400">
            <Loader2 className="mx-auto mb-3 h-6 w-6 animate-spin text-blue-500" />
            正在读取渠道登录状态…
          </div>
        </div>
      ) : assets.length === 0 ? (
        <div className="mt-6 flex min-h-64 flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 text-center dark:border-slate-700 dark:bg-slate-800/60">
          <Unplug className="h-10 w-10 text-slate-300 dark:text-slate-600" />
          <h2 className="mt-4 text-base font-semibold text-slate-800 dark:text-slate-100">暂无已绑定渠道账号</h2>
          <p className="mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400">完成渠道扫码、OAuth 或网站账号登录后，账号会自动出现在这里。</p>
          <button
            type="button"
            onClick={() => navigate('/settings?tab=channels')}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            去绑定渠道 <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {assets.map((asset) => {
            const meta = STATE_META[asset.state];
            const brandColor = CHANNEL_BRAND_COLOR[asset.channelType] || '#3b82f6';
            return (
              <section
                key={asset.id}
                className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800/60"
                data-channel-account={asset.id}
              >
                <div className="h-1" style={{ backgroundColor: brandColor }} />
                <div className="p-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" style={{ backgroundColor: `${brandColor}1a` }}>
                        <ChannelLogo type={asset.channelType} size={28} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-slate-400 dark:text-slate-500">{asset.channelName}</p>
                        <h2 className="mt-0.5 truncate text-lg font-semibold text-slate-900 dark:text-white">{asset.accountName}</h2>
                        <p className="mt-1 break-all text-xs text-slate-500 dark:text-slate-400">{asset.accountId}</p>
                      </div>
                    </div>
                    <span className={clsx('inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', meta.tone)}>
                      <span className={clsx('h-1.5 w-1.5 rounded-full', meta.dot)} />
                      {meta.label}
                    </span>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900/50">
                      <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500"><Link2 className="h-3.5 w-3.5" />绑定方式</div>
                      <p className="mt-1 font-medium text-slate-700 dark:text-slate-200">{asset.bindingType}</p>
                    </div>
                    <div className="rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900/50">
                      <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500"><Radio className="h-3.5 w-3.5" />实时监听</div>
                      <p className={clsx('mt-1 font-medium', asset.monitorRunning ? 'text-emerald-600 dark:text-emerald-300' : 'text-slate-700 dark:text-slate-200')}>
                        {asset.monitorRunning ? '运行中' : asset.channelType === 'douyin' ? '未运行' : '跟随渠道连接'}
                      </p>
                    </div>
                    <div className="rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900/50">
                      <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500"><Clock3 className="h-3.5 w-3.5" />最近同步</div>
                      <p className="mt-1 font-medium text-slate-700 dark:text-slate-200">{formatTime(asset.lastSyncAt)}</p>
                    </div>
                    <div className="rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-900/50">
                      <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500"><Users className="h-3.5 w-3.5" />已识别联系人</div>
                      <p className="mt-1 font-medium text-slate-700 dark:text-slate-200">{asset.contactCount !== undefined ? `${asset.contactCount} 位` : '随渠道同步'}</p>
                    </div>
                  </div>

                  {(asset.error || asset.message) && (
                    <div className={clsx(
                      'mt-4 rounded-xl border px-3.5 py-3 text-xs leading-relaxed',
                      asset.error
                        ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
                        : 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900/50 dark:text-slate-300',
                    )}>
                      {asset.error || asset.message}
                    </div>
                  )}

                  <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-4 dark:border-slate-700">
                    <div className="flex items-center gap-1.5 text-xs text-slate-400 dark:text-slate-500">
                      <ShieldCheck className="h-3.5 w-3.5" />
                      仅显示账号标识，不显示登录凭据
                    </div>
                    <button
                      type="button"
                      onClick={() => navigate('/settings?tab=channels')}
                      className="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400"
                    >
                      {asset.state === 'expired' ? '重新登录' : '管理'} <ArrowRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      )}

      <div className="mt-4 flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-500">
        <span>资产范围：已绑定、已授权或保留登录记录的渠道账号。</span>
        <span>{refreshedAt ? `更新于 ${formatTime(refreshedAt.toISOString())}` : '正在读取状态…'}</span>
      </div>
    </div>
  );
}
