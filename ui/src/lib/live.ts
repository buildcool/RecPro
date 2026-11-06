import type { QueryClient } from '@tanstack/react-query';
import { create } from 'zustand';
import { wsUrl } from './api';

export type StageStatus = { done: number; total: number; rate?: number; label: string };
export type IndexStatus = {
  running: boolean;
  paused: boolean;
  phase: string;
  scanning: boolean;
  stages: Record<string, StageStatus>;
  totalMedia: number;
  current?: string | null;
  etaSec?: number | null;
};

export type OpProgress = {
  id: number;
  kind: string;
  status: string;
  title?: string;
  total: number;
  done: number;
  failed: number;
  bytes_total: number;
  bytes_done: number;
  rate?: number;
};

type LiveState = {
  connected: boolean;
  status: IndexStatus | null;
  ops: Record<number, OpProgress>;
  reviewCounts: Record<string, number>;
  privateState: { configured: boolean; unlocked: boolean; blur: boolean; showEverywhere: boolean; expiresAt?: number | null } | null;
};

export const useLive = create<LiveState>(() => ({
  connected: false,
  status: null,
  ops: {},
  reviewCounts: {},
  privateState: null,
}));

type Msg = { type: string; data: unknown };

const INVALIDATE: Record<string, string[][]> = {
  'library.changed': [['folders'], ['media'], ['timeline'], ['stats']],
  'media.updated': [['media'], ['stats'], ['timeline']],
  'people.changed': [['people'], ['person'], ['review'], ['stats']],
  'labels.changed': [['labels'], ['explore'], ['review'], ['stats']],
  'ops.changed': [['ops'], ['bin']],
  'review.changed': [['review'], ['people'], ['person']],
  'private.changed': [['private'], ['media'], ['timeline'], ['people'], ['explore'], ['stats']],
  settings: [['settings']],
  'models.changed': [['models'], ['health']],
};

let started = false;

export function startLive(qc: QueryClient) {
  if (started) return;
  started = true;
  let retry = 500;
  const pending = new Set<string>();
  let flushTimer: number | undefined;

  const scheduleInvalidate = (keys: string[][]) => {
    keys.forEach((k) => pending.add(JSON.stringify(k)));
    if (flushTimer) return;
    flushTimer = window.setTimeout(() => {
      flushTimer = undefined;
      const items = [...pending];
      pending.clear();
      items.forEach((k) => qc.invalidateQueries({ queryKey: JSON.parse(k) }));
    }, 400);
  };

  const connect = () => {
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl());
    } catch {
      setTimeout(connect, retry);
      return;
    }
    ws.onopen = () => {
      retry = 500;
      useLive.setState({ connected: true });
      qc.invalidateQueries();
    };
    ws.onclose = () => {
      useLive.setState({ connected: false });
      retry = Math.min(retry * 2, 5000);
      setTimeout(connect, retry);
    };
    ws.onmessage = (ev) => {
      let msg: Msg;
      try {
        msg = JSON.parse(ev.data as string) as Msg;
      } catch {
        return;
      }
      switch (msg.type) {
        case 'status':
          useLive.setState({ status: msg.data as IndexStatus });
          break;
        case 'op.progress': {
          const op = msg.data as OpProgress;
          useLive.setState((s) => ({ ops: { ...s.ops, [op.id]: op } }));
          if (op.status !== 'running' && op.status !== 'paused') scheduleInvalidate([['ops'], ['bin'], ['media']]);
          break;
        }
        case 'review.counts':
          useLive.setState({ reviewCounts: msg.data as Record<string, number> });
          break;
        case 'private.state':
          useLive.setState({ privateState: msg.data as LiveState['privateState'] });
          scheduleInvalidate(INVALIDATE['private.changed']);
          break;
        default: {
          const keys = INVALIDATE[msg.type];
          if (keys) scheduleInvalidate(keys);
        }
      }
    };
  };
  connect();
}
