/**
 * Binance USDT-M futures diff-depth events carry `pu` (previous update
 * id), which must equal the `u` of the last applied event. A mismatch
 * means a message was dropped/reordered/duplicated and the local book
 * must be resynced from a fresh REST snapshot.
 */
export function hasSequenceGap(event, lastAppliedUpdateId) {
  return event.pu !== lastAppliedUpdateId;
}
