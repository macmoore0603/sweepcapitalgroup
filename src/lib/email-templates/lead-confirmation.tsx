import {
  Body,
  Button,
  Container,
  Head,
  Heading,
  Html,
  Preview,
  Section,
  Text,
} from '@react-email/components'
import type { TemplateEntry } from './registry'

const SITE_NAME = 'Sweep Capital Group'

interface LeadConfirmationProps {
  name?: string
  tier?: string
  bookingUrl?: string
}

const LeadConfirmationEmail = ({ name, tier, bookingUrl }: LeadConfirmationProps) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Pick a time for your onboarding call — takes 30 seconds.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>
          {name ? `Thanks, ${name}.` : 'Thanks for reaching out.'}
        </Heading>
        <Text style={text}>
          We received your inquiry at {SITE_NAME}. Before we can confirm details and
          arrange payment, please book a 30-minute onboarding call so we can review
          your goals and walk you through the program.
        </Text>

        {tier ? (
          <Section style={card}>
            <Text style={cardLabel}>Selected option</Text>
            <Text style={cardValue}>{tier}</Text>
          </Section>
        ) : null}

        {bookingUrl ? (
          <Section style={ctaSection}>
            <Text style={ctaLabel}>Next step</Text>
            <Heading as="h2" style={ctaHeading}>
              Schedule your onboarding call
            </Heading>
            <Text style={text}>
              Pick a slot that works for you — your link is personal, no login needed.
            </Text>
            <Button href={bookingUrl} style={button}>
              Pick a time →
            </Button>
            <Text style={smallMuted}>
              Or paste this link into your browser:
              <br />
              {bookingUrl}
            </Text>
          </Section>
        ) : null}

        <Heading as="h2" style={h2}>What happens next</Heading>
        <Text style={text}>
          1. You book your onboarding call using the link above.
        </Text>
        <Text style={text}>
          2. On the call we confirm fit, answer your questions, and walk through the
          program structure.
        </Text>
        <Text style={text}>
          3. After the call, you'll receive a secure payment link. Once payment clears
          you get immediate access to course materials and your first 1-on-1 session.
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
      ? `Book your onboarding call — ${data.tier}`
      : 'Book your onboarding call',
  displayName: 'Lead confirmation',
  previewData: {
    name: 'Jane Doe',
    tier: 'Course + Coaching — $1,500',
    bookingUrl: 'https://sweepcapitalgroup.com/book?lead=preview&token=preview',
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
const ctaSection = {
  border: '1px solid #0a0a0a',
  padding: '24px 22px',
  margin: '24px 0 8px',
  backgroundColor: '#fafafa',
}
const ctaLabel = {
  fontSize: '11px',
  color: '#0a0a0a',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.12em',
  margin: '0 0 6px',
  fontWeight: 'bold' as const,
}
const ctaHeading = {
  fontSize: '18px',
  fontWeight: 'bold' as const,
  color: '#0a0a0a',
  margin: '0 0 10px',
}
const button = {
  backgroundColor: '#0a0a0a',
  color: '#ffffff',
  fontSize: '13px',
  fontWeight: 'bold' as const,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.1em',
  padding: '14px 24px',
  textDecoration: 'none',
  display: 'inline-block',
  margin: '8px 0 16px',
}
const smallMuted = {
  fontSize: '11px',
  color: '#888',
  lineHeight: '1.5',
  margin: '0',
  wordBreak: 'break-all' as const,
}
const footer = {
  fontSize: '12px',
  color: '#888',
  margin: '32px 0 0',
  lineHeight: '1.6',
}
