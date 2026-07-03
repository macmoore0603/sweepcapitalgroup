import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; siteUrl?: string }

const Email = ({ name, siteUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>The one thing separating consistent traders from everyone else.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, quick note.` : 'Quick note.'}</Heading>
        <Text style={text}>
          Most traders lose because they trade every idea. Our members focus on three setups —
          Session Sweep, the 5–15 Gap, and the Power of 3 — and nothing else. Discipline is the only edge.
        </Text>
        <Text style={text}>
          The full framework is inside our mentorship. If you were on the fence, this is your reminder.
        </Text>
        {siteUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={siteUrl} style={btn}>See the tiers</Button>
          </Section>
        ) : null}
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'The one thing separating consistent traders',
  displayName: 'Nurture · Day 3',
  previewData: { name: 'Sam', siteUrl: 'https://sweepcapitalgroup.com/' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
