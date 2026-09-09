import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; productName?: string; retryUrl?: string }

const Email = ({ name, productName, retryUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Your payment didn't go through — your spot is still saved.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, your payment didn't go through.` : 'Your payment didn’t go through.'}</Heading>
        <Text style={text}>
          We tried to process your enrollment in {productName ? productName : 'our program'}, but your bank
          declined the charge. This is almost always fixed by trying the card again, or using a different one.
        </Text>
        <Text style={text}>
          Your spot and pricing are still locked in — it only takes a minute to finish.
        </Text>
        {retryUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={retryUrl} style={btn}>Complete your enrollment</Button>
          </Section>
        ) : null}
        <Text style={text}>
          Reply to this email if you'd like help — we answer every message.
        </Text>
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Action needed: finish your enrollment',
  displayName: 'Payment failed',
  previewData: { name: 'Sam', productName: 'The Edge', retryUrl: 'https://sweepcapitalgroup.com/mentorship' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
