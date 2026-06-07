import {
  Body,
  Container,
  Head,
  Heading,
  Html,
  Preview,
  Section,
  Text,
} from '@react-email/components'
import type { TemplateEntry } from './registry'

const SITE_NAME = 'Momentum Capital Group'

interface PurchaseConfirmationProps {
  name?: string
  productName?: string
  amount?: string
  reference?: string
}

const PurchaseConfirmationEmail = ({ name, productName, amount, reference }: PurchaseConfirmationProps) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Payment received — welcome to {SITE_NAME}.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>
          {name ? `Thank you, ${name}.` : 'Thank you for your purchase.'}
        </Heading>
        <Text style={text}>
          Your payment has been received. Below is your receipt — keep this email
          for your records.
        </Text>

        <Section style={card}>
          {productName ? (
            <>
              <Text style={cardLabel}>Item</Text>
              <Text style={cardValue}>{productName}</Text>
            </>
          ) : null}
          {amount ? (
            <>
              <Text style={cardLabel}>Amount</Text>
              <Text style={cardValue}>{amount}</Text>
            </>
          ) : null}
          {reference ? (
            <>
              <Text style={cardLabel}>Reference</Text>
              <Text style={cardValueMono}>{reference}</Text>
            </>
          ) : null}
        </Section>

        <Heading as="h2" style={h2}>What happens next</Heading>
        <Text style={text}>
          1. We'll reach out within 24 hours with onboarding details and any
          materials specific to your tier.
        </Text>
        <Text style={text}>
          2. If you haven't already, book your onboarding call using the link
          we sent in your original confirmation email.
        </Text>
        <Text style={text}>
          3. Reply directly to this email if you have any questions.
        </Text>

        <Text style={footer}>
          — The {SITE_NAME} Team
        </Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: PurchaseConfirmationEmail,
  subject: (data: Record<string, any>) =>
    data?.productName ? `Payment received — ${data.productName}` : 'Payment received',
  displayName: 'Purchase confirmation',
  previewData: {
    name: 'Jane Doe',
    productName: 'Course + Coaching',
    amount: '$1,500.00',
    reference: 'cs_test_a1b2c3',
  },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '32px 28px', maxWidth: '560px' }
const h1 = {
  fontSize: '24px',
  fontWeight: 'bold' as const,
  color: '#0a0a0a',
  margin: '0 0 16px',
  letterSpacing: '-0.01em',
}
const h2 = {
  fontSize: '14px',
  fontWeight: 'bold' as const,
  color: '#0a0a0a',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.08em',
  margin: '28px 0 12px',
}
const text = { fontSize: '14px', color: '#3a3a3a', lineHeight: '1.6', margin: '0 0 12px' }
const card = { border: '1px solid #e5e5e5', padding: '16px 20px', margin: '20px 0 8px' }
const cardLabel = {
  fontSize: '11px',
  color: '#888',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.1em',
  margin: '12px 0 4px',
}
const cardValue = { fontSize: '16px', fontWeight: 'bold' as const, color: '#0a0a0a', margin: 0 }
const cardValueMono = {
  fontSize: '12px',
  fontFamily: 'monospace',
  color: '#3a3a3a',
  margin: 0,
  wordBreak: 'break-all' as const,
}
const footer = { fontSize: '12px', color: '#888', margin: '32px 0 0', lineHeight: '1.6' }
