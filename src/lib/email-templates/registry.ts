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
import { template as abandonedCheckout } from './abandoned-checkout'
import { template as nurtureDay3 } from './nurture-day3'
import { template as nurtureDay7 } from './nurture-day7'

export const TEMPLATES: Record<string, TemplateEntry> = {
  'lead-confirmation': leadConfirmation,
  'purchase-confirmation': purchaseConfirmation,
  'abandoned-checkout': abandonedCheckout,
  'nurture-day3': nurtureDay3,
  'nurture-day7': nurtureDay7,
}

