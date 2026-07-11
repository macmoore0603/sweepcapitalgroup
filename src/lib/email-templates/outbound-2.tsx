import { Body, Container, Head, Html, Preview, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string }

const Email = ({ name }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>The three setups our members actually trade</Preview>
    <Body style={main}>
      <Container style={container}>
        <Text style={text}>{name ? `${name},` : 'Following up,'}</Text>
        <Text style={text}>
          Real quick — the three setups we teach: Session Sweep, the 5–15 Gap, and Power of 3.
          That's it. Discipline over volume. Audited win rate, past performance not indicative of future results.
        </Text>
        <Text style={text}>
          If it sounds relevant, the entry tier is $500 and starts this week:
          https://sweepcapitalgroup.com/
        </Text>
        <Text style={text}>— SCG</Text>
        <Text style={small}>Reply "stop" and I'll leave you alone. Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'The three setups (2-min read)',
  displayName: 'Outbound · Step 2',
  previewData: { name: 'Sam' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '11px', color: '#999', marginTop: '20px' }
