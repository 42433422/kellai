import { useEffect, useRef, useState } from 'react';
import { currentAccountKey } from '../api/client';
import {
  deliveryLabel,
  deliveryReceiptFromMessage,
  getDeliveryReceiptForView,
  type DeliveryReceipt,
  type MessageDeliveryProjection,
} from '../api/messages';

interface Props {
  message: MessageDeliveryProjection;
  accountKey: string;
  isCurrentView: () => boolean;
}

/** Per-message presentation only; durable history stays in the server projection. */
export default function MessageDeliveryReceipt({ message, accountKey, isCurrentView }: Props) {
  const projected = deliveryReceiptFromMessage(message);
  const projectionKey = JSON.stringify(projected);
  const currentProjection = useRef(projectionKey);
  currentProjection.current = projectionKey;
  const active = useRef(true);
  const sequence = useRef(0);
  const [query, setQuery] = useState<{
    projectionKey: string; receipt: DeliveryReceipt; pending: boolean; error?: string;
  } | null>(null);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; sequence.current += 1; };
  }, []);
  if (!projected) return null;

  const visibleQuery = query?.projectionKey === projectionKey ? query : null;
  const receipt = visibleQuery?.receipt || projected;
  const failed = receipt.status === 'failed' || (receipt.status === 'accepted' && receipt.provider_state === 'failed');
  const uncertain = receipt.status === 'unknown' || receipt.status === 'sending';
  const lookup = async () => {
    const lookupSequence = ++sequence.current;
    const current = () => active.current && sequence.current === lookupSequence
      && currentProjection.current === projectionKey && currentAccountKey() === accountKey && isCurrentView();
    if (!current()) return;
    setQuery({ projectionKey, receipt, pending: true });
    try {
      const updated = await getDeliveryReceiptForView(projected.request_id, accountKey, current);
      if (!updated || !current()) return;
      if (updated.message_id !== message.id) throw new Error('receipt_message_mismatch');
      setQuery({ projectionKey, receipt: updated, pending: false });
    } catch {
      if (current()) setQuery({ projectionKey, receipt, pending: false, error: '暂时无法读取此消息回执，请稍后再查' });
    }
  };

  return (
    <div className="mt-1 text-right text-[10px]" data-delivery-request-id={projected.request_id}>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <span role="status" className={failed ? 'text-red-600 dark:text-red-400'
          : uncertain ? 'text-amber-700 dark:text-amber-400' : 'text-gray-500 dark:text-slate-400'}>
          {deliveryLabel(receipt)}
        </span>
        <button type="button" onClick={() => { void lookup(); }}
          disabled={visibleQuery?.pending || !accountKey}
          aria-label={`查询此消息回执：${projected.request_id}`} title={`原请求编号：${projected.request_id}`}
          className="shrink-0 text-blue-600 underline disabled:cursor-wait disabled:opacity-50 dark:text-blue-400">
          {visibleQuery?.pending ? '查询中…' : '查询回执'}
        </button>
      </div>
      {visibleQuery?.error && <span role="alert" className="text-red-600 dark:text-red-400">{visibleQuery.error}</span>}
    </div>
  );
}
