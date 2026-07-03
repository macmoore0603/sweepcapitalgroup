import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; siteUrl?: string }

const Email = ({ name, siteUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Last check-in before we close your file.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name} — last check-in.` : 'Last check-in.'}</Heading>
        <Text style={text}>
          It's been a week since you asked about Sweep Capital Group. We're closing your file
          unless you want to move forward. The $500 Edge tier is the fastest way in.
        </Text>
        {siteUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={siteUrl} style={btn}>Enroll now</Button>
          </Section>
        ) : null}
        <Text style={text}>
          No hard feelings if the timing isn't right. Just reply "stop" and we'll leave you alone.
        </Text>
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Last check-in from Sweep Capital Group',
  displayName: 'Nurture · Day 7',
  previewData: { name: 'Sam', siteUrl: 'https://sweepcapitalgroup.com/' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
