import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; productName?: string; resumeUrl?: string }

const Email = ({ name, productName, resumeUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Your Sweep Capital Group enrollment is still open.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, you left something behind.` : 'You left something behind.'}</Heading>
        <Text style={text}>
          You started enrolling in {productName ? productName : 'our program'} but didn't finish.
          Seats are limited and priced to move — the same offer won't be here forever.
        </Text>
        {resumeUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={resumeUrl} style={btn}>Resume enrollment</Button>
          </Section>
        ) : null}
        <Text style={text}>
          Reply to this email if a question is holding you back — we answer every one.
        </Text>
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Your enrollment is still open',
  displayName: 'Abandoned checkout',
  previewData: { name: 'Sam', productName: 'The Edge', resumeUrl: 'https://sweepcapitalgroup.com/' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
