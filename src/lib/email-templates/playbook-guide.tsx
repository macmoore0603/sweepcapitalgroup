import { Body, Container, Head, Heading, Html, Preview, Section, Text, Link } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props { name?: string; siteUrl?: string; bookingUrl?: string }

const Email = ({ name, siteUrl, bookingUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Your Session Sweep Playbook — three setups, one framework</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>The Session Sweep Playbook</Heading>
        <Text style={text}>{name ? `${name},` : 'Hey,'} here it is — the entire framework we trade, in three parts.</Text>

        <Section style={card}>
          <Text style={h2}>1 · Session Sweep</Text>
          <Text style={text}>
            Price runs the prior session's high or low to take liquidity, then rejects. That sweep is
            your only valid reason to be interested. No sweep, no trade.
          </Text>
        </Section>

        <Section style={card}>
          <Text style={h2}>2 · The 5–15 Gap</Text>
          <Text style={text}>
            After the sweep, drop to the 5m and 15m. You want an inefficiency (gap) left behind by the
            displacement leg. Entry is the retrace into that gap — not the breakout.
          </Text>
        </Section>

        <Section style={card}>
          <Text style={h2}>3 · Power of 3</Text>
          <Text style={text}>
            Accumulation → Manipulation → Distribution. The sweep is the manipulation. You are trading
            the distribution leg only, which is why the stop sits above the sweep wick and the target
            sits at the opposing session liquidity.
          </Text>
        </Section>

        <Text style={text}>
          Keep it simple: one sweep, one gap, one direction per session. Most losing weeks come from
          taking the second and third idea after the first already paid.
        </Text>

        <Text style={text}>
          When you want the full breakdown with live examples and a review of your own chart, book a
          15-minute call: <Link href={bookingUrl || siteUrl || 'https://sweepcapitalgroup.com'} style={link}>
            {bookingUrl ? 'grab a time here' : 'sweepcapitalgroup.com'}
          </Link>.
        </Text>

        <Text style={text}>— Sweep Capital Group</Text>
        <Text style={small}>
          Educational content only. Trading involves substantial risk of loss and is not suitable for everyone.
        </Text>
      </Container>
    </Body>
  </Html>
)

export const template = {
  component: Email,
  subject: 'Your Session Sweep Playbook (inside)',
  displayName: 'Lead Magnet · Session Sweep Playbook',
  previewData: { name: 'Sam', siteUrl: 'https://sweepcapitalgroup.com' },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '28px', maxWidth: '580px', margin: '0 auto' }
const h1 = { fontSize: '22px', color: '#111', margin: '0 0 16px' }
const h2 = { fontSize: '14px', color: '#111', fontWeight: 'bold' as const, margin: '0 0 6px' }
const card = { borderLeft: '3px solid #c8a24a', paddingLeft: '14px', margin: '18px 0' }
const text = { fontSize: '15px', color: '#333', lineHeight: '23px' }
const link = { color: '#8a6d2f' }
const small = { fontSize: '11px', color: '#999', marginTop: '22px' }
