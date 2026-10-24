import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; productName?: string; resumeUrl?: string }

const Email = ({ name, productName, resumeUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Last note from us — your spot closes soon.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, one last note.` : 'One last note.'}</Heading>
        <Text style={text}>
          A couple of days ago you started enrolling in {productName ? productName : 'our program'} and stopped
          before finishing. That's usually one of three things: timing, money, or a question nobody answered.
        </Text>
        <Text style={text}>
          If it's a question, just reply — a real person reads every response. If it's timing, your spot
          stays open a little longer, but cohorts are capped and the price on the page today is the
          lowest it will be.
        </Text>
        {resumeUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={resumeUrl} style={btn}>Finish enrolling</Button>
          </Section>
        ) : null}
        <Text style={text}>
          And if the answer is simply "not for me" — no hard feelings. You won't hear about this again.
        </Text>
        <Text style={small}>Educational content. Not financial advice. Trading involves substantial risk of loss.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Last note — your spot closes soon',
  displayName: 'Abandoned checkout (48h follow-up)',
  previewData: { name: 'Sam', productName: 'The Edge', resumeUrl: 'https://sweepcapitalgroup.com/' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
