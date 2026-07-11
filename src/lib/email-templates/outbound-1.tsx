import { Body, Container, Head, Html, Preview, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; company?: string }

const Email = ({ name, company }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Quick question about your trading edge</Preview>
    <Body style={main}>
      <Container style={container}>
        <Text style={text}>{name ? `Hey ${name},` : 'Hey,'}</Text>
        <Text style={text}>
          Saw {company ? `${company}` : 'your profile'} and figured I'd reach out. We run a
          mentorship for traders who are tired of guessing — three setups, one framework,
          audited results.
        </Text>
        <Text style={text}>
          Not a pitch — just curious: what's the biggest hole in your trading process right now?
        </Text>
        <Text style={text}>— Sweep Capital Group</Text>
        <Text style={small}>Reply "stop" and I won't message again.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: (d: Record<string, any>) => d.company ? `${d.company} — quick trading question` : 'Quick trading question',
  displayName: 'Outbound · Step 1',
  previewData: { name: 'Sam', company: 'Acme' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '11px', color: '#999', marginTop: '20px' }
