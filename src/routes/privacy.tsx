import { createFileRoute, Link } from "@tanstack/react-router";
import logo from "../assets/lnc-logo.png";

export const Route = createFileRoute("/privacy")({
  head: () => ({
    meta: [
      { title: "Privacy Policy — Momentum Trading" },
      { name: "description", content: "Privacy Policy for Momentum Trading and Sierra messaging services." },
      { property: "og:title", content: "Privacy Policy — Momentum Trading" },
      { property: "og:description", content: "Privacy Policy for Momentum Trading and Sierra messaging services." },
      { name: "robots", content: "index, follow" },
    ],
  }),
  component: PrivacyPage,
});

function PrivacyPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Momentum Trading logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Momentum</span>
        </Link>
        <span className="font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5 uppercase tracking-widest">
          Privacy Policy
        </span>
      </header>

      <main className="px-6 md:px-10 py-16 md:py-24 max-w-3xl mx-auto">
        <div className="flex flex-col gap-6 mb-16">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Legal</span>
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">Privacy Policy</h1>
          <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
            Last updated: May 23, 2026
          </p>
        </div>

        <div className="space-y-16">
          <Section title="Introduction">
            <p>
              Momentum Trading (“Momentum”, “we”, “us”, or “our”) respects your privacy and is committed to protecting your personal data. This Privacy Policy explains how we collect, use, store, and protect information when you use our website, services, or communicate with Sierra, our AI assistant via SMS, voice, or other messaging channels.
            </p>
            <p>
              By accessing or using our services, you consent to the practices described in this Privacy Policy. If you do not agree with any part of this policy, please do not use our services.
            </p>
          </Section>

          <Section title="Information We Collect">
            <p>We collect the following types of information:</p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li><strong>Contact Information:</strong> Your name, email address, phone number, and any other information you provide when filling out forms, applying for mentorship, or communicating with Sierra.</li>
              <li><strong>Message Content:</strong> Text messages, voice transcriptions, and any media you send to or receive from Sierra.</li>
              <li><strong>Technical Information:</strong> IP address, browser type, device information, operating system, and cookies or similar tracking technologies.</li>
              <li><strong>Usage Data:</strong> Pages visited, time spent on site, referral sources, and interaction patterns with Sierra.</li>
              <li><strong>Transaction Data:</strong> Payment and billing information when you purchase services through our platform.</li>
            </ul>
          </Section>

          <Section title="How We Use Your Information">
            <p>We use the information we collect for the following purposes:</p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li>To provide, operate, and maintain our services, including responding to your inquiries via Sierra.</li>
              <li>To process applications for our mentorship and trading programs.</li>
              <li>To schedule and confirm appointments, calls, and consultations.</li>
              <li>To send you transactional messages, reminders, and service-related updates via SMS, email, or voice.</li>
              <li>To improve our AI assistant’s accuracy and performance.</li>
              <li>To comply with legal obligations and enforce our Terms &amp; Conditions.</li>
              <li>To detect, prevent, and address fraud, abuse, or security issues.</li>
            </ul>
          </Section>

          <Section title="SMS & Messaging">
            <p>
              When you communicate with Sierra via SMS or voice, your phone number and message content are transmitted through Twilio, our messaging service provider. Standard message and data rates may apply based on your carrier plan.
            </p>
            <p>
              <strong>Opt-Out:</strong> You may stop receiving SMS messages from us at any time by replying <strong>STOP</strong> to any message from Sierra, or by contacting us at the email or phone number below. After opting out, you will receive a confirmation message and no further messages unless you re-subscribe.
            </p>
            <p>
              <strong>Help:</strong> Reply <strong>HELP</strong> to any message for assistance, or contact us directly.
            </p>
          </Section>

          <Section title="Data Sharing & Third Parties">
            <p>
              We do not sell your personal information. We may share your information with trusted third-party service providers who help us operate our business, including:
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li><strong>Twilio</strong> — for SMS, voice, and messaging infrastructure.</li>
              <li><strong>Stripe</strong> — for payment processing.</li>
              <li><strong>Supabase</strong> — for secure data storage and authentication.</li>
              <li><strong>OpenAI / Google</strong> — for AI model processing (message content is processed to generate responses).</li>
            </ul>
            <p>
              All third-party providers are contractually obligated to protect your data and may only use it for the specific services they provide to us.
            </p>
          </Section>

          <Section title="Data Security">
            <p>
              We implement industry-standard security measures to protect your information, including encryption at rest and in transit, access controls, and regular security audits. Access tokens for social media accounts and messaging APIs are encrypted using AES-256-GCM before storage.
            </p>
            <p>
              While we strive to use commercially acceptable means to protect your personal data, no method of transmission over the internet or electronic storage is 100% secure.
            </p>
          </Section>

          <Section title="Data Retention">
            <p>
              We retain your personal information for as long as necessary to fulfill the purposes outlined in this Privacy Policy, unless a longer retention period is required or permitted by law. Message history with Sierra is retained to maintain conversation context and improve service quality.
            </p>
            <p>
              You may request deletion of your data at any time by contacting us. We will comply unless retention is required for legal, security, or operational reasons.
            </p>
          </Section>

          <Section title="Your Rights">
            <p>Depending on your jurisdiction, you may have the right to:</p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li>Access the personal data we hold about you.</li>
              <li>Request correction of inaccurate or incomplete data.</li>
              <li>Request deletion of your personal data.</li>
              <li>Object to or restrict certain processing activities.</li>
              <li>Withdraw consent where processing is based on consent.</li>
              <li>Lodge a complaint with a data protection authority.</li>
            </ul>
            <p>
              To exercise any of these rights, please contact us using the information below.
            </p>
          </Section>

          <Section title="Children's Privacy">
            <p>
              Our services are not directed to individuals under the age of 18. We do not knowingly collect personal information from children. If we become aware that a child has provided us with personal information, we will take steps to delete such information.
            </p>
          </Section>

          <Section title="Changes to This Policy">
            <p>
              We may update this Privacy Policy from time to time to reflect changes in our practices or legal requirements. We will notify you of any material changes by posting the updated policy on this page with a new effective date. Your continued use of our services after any changes constitutes acceptance of the revised policy.
            </p>
          </Section>

          <Section title="Contact Us">
            <p>
              If you have any questions, concerns, or requests regarding this Privacy Policy or your personal data, please contact us:
            </p>
            <div className="mt-4 space-y-2 font-mono text-sm">
              <p><strong>Momentum Trading</strong></p>
              <p>1131 Oaklake Terrace</p>
              <p>Watkinsville, GA 30677</p>
              <p>Email: <a href="mailto:mac@momentumcapitalgroup.com" className="text-accent hover:underline">mac@momentumcapitalgroup.com</a></p>
              <p>Phone: <a href="tel:+14782978388" className="text-accent hover:underline">(478) 297-8388</a></p>
            </div>
          </Section>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Momentum Trading logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Momentum Trading — Atlanta, GA</span>
          </div>
          <div className="flex gap-6">
            <Link to="/terms" className="hover:text-foreground transition-colors">Terms</Link>
            <Link to="/privacy" className="hover:text-foreground transition-colors">Privacy</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-extrabold uppercase tracking-tight">{title}</h2>
      <div className="text-muted-foreground text-sm leading-relaxed space-y-3">
        {children}
      </div>
    </section>
  );
}
