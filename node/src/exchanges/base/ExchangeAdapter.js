import { EventEmitter } from 'node:events';
import WebSocket from 'ws';
import { logger } from '../../config/logger.js';

const MAX_BACKOFF_MS = 30_000;
const HEARTBEAT_INTERVAL_MS = 15_000;
// A connection is considered "healthy" (and resets the reconnect backoff)
// once it has stayed open this long, so a burst of rapid disconnects
// still backs off instead of hammering the exchange.
const HEALTHY_UPTIME_MS = 30_000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Base class every exchange adapter implements. Owns the WebSocket
 * lifecycle (connect, subscribe, heartbeat/staleness detection,
 * exponential-backoff reconnect, graceful stop) so each exchange's
 * adapter only has to implement message parsing. Emits 'orderbook',
 * 'trade', 'connected', 'disconnected' and 'error'.
 */
export class ExchangeAdapter extends EventEmitter {
  constructor({ name, symbols }) {
    super();
    this.name = name;
    this.symbols = symbols;
    this.ws = null;
    this.stopped = true;
    this.backoffMs = 1000;
    this.heartbeatTimer = null;
    this.connected = false;
    this.lastMessageAt = null;
    this._loopPromise = null;
  }

  // ---- to override in subclasses ----
  getWsUrl() {
    throw new Error(`${this.name}: getWsUrl not implemented`);
  }

  getSubscribeMessages() {
    return [];
  }

  // eslint-disable-next-line no-unused-vars
  handleMessage(_raw) {
    throw new Error(`${this.name}: handleMessage not implemented`);
  }

  sendHeartbeat(ws) {
    if (ws.readyState === WebSocket.OPEN) ws.ping();
  }
  // ------------------------------------

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this._loopPromise = this._loop();
  }

  async stop() {
    this.stopped = true;
    this._clearHeartbeat();
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // socket may already be closing/closed
      }
    }
    if (this._loopPromise) {
      await this._loopPromise;
    }
  }

  async _loop() {
    while (!this.stopped) {
      const connectedAt = Date.now();
      try {
        await this._connectOnce();
      } catch (err) {
        // Deliberately NOT re-emitted as an 'error' event: EventEmitter
        // throws synchronously when 'error' has no listener, which would
        // crash the process on every routine reconnect for any consumer
        // that forgot to attach one. The 'disconnected' event (fired from
        // the ws 'close' handler) plus this log line are sufficient -
        // reconnects are expected, not exceptional.
        logger.error(`[${this.name}] connection error: ${err.message}`);
      }
      if (this.stopped) break;
      if (Date.now() - connectedAt > HEALTHY_UPTIME_MS) {
        this.backoffMs = 1000;
      }
      logger.warn(`[${this.name}] reconnecting in ${this.backoffMs}ms`);
      await sleep(this.backoffMs);
      this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
    }
  }

  _connectOnce() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.getWsUrl());
      this.ws = ws;
      let settled = false;
      const settleReject = (err) => {
        if (!settled) {
          settled = true;
          reject(err);
        }
      };

      ws.on('open', () => {
        this.connected = true;
        this.lastMessageAt = Date.now();
        logger.info(`[${this.name}] connected`);
        for (const msg of this.getSubscribeMessages()) {
          ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg));
        }
        this._startHeartbeat(ws);
        this.emit('connected');
      });

      ws.on('message', (raw) => {
        this.lastMessageAt = Date.now();
        try {
          this.handleMessage(raw);
        } catch (err) {
          logger.error(`[${this.name}] failed to handle message: ${err.message}`);
        }
      });

      ws.on('close', (code, reason) => {
        this.connected = false;
        this._clearHeartbeat();
        this.emit('disconnected', { code, reason: reason?.toString() });
        settleReject(new Error(`connection closed (code ${code})`));
      });

      ws.on('error', (err) => {
        this.connected = false;
        settleReject(err);
      });
    });
  }

  _startHeartbeat(ws) {
    this._clearHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      const staleForMs = Date.now() - (this.lastMessageAt ?? 0);
      if (staleForMs > HEARTBEAT_INTERVAL_MS * 2) {
        logger.warn(`[${this.name}] no messages for ${staleForMs}ms, terminating stale connection`);
        ws.terminate();
        return;
      }
      try {
        this.sendHeartbeat(ws);
      } catch {
        // socket may already be closing
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  _clearHeartbeat() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }
}
