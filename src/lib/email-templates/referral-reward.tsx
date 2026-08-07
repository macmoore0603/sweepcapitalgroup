import { Body, Container, Head, Heading, Html, Preview, Section, Text, Link } from '@react-email/components'
import type { TemplateEntry } from './registry'

interface Props {
  name?: string
  amount?: string
  productName?: string
  referralUrl?: string
  bookingUrl?: string
}

const Email = ({ name, amount, productName, referralUrl, bookingUrl }: Props) => (
  <Html lang="en" dir="ltr">
    <Head />
    <Preview>Someone you referred just joined Sweep Capital Group</Preview>
    <Body style={main}>
      <Container style={container}>
        <Heading style={h1}>Your referral just converted</Heading>
        <Text style={text}>
          {name ? `${name},` : 'Hey,'} someone who used your link just enrolled
          {productName ? ` in ${productName}` : ''}{amount ? ` (${amount})` : ''}.
        </Text>

        <Section style={card}>
          <Text style={text}>
            That is one more trader running the same framework you do — session sweep, the 5–15 gap,
            and Power of 3. Referrals compound: the more people in your circle trading the same
            model, the sharper your own reviews get.
          </Text>
        </Section>

        {referralUrl ? (
          <Section style={referralSection}>
            <Text style={h2}>Keep it going</Text>
            <Text style={text}>Your personal link:</Text>
            <Link href={referralUrl} style={referralLink}>{referralUrl}</Link>
          </Section>
        ) : null}

        {bookingUrl ? (
          <Text style={text}>
            Want your referral credit applied or a review of your own chart?{' '}
            <Link href={bookingUrl} style={link}>Book 15 minutes</Link>.
          </Text>
        ) : null}

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
  subject: 'Your referral just joined Sweep Capital Group',
  displayName: 'Referral · Reward Notice',
  previewData: {
    name: 'Sam',
    amount: '$1,500.00',
    productName: 'The Apprenticeship',
    referralUrl: 'https://sweepcapitalgroup.com/ref/smith7a2b',
  },
} satisfies TemplateEntry

const main = { backgroundColor: '#ffffff', fontFamily: 'Arial, sans-serif' }
const container = { padding: '28px', maxWidth: '580px', margin: '0 auto' }
const h1 = { fontSize: '22px', color: '#111', margin: '0 0 16px' }
const h2 = { fontSize: '14px', color: '#111', fontWeight: 'bold' as const, margin: '0 0 6px' }
const card = { borderLeft: '3px solid #c8a24a', paddingLeft: '14px', margin: '18px 0' }
const text = { fontSize: '15px', color: '#333', lineHeight: '23px' }
const link = { color: '#8a6d2f' }
const small = { fontSize: '11px', color: '#999', marginTop: '22px' }
const referralSection = {
  border: '1px dashed #c8a24a',
  padding: '16px 18px',
  margin: '22px 0',
  backgroundColor: '#faf8f2',
}
const referralLink = { color: '#8a6d2f', fontSize: '13px', wordBreak: 'break-all' as const }
