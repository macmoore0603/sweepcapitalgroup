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

const SITE_NAME = 'Lexus Nexus Capital Group'

interface LeadConfirmationProps {
  name?: string
  tier?: string
}

const LeadConfirmationEmail = ({ name, tier }: LeadConfirmationProps) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>We received your request — here are your next steps.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>
          {name ? `Thanks, ${name}.` : 'Thanks for reaching out.'}
        </Heading>
        <Text style={text}>
          We received your inquiry at {SITE_NAME}. A member of our team will
          contact you within 24 hours to confirm the details and arrange
          payment.
        </Text>

        {tier ? (
          <Section style={card}>
            <Text style={cardLabel}>Selected option</Text>
            <Text style={cardValue}>{tier}</Text>
          </Section>
        ) : null}

        <Heading as="h2" style={h2}>What happens next</Heading>
        <Text style={text}>
          1. We review your submission and prepare onboarding materials.
        </Text>
        <Text style={text}>
          2. You'll receive a follow-up email with a secure payment link and a
          short intake form (trading experience, goals, schedule).
        </Text>
        <Text style={text}>
          3. Once payment clears, you get immediate access to course materials
          and your first 1-on-1 session is scheduled.
        </Text>

        <Text style={footer}>
          Reply directly to this email if you have any questions.
          <br />— The {SITE_NAME} Team
        </Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: LeadConfirmationEmail,
  subject: (data: Record<string, any>) =>
    data?.tier
      ? `We received your request — ${data.tier}`
      : 'We received your request',
  displayName: 'Lead confirmation',
  previewData: { name: 'Jane Doe', tier: 'Course + Coaching — $1,500' },
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
const text = {
  fontSize: '14px',
  color: '#3a3a3a',
  lineHeight: '1.6',
  margin: '0 0 12px',
}
const card = {
  border: '1px solid #e5e5e5',
  padding: '16px 20px',
  margin: '20px 0 8px',
}
const cardLabel = {
  fontSize: '11px',
  color: '#888',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.1em',
  margin: '0 0 4px',
}
const cardValue = {
  fontSize: '16px',
  fontWeight: 'bold' as const,
  color: '#0a0a0a',
  margin: 0,
}
const footer = {
  fontSize: '12px',
  color: '#888',
  margin: '32px 0 0',
  lineHeight: '1.6',
}
