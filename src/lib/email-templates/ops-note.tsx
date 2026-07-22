import { Body, Container, Head, Html, Preview, Text, Heading } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; customMessage?: string }

const Email = ({ name, customMessage }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Sweep Capital Agent — ops note</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `Hey ${name},` : 'Ops note'}</Heading>
        <Text style={pre}>{customMessage ?? ''}</Text>
        <Text style={footer}>— Sweep Capital Agent</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Sweep Capital — Ops note',
  displayName: 'Ops note',
  previewData: { name: 'Mac', customMessage: 'Everything nominal.' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '28px', maxWidth: '640px', margin: '0 auto' }
const h1 = { fontSize: '18px', fontWeight: 'bold' as const, color: '#0a0a0a', margin: '0 0 16px' }
const pre = {
  fontSize: '13px',
  color: '#222',
  lineHeight: '1.6',
  whiteSpace: 'pre-wrap' as const,
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  margin: 0,
}
const footer = { fontSize: '11px', color: '#888', marginTop: '24px' }
