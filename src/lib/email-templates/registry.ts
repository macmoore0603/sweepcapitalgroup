import type { ComponentType } from 'react'

export interface TemplateEntry {
  component: ComponentType<any>
  subject: string | ((data: Record<string, any>) => string)
  displayName?: string
  previewData?: Record<string, any>
  /** Fixed recipient — overrides caller-provided recipientEmail when set. */
  to?: string
}

import { template as leadConfirmation } from './lead-confirmation'
import { template as purchaseConfirmation } from './purchase-confirmation'
import { template as paymentFailed } from './payment-failed'
import { template as abandonedCheckout } from './abandoned-checkout'
import { template as nurtureDay3 } from './nurture-day3'
import { template as nurtureDay7 } from './nurture-day7'
import { template as nurtureDay14 } from './nurture-day14'
import { template as outbound1 } from './outbound-1'
import { template as outbound2 } from './outbound-2'
import { template as outbound3 } from './outbound-3'
import { template as opsNote } from './ops-note'
import { template as playbookGuide } from './playbook-guide'
import { template as referralReward } from './referral-reward'
import { template as callReminder } from './call-reminder'

export const TEMPLATES: Record<string, TemplateEntry> = {
  'call-reminder': callReminder,
  'lead-confirmation': leadConfirmation,
  'purchase-confirmation': purchaseConfirmation,
  'payment-failed': paymentFailed,
  'abandoned-checkout': abandonedCheckout,
  'nurture-day3': nurtureDay3,
  'nurture-day7': nurtureDay7,
  'nurture-day14': nurtureDay14,
  'outbound-1': outbound1,
  'outbound-2': outbound2,
  'outbound-3': outbound3,
  'ops-note': opsNote,
  'playbook-guide': playbookGuide,
  'referral-reward': referralReward,
}


