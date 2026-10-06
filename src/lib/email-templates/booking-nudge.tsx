import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; bookingUrl?: string }

const Email = ({ name, bookingUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Your onboarding call spot is still open — pick a time.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, you're one step away.` : "You're one step away."}</Heading>
        <Text style={text}>
          Thanks for applying to Sweep Capital Group. You haven't picked a time for your quick
          onboarding call yet — it's 15 minutes, and it's where we figure out which path fits you.
        </Text>
        {bookingUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={bookingUrl} style={btn}>Pick my call time</Button>
          </Section>
        ) : null}
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Your onboarding call is still unbooked',
  displayName: 'Booking Nudge',
  previewData: { name: 'Sam', bookingUrl: 'https://sweepcapitalgroup.com/book' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
