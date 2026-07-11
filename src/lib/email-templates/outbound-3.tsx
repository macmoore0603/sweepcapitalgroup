import { Body, Container, Head, Html, Preview, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string }

const Email = ({ name }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Closing your file</Preview>
    <Body style={main}>
      <Container style={container}>
        <Text style={text}>{name ? `${name} —` : 'Hey —'}</Text>
        <Text style={text}>
          Last note. Closing your file after this. If timing's off, no problem. If you want in,
          the door's here: https://sweepcapitalgroup.com/
        </Text>
        <Text style={text}>— SCG</Text>
        <Text style={small}>Reply "stop" to opt out. Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Closing your file',
  displayName: 'Outbound · Step 3',
  previewData: { name: 'Sam' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '11px', color: '#999', marginTop: '20px' }
