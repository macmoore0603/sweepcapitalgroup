export const paymentCatalog = {
  mentorship_course_onetime: { amount: 100000, livePrice: 'price_1UQx947G34ZJ9tfhGzj49VKs', needsApproval: false },
  mentorship_course_coaching_onetime: { amount: 150000, livePrice: 'price_1UaOMy7G34ZJ9tfhUYtlbCkH', needsApproval: false },
  mentorship_managed_onetime: { amount: 100000, livePrice: 'price_1UWStf7G34ZJ9tfh0ax8kTlJ', needsApproval: true },
  mentorship_all_inclusive_onetime: { amount: 200000, livePrice: 'price_1UaON37G34ZJ9tfhQK94aJS3', needsApproval: true },
} as const;

export function getPaymentTier(id: string) {
  if (!Object.prototype.hasOwnProperty.call(paymentCatalog, id)) throw new Error('Unknown program');
  return paymentCatalog[id as keyof typeof paymentCatalog];
}

export function assertProgramAvailable(id: string, environment: 'sandbox' | 'live', approved: boolean) {
  const tier = getPaymentTier(id);
  if (environment === 'live' && tier.needsApproval && !approved) {
    throw new Error('Managed Trading enrollment is unavailable while payment-provider approval is pending.');
  }
  return tier;
}