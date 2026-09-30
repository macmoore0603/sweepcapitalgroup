import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; callTime?: string; rescheduleUrl?: string }

const Email = ({ name, callTime, rescheduleUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Your call with Sweep Capital Group is tomorrow.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, your call is tomorrow.` : 'Your call is tomorrow.'}</Heading>
        <Text style={text}>
          You're booked in for a quick onboarding call with the Sweep Capital Group team
          {callTime ? ` at ${callTime}` : ''}. Come with your questions — we'll walk you through
          the Session Sweep, the 5–15 Gap, and the Power of 3, and map out which tier fits you best.
        </Text>
        <Text style={text}>
          The call takes about 15 minutes. If the time no longer works, just grab a new slot below —
          it takes ten seconds.
        </Text>
        {rescheduleUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={rescheduleUrl} style={btn}>Reschedule my call</Button>
          </Section>
        ) : null}
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Reminder: your call is tomorrow',
  displayName: 'Call Reminder · 24h',
  previewData: {
    name: 'Sam',
    callTime: 'Tuesday at 2:00 PM ET',
    rescheduleUrl: 'https://sweepcapitalgroup.com/book',
  },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
