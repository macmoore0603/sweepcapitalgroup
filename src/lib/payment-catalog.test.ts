import { describe, test, expect } from 'bun:test';
import { getPaymentTier, assertProgramAvailable } from './payment-catalog';

describe('one-time program pricing', () => {
  test('Edge costs $1,000', () => expect(getPaymentTier('mentorship_course_onetime').amount).toBe(100000));
  test('Apprenticeship costs $1,500', () => expect(getPaymentTier('mentorship_course_coaching_onetime').amount).toBe(150000));
  test('Managed Trading costs $1,000', () => expect(getPaymentTier('mentorship_managed_onetime').amount).toBe(100000));
  test('Full Send costs $2,000', () => expect(getPaymentTier('mentorship_all_inclusive_onetime').amount).toBe(200000));
  test('unknown programs cannot be purchased', () => expect(() => getPaymentTier('other')).toThrow());
  test('unapproved managed trading cannot charge live', () => expect(() => assertProgramAvailable('mentorship_managed_onetime', 'live', false)).toThrow());
  test('unapproved bundle cannot charge live', () => expect(() => assertProgramAvailable('mentorship_all_inclusive_onetime', 'live', false)).toThrow());
  test('course does not need managed trading approval', () => expect(assertProgramAvailable('mentorship_course_onetime', 'live', false).amount).toBe(100000));
});