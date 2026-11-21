/** A late response may only clear the recovery pointer it originally created. */
export interface PendingDelivery {
  requestId: string;
  hash: string;
}

type DeliveryStorage = Pick<Storage, 'getItem' | 'removeItem'>;

export function readPendingDelivery(storage: DeliveryStorage, key: string): PendingDelivery | null {
  try {
    const value = JSON.parse(storage.getItem(key) || 'null');
    return typeof value?.requestId === 'string' && value.requestId
      && typeof value.hash === 'string' ? value : null;
  } catch { return null; }
}

export function clearPendingDelivery(storage: DeliveryStorage, key: string, requestId: string): boolean {
  if (readPendingDelivery(storage, key)?.requestId !== requestId) return false;
  storage.removeItem(key);
  return true;
}
