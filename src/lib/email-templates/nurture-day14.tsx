import { Body, Button, Container, Head, Heading, Html, Preview, Section, Text } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; siteUrl?: string }

const Email = ({ name, siteUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Final note — then we'll close your file for good.</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>{name ? `${name}, one last note.` : 'One last note.'}</Heading>
        <Text style={text}>
          Two weeks ago you reached out about learning the Session Sweep method. Since then we've
          sent you the playbook and a couple of check-ins — this is the last one.
        </Text>
        <Text style={text}>
          If you still want in, the $500 Edge tier gets you the full course today. If not, no
          worries — we'll close your file and stop emailing you.
        </Text>
        {siteUrl ? (
          <Section style={{ textAlign: 'center' as const, margin: '28px 0' }}>
            <Button href={siteUrl} style={btn}>Get The Edge — $500</Button>
          </Section>
        ) : null}
        <Text style={text}>
          Whatever you decide, thanks for your time. Reply "stop" any time and we'll remove you
          immediately.
        </Text>
        <Text style={small}>Educational content. Not financial advice.</Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Closing your file — final note from Sweep Capital Group',
  displayName: 'Nurture · Day 14',
  previewData: { name: 'Sam', siteUrl: 'https://sweepcapitalgroup.com/' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '24px', maxWidth: '560px', margin: '0 auto' }
const h1 = { fontSize: '24px', color: '#0a0a0a', margin: '0 0 12px' }
const text = { fontSize: '15px', color: '#333', lineHeight: '22px' }
const small = { fontSize: '12px', color: '#888', marginTop: '24px' }
const btn = { backgroundColor: '#c9a55c', color: '#0a0a0a', padding: '12px 24px', borderRadius: '4px', textDecoration: 'none', fontWeight: 700 }
