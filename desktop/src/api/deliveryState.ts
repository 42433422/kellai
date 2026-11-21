/** A late response may only clear the recovery pointer it originally created. */
export interface PendingDelivery {
  requestId: string;
  hash: string;
}

type DeliveryStorage = Pick<Storage, 'getItem' | 'removeItem'>;

export class PendingDeliveryStateError extends Error {
  name = 'PendingDeliveryStateError';
}

export function readPendingDelivery(storage: DeliveryStorage, key: string): PendingDelivery | null {
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    throw new PendingDeliveryStateError('无法读取本地发送记录，已停止新的发送，请先核验原请求回执');
  }
  // Only an absent key establishes that there is no recovery pointer. A
  // damaged/unreadable record may still belong to a message already sent.
  if (raw === null) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new PendingDeliveryStateError('本地发送记录损坏，已停止新的发送，请先核验原请求回执');
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new PendingDeliveryStateError('本地发送记录格式无效，已停止新的发送，请先核验原请求回执');
  }
  const record = value as Partial<PendingDelivery>;
  if (typeof record.requestId !== 'string' || !record.requestId.trim()
    || typeof record.hash !== 'string' || !/^[a-f0-9]{64}$/.test(record.hash)) {
    throw new PendingDeliveryStateError('本地发送记录格式无效，已停止新的发送，请先核验原请求回执');
  }
  return { requestId: record.requestId, hash: record.hash };
}

export function clearPendingDelivery(storage: DeliveryStorage, key: string, requestId: string): boolean {
  if (readPendingDelivery(storage, key)?.requestId !== requestId) return false;
  try {
    storage.removeItem(key);
  } catch {
    throw new PendingDeliveryStateError('无法更新本地发送记录，请先核验原请求回执');
  }
  return true;
}
