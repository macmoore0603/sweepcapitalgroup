import { createFileRoute, Link } from "@tanstack/react-router";
import logo from "../assets/lnc-logo.png";

export const Route = createFileRoute("/terms")({
  head: () => ({
    meta: [
      { title: "Terms & Conditions — Lexus Nexus Capital Group" },
      { name: "description", content: "Terms and Conditions for Lexus Nexus Capital Group and Sierra messaging services." },
      { property: "og:title", content: "Terms & Conditions — Lexus Nexus Capital Group" },
      { property: "og:description", content: "Terms and Conditions for Lexus Nexus Capital Group and Sierra messaging services." },
      { name: "robots", content: "index, follow" },
    ],
  }),
  component: TermsPage,
});

function TermsPage() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="sticky top-0 z-50 flex items-center justify-between px-6 md:px-10 py-5 bg-background/80 backdrop-blur-md border-b border-border">
        <Link to="/" className="flex items-center gap-3">
          <img src={logo} alt="Lexus Nexus Capital Group logo" width={32} height={32} className="h-8 w-8 object-contain" />
          <span className="font-extrabold tracking-tighter text-xl uppercase">Lexus Nexus</span>
        </Link>
        <span className="font-mono text-[10px] text-accent border border-accent/40 px-1.5 py-0.5 uppercase tracking-widest">
          Terms & Conditions
        </span>
      </header>

      <main className="px-6 md:px-10 py-16 md:py-24 max-w-3xl mx-auto">
        <div className="flex flex-col gap-6 mb-16">
          <span className="font-mono text-accent text-[11px] uppercase tracking-[0.3em]">Legal</span>
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tighter uppercase">Terms & Conditions</h1>
          <p className="font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
            Last updated: May 23, 2026
          </p>
        </div>

        <div className="space-y-16">
          <Section title="Agreement to Terms">
            <p>
              These Terms and Conditions (“Terms”, “Agreement”) constitute a legally binding agreement between you (“User”, “you”, or “your”) and Lexus Nexus Capital Group (“Lexus Nexus”, “we”, “us”, or “our”) regarding your access to and use of our website, applications, AI assistant Sierra, and all related services (collectively, the “Services”).
            </p>
            <p>
              By accessing or using our Services, you agree to be bound by these Terms. If you do not agree to all of the Terms, you may not access or use the Services.
            </p>
          </Section>

          <Section title="Description of Services">
            <p>Lexus Nexus Capital Group provides the following:</p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li>Institutional-grade trading mentorship and education programs.</li>
              <li>Capital allocation and proprietary desk funding for qualified traders.</li>
              <li>AI-powered concierge assistance through Sierra, accessible via SMS, voice, and messaging platforms.</li>
              <li>Social media content management and scheduling services for brand presence.</li>
              <li>Educational resources, market analysis, and community access.</li>
            </ul>
            <p>
              Sierra is an AI assistant designed to help you schedule tasks, set reminders, manage social media posts, search for information, and communicate via email on your behalf. Sierra operates under your explicit direction and does not make independent financial or investment decisions.
            </p>
          </Section>

          <Section title="Eligibility">
            <p>
              You must be at least 18 years of age to use our Services. By using our Services, you represent and warrant that you are of legal age and have the capacity to enter into this Agreement. Our trading mentorship programs are intended for individuals with sufficient capital and risk tolerance. We do not guarantee returns, and all trading involves substantial risk of loss.
            </p>
          </Section>

          <Section title="SMS & Messaging Terms">
            <p>
              By providing your phone number and communicating with Sierra, you consent to receive SMS messages, voice calls, and other electronic communications from us related to the Services.
            </p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li><strong>Message Frequency:</strong> Message frequency varies based on your interaction with Sierra. You may receive automated reminders, confirmations, and responses to your inquiries.</li>
              <li><strong>Carrier Rates:</strong> Standard messaging and data rates may apply from your wireless carrier. You are responsible for any fees charged by your carrier.</li>
              <li><strong>Opt-Out:</strong> You may opt out of SMS communications at any time by replying <strong>STOP</strong> to any message. You will receive a confirmation and no further messages unless you re-engage.</li>
              <li><strong>Help:</strong> Reply <strong>HELP</strong> for assistance, or contact us directly at the information provided below.</li>
            </ul>
            <p>
              We use Twilio as our messaging infrastructure provider. Message delivery is subject to carrier availability and network conditions. We are not liable for delayed or undelivered messages.
            </p>
          </Section>

          <Section title="User Conduct & Acceptable Use">
            <p>You agree not to use our Services to:</p>
            <ul className="list-disc pl-5 space-y-2 mt-3">
              <li>Violate any applicable law, regulation, or third-party right.</li>
              <li>Transmit unlawful, fraudulent, defamatory, obscene, or harassing content.</li>
              <li>Impersonate any person or entity, or misrepresent your affiliation.</li>
              <li>Interfere with or disrupt the Services or servers connected to the Services.</li>
              <li>Attempt to gain unauthorized access to any part of the Services.</li>
              <li>Use automated systems (bots, scrapers) to access the Services without permission.</li>
              <li>Exploit Sierra to send unsolicited commercial messages (spam) to third parties.</li>
            </ul>
            <p>
              We reserve the right to suspend or terminate your access to the Services if we determine, in our sole discretion, that you have violated these terms.
            </p>
          </Section>

          <Section title="Intellectual Property">
            <p>
              All content, trademarks, logos, software, and materials available through our Services are the property of Lexus Nexus Capital Group or its licensors and are protected by copyright, trademark, and other intellectual property laws. You may not reproduce, distribute, modify, or create derivative works without our express written permission.
            </p>
            <p>
              You retain ownership of any content you submit to Sierra or through our Services. By submitting content, you grant us a limited, non-exclusive license to use, store, and process that content solely for the purpose of providing the Services.
            </p>
          </Section>

          <Section title="Disclaimer of Warranties">
            <p>
              OUR SERVICES ARE PROVIDED ON AN “AS IS” AND “AS AVAILABLE” BASIS WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED. TO THE FULLEST EXTENT PERMITTED BY LAW, WE DISCLAIM ALL WARRANTIES, INCLUDING BUT NOT LIMITED TO IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
            </p>
            <p>
              We do not warrant that the Services will be uninterrupted, error-free, secure, or free from viruses or other harmful components. Trading mentorship and educational content is for informational purposes only and does not constitute financial advice. Past performance is not indicative of future results.
            </p>
          </Section>

          <Section title="Limitation of Liability">
            <p>
              TO THE MAXIMUM EXTENT PERMITTED BY LAW, LEXUS NEXUS CAPITAL GROUP, ITS OFFICERS, DIRECTORS, EMPLOYEES, AND AFFILIATES SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF PROFITS, DATA, OR GOODWILL, ARISING OUT OF OR RELATING TO YOUR USE OF OR INABILITY TO USE THE SERVICES.
            </p>
            <p>
              Our total cumulative liability to you for any claim arising from these Terms or the Services shall not exceed the greater of (a) the amount you paid us in the twelve (12) months preceding the claim, or (b) one hundred U.S. dollars ($100).
            </p>
          </Section>

          <Section title="Indemnification">
            <p>
              You agree to indemnify, defend, and hold harmless Lexus Nexus Capital Group and its officers, directors, employees, and agents from any claims, damages, losses, liabilities, costs, and expenses (including reasonable attorneys' fees) arising out of or relating to your use of the Services, violation of these Terms, or infringement of any third-party right.
            </p>
          </Section>

          <Section title="Governing Law & Dispute Resolution">
            <p>
              These Terms shall be governed by and construed in accordance with the laws of the State of Georgia, United States, without regard to its conflict of law provisions. Any dispute arising under these Terms shall be resolved exclusively in the state or federal courts located in Clarke County, Georgia.
            </p>
          </Section>

          <Section title="Termination">
            <p>
              We may terminate or suspend your access to the Services at any time, with or without cause, and with or without notice. Upon termination, all licenses and rights granted to you under these Terms will immediately cease. Provisions that by their nature should survive termination shall survive, including but not limited to intellectual property, disclaimers, limitation of liability, and indemnification provisions.
            </p>
          </Section>

          <Section title="Changes to Terms">
            <p>
              We reserve the right to modify these Terms at any time. Changes will be effective immediately upon posting to this page with an updated effective date. Your continued use of the Services after changes constitutes acceptance of the revised Terms. We encourage you to review this page periodically.
            </p>
          </Section>

          <Section title="Severability">
            <p>
              If any provision of these Terms is held to be invalid, illegal, or unenforceable by a court of competent jurisdiction, the remaining provisions shall continue in full force and effect.
            </p>
          </Section>

          <Section title="Entire Agreement">
            <p>
              These Terms, together with our Privacy Policy and any other policies referenced herein, constitute the entire agreement between you and Lexus Nexus Capital Group regarding the Services and supersede all prior agreements, understandings, and communications.
            </p>
          </Section>

          <Section title="Contact Us">
            <p>
              If you have any questions about these Terms, please contact us:
            </p>
            <div className="mt-4 space-y-2 font-mono text-sm">
              <p><strong>Lexus Nexus Capital Group</strong></p>
              <p>1131 Oaklake Terrace</p>
              <p>Watkinsville, GA 30677</p>
              <p>Email: <a href="mailto:mac@lexusnexuscapital.com" className="text-accent hover:underline">mac@lexusnexuscapital.com</a></p>
              <p>Phone: <a href="tel:+14782978388" className="text-accent hover:underline">(478) 297-8388</a></p>
            </div>
          </Section>
        </div>
      </main>

      {/* Footer */}
      <footer className="px-6 md:px-10 py-10 border-t border-border">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-center gap-6 font-mono text-[10px] text-muted-foreground uppercase tracking-widest">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Lexus Nexus Capital Group logo" width={24} height={24} className="h-6 w-6 object-contain opacity-60" />
            <span>© 2026 Lexus Nexus Capital Group — Atlanta, GA</span>
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
