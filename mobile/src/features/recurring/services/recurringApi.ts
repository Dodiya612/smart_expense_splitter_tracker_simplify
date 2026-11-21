/**
 * Recurring expense API (T-45 / US-14), backed by T-44's endpoints:
 * - GET  /api/v1/recurring                 my rules (newest first)
 * - POST /api/v1/recurring                 create a rule (Idempotency-Key header)
 * - POST /api/v1/recurring/:id/pause       active -> paused
 * - POST /api/v1/recurring/:id/resume      paused -> active (paused dates are not back-filled)
 * - POST /api/v1/recurring/:id/cancel      final
 * Only the owner can see a rule; anyone else gets 404.
 */

import { fastApiClient } from '@/services/api/fastApiClient';
import type { CreateRecurringRuleBody, RecurringRule, RuleAction } from '../types';
import { mapRule } from '../utils/recurring';

const BASE = '/api/v1/recurring';

export async function listRecurringRules(): Promise<RecurringRule[]> {
  const raw = await fastApiClient.get<{ data?: unknown[] }>(`${BASE}?limit=100`);
  return Array.isArray(raw?.data) ? raw.data.map(mapRule) : [];
}

export async function createRecurringRule(
  body: CreateRecurringRuleBody,
  idempotencyKey: string
): Promise<RecurringRule> {
  const raw = await fastApiClient.post<{ data?: unknown }>(BASE, body, {
    'Idempotency-Key': idempotencyKey,
  });
  return mapRule(raw?.data);
}

export async function changeRecurringRule(ruleId: string, action: RuleAction): Promise<RecurringRule> {
  const raw = await fastApiClient.post<{ data?: unknown }>(
    `${BASE}/${encodeURIComponent(ruleId)}/${action}`
  );
  return mapRule(raw?.data);
}
