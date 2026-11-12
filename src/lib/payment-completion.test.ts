import { expect, test } from 'bun:test';
import { completePaidPurchase } from './payment-completion.server';

test('Cloud or email failure is logged without rejecting fulfillment', async () => {
  const steps: string[] = [];
  const failure = new Error('Email unavailable');
  const logged: unknown[] = [];
  await completePaidPurchase(
    async () => { steps.push('fulfilled'); },
    async () => { steps.push('email'); throw failure; },
    (error) => { logged.push(error); },
  );
  expect(steps).toEqual(['fulfilled', 'email']);
  expect(logged).toEqual([failure]);
});

test('optional email enqueue remains available after fulfillment', async () => {
  const steps: string[] = [];
  await completePaidPurchase(
    async () => { steps.push('fulfilled'); },
    async () => { steps.push('email queued'); },
    () => { steps.push('unexpected failure'); },
  );
  expect(steps).toEqual(['fulfilled', 'email queued']);
});