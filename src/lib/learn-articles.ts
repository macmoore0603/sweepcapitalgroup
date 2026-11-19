export const LEARN_BASE_URL = "https://sweepcapitalgroup.com";

export type LearnSection = { h2: string; paragraphs: string[]; bullets?: string[] };
export type LearnFaq = { q: string; a: string };
export type LearnArticle = {
  slug: string;
  kicker: string;
  title: string;
  metaTitle: string;
  metaDescription: string;
  intro: string;
  readMinutes: number;
  published: string;
  sections: LearnSection[];
  faq: LearnFaq[];
};

export const LEARN_ARTICLES: LearnArticle[] = [
  {
    slug: "pass-futures-prop-firm-evaluation",
    kicker: "Prop firms",
    title: "How to Pass a Futures Prop Firm Evaluation (Without Gambling the Account)",
    metaTitle: "How to Pass a Futures Prop Firm Evaluation | Sweep Capital",
    metaDescription:
      "Drawdown types, daily loss limits, consistency rules, and a step-by-step plan for futures prop firm evaluations. Built around risk, not luck.",
    intro:
      "Most traders who fail a futures prop firm evaluation don't fail because they can't find a trade. They fail because they misread the drawdown rule, size up after a red day, or try to hit the profit target in one session. This guide walks through how evaluations are typically structured and a plan that treats the rules as the strategy.",
    readMinutes: 8,
    published: "2026-11-19",
    sections: [
      {
        h2: "How a futures evaluation usually works",
        paragraphs: [
          "An evaluation (sometimes called a challenge or combine) gives you a simulated account with a profit target and a set of loss limits. Hit the target without breaking a rule and you move to a funded or payout stage. Break one rule once and the account is usually done.",
          "Every firm words its rules differently and changes them over time, so always read the current rulebook for the exact account you buy. The categories, though, are close to universal:",
        ],
        bullets: [
          "Profit target: the amount you need to gain before you pass.",
          "Maximum drawdown: how far the account can fall from a reference point before it fails.",
          "Daily loss limit: a cap on how much you can lose in a single session (not every firm uses one).",
          "Consistency rule: limits how much of your total profit can come from your single best day.",
          "Minimum trading days, contract limits, and rules around news events or holding positions past the session close.",
        ],
      },
      {
        h2: "Know which drawdown you're trading under",
        paragraphs: [
          "This is the rule that ends the most accounts. A static drawdown is fixed from your starting balance. A trailing drawdown follows your highest balance upward, which means open profit you give back can count against you. An end-of-day trailing drawdown only updates at the close, which is more forgiving intraday but still ratchets up after green days.",
          "Before your first trade, write down in dollars exactly where your account fails today, and how that number moves after a winning day. If you can't state it from memory, you aren't ready to place a trade.",
        ],
      },
      {
        h2: "Size every trade from the drawdown, not from the target",
        paragraphs: [
          "Work backwards. If your remaining drawdown is $2,000, risking $1,000 on one idea means two losses end the evaluation. Risking $200 means you can be wrong ten times in a row and still be in the game.",
          "A common rule of thumb is to risk a small, fixed fraction of the remaining drawdown per trade and set a personal daily stop well inside the firm's daily limit. Micro contracts (MES, MNQ) make this much easier because each point is worth a tenth of the full-size contract.",
        ],
        bullets: [
          "Pick a max risk per trade in dollars and convert it to ticks for your contract before the session.",
          "Set a personal daily stop that is smaller than the firm's daily loss limit.",
          "Stop for the day after two losing trades, regardless of how good the next setup looks.",
        ],
      },
      {
        h2: "Treat the profit target as a pace, not a deadline",
        paragraphs: [
          "If the target is $3,000 and there is no time limit, $300 a day over ten sessions is a very different risk profile than $3,000 in one. Consistency rules exist precisely to discourage the one-big-day approach.",
          "Pick a realistic daily goal, and when you reach it, stop. Giving back a good day by overtrading is one of the most common ways traders turn a passing account into a failed one.",
        ],
      },
      {
        h2: "Trade one setup you can define in writing",
        paragraphs: [
          "An evaluation is the worst place to experiment. Choose one setup with a written entry condition, a written invalidation, and a written reason to skip the session entirely. At Sweep Capital Group we teach this with the Session Sweep framework: map the prior session's high and low, wait for liquidity there to be taken, and only then look for a return with the stop defined first.",
          "Whatever framework you use, the test is simple: could someone else read your notes and know exactly when you would and would not trade?",
        ],
      },
      {
        h2: "A simple evaluation checklist",
        paragraphs: ["Run this before every session of your evaluation:"],
        bullets: [
          "Where does my account fail today, in dollars?",
          "What is my max loss for this trade and this day?",
          "Is there scheduled high-impact news, and what do the firm's rules say about it?",
          "What does my setup need to see before I'm allowed to enter?",
          "When am I done for the day, win or lose?",
        ],
      },
    ],
    faq: [
      {
        q: "What is the hardest rule in a futures prop firm evaluation?",
        a: "For most traders it's the trailing drawdown, because it moves up with your highest balance and open profit you give back can count against you. Know exactly how your firm calculates it before you trade.",
      },
      {
        q: "Should I use micro contracts for an evaluation?",
        a: "Micros such as MES and MNQ are worth one-tenth of the full-size contract per point, which makes it much easier to size small relative to your drawdown. Many traders start there for that reason.",
      },
      {
        q: "Can a course guarantee I pass an evaluation?",
        a: "No. Nobody can guarantee a pass or a payout. Education can help you understand the rules and build a repeatable risk process, but results depend on the market and your own execution.",
      },
    ],
  },
  {
    slug: "opening-range-breakout-strategy",
    kicker: "Strategy",
    title: "Opening Range Breakout (ORB) Strategy Explained for Futures Traders",
    metaTitle: "Opening Range Breakout (ORB) Strategy Explained | Sweep Capital",
    metaDescription:
      "What the opening range is, how ORB setups are defined on ES and NQ, where stops usually go, and why false breakouts matter. A plain-English guide.",
    intro:
      "The opening range breakout is one of the oldest intraday ideas in futures: let the market show you its first range of the regular session, then pay attention when price leaves it. It's simple to describe and easy to trade badly. Here is how traders usually define it and the parts most beginners skip.",
    readMinutes: 7,
    published: "2026-11-19",
    sections: [
      {
        h2: "What is the opening range?",
        paragraphs: [
          "The opening range is the high and low price reached in the first few minutes after a session opens. For U.S. equity index futures such as ES and NQ, most traders anchor it to the 9:30 AM ET cash open, and use the first 5, 15, or 30 minutes.",
          "A shorter range (5 minutes) gives earlier signals and more false starts. A longer range (30 minutes) gives fewer signals and usually wider stops. There is no single correct window; the point is to pick one and keep it fixed so your results are comparable.",
        ],
      },
      {
        h2: "How a basic ORB setup is defined",
        paragraphs: ["A typical rule set looks like this. Every part should be written before the session starts:"],
        bullets: [
          "Range: mark the high and low of the chosen opening window.",
          "Trigger: a candle close beyond the range high (long idea) or below the range low (short idea), rather than a single tick through.",
          "Stop: commonly the opposite side of the range or its midpoint. A wide range can make the dollar risk too large for your account, and that is a valid reason to skip.",
          "Target: a fixed multiple of risk, a prior-day level, or a time-based exit.",
          "Session limits: how many attempts you allow (many traders allow one or two), and a time after which you stop taking ORB signals.",
        ],
      },
      {
        h2: "The false breakout problem",
        paragraphs: [
          "The most common ORB failure is the breakout that immediately reverses back into the range. The opening range highs and lows are obvious levels, which means stop orders and breakout entries tend to cluster just beyond them.",
          "That is why we teach traders to watch what price does after it takes an obvious level. In the Session Sweep framework, a run through a prior high or low followed by a return is a reason to be interested in the other direction, with risk defined first. Whether you trade the breakout or the failed breakout, having a written answer for both cases keeps you from improvising.",
        ],
      },
      {
        h2: "Filters traders commonly add",
        paragraphs: ["None of these guarantee anything, but they help you decide when the setup simply isn't worth taking:"],
        bullets: [
          "Range size: skip if the opening range is so wide that the stop exceeds your max risk per trade.",
          "News: be aware of scheduled releases (CPI, FOMC, jobs reports) that can create sudden volatility.",
          "Context: where is price relative to the prior day's high, low, and close?",
          "Time: many ORB traders stop looking for new entries by late morning ET.",
        ],
      },
      {
        h2: "How to evaluate an ORB plan honestly",
        paragraphs: [
          "Write the rules down, then review a decent sample of past sessions and journal what the rules would have done, including the sessions you would have skipped. Be wary of tweaking the range length or targets until the past looks perfect; that usually produces a plan fitted to history rather than one that holds up.",
          "Hypothetical or backtested results have real limitations: they do not include the emotional pressure of live trading, and they are often designed with the benefit of hindsight.",
        ],
      },
    ],
    faq: [
      {
        q: "What time frame is best for an opening range breakout?",
        a: "Common choices for ES and NQ are the first 5, 15, or 30 minutes after the 9:30 AM ET open. Shorter windows trigger earlier with more false breakouts; longer windows trigger less often with wider stops. Consistency matters more than the specific choice.",
      },
      {
        q: "Where do traders put the stop on an ORB trade?",
        a: "Often at the opposite side of the opening range or at its midpoint. If that distance is more than you're willing to risk on one trade, the usual answer is to skip it or trade a smaller contract such as a micro.",
      },
      {
        q: "Is the opening range breakout profitable?",
        a: "No strategy is reliably profitable for everyone. Outcomes depend on market conditions, execution, costs, and risk control. Treat ORB as a framework to test and journal, not a promise.",
      },
    ],
  },
  {
    slug: "futures-trading-risk-management-beginners",
    kicker: "Risk management",
    title: "Futures Trading for Beginners: Risk Management First",
    metaTitle: "Futures Risk Management for Beginners | Sweep Capital Group",
    metaDescription:
      "Tick values for ES, NQ, MES and MNQ, how to size a position from your stop, daily loss limits, and why leverage cuts both ways. Start here.",
    intro:
      "Futures are leveraged. A small margin deposit controls a much larger contract value, so a modest move in price can mean a large gain or loss relative to your account. Before you study a single entry pattern, learn the math of risk. It's the part that keeps you in the game long enough to learn anything else.",
    readMinutes: 7,
    published: "2026-11-19",
    sections: [
      {
        h2: "Know what one tick is worth",
        paragraphs: [
          "Every futures contract has a minimum price move (a tick) and a fixed dollar value per tick. For the most popular U.S. equity index contracts:",
        ],
        bullets: [
          "ES (E-mini S&P 500): 0.25-point tick = $12.50, so 1 point = $50.",
          "MES (Micro E-mini S&P 500): 0.25-point tick = $1.25, so 1 point = $5.",
          "NQ (E-mini Nasdaq-100): 0.25-point tick = $5.00, so 1 point = $20.",
          "MNQ (Micro E-mini Nasdaq-100): 0.25-point tick = $0.50, so 1 point = $2.",
        ],
      },
      {
        h2: "Size the position from the stop",
        paragraphs: [
          "Decide where your idea is wrong first, then size. The formula is simple: contracts = max dollar risk ÷ (stop distance in points × dollars per point).",
          "Example: you're willing to risk $100 on a trade and your stop is 10 points away on MNQ ($2 per point). Risk per contract is $20, so up to 5 MNQ contracts fits your rule. The same 10-point stop on NQ is $200 per contract, which already breaks your rule with one contract. That's the main reason beginners are often pointed to micros.",
        ],
      },
      {
        h2: "Set a daily loss limit and actually stop",
        paragraphs: [
          "A daily loss limit is a number you decide in advance, while calm. When it's hit, you're done for the session. This protects you from the most expensive habit in trading: trying to win back a loss immediately.",
          "Many traders also set a maximum number of trades per day and a hard stop after two consecutive losses.",
        ],
      },
      {
        h2: "Understand margin and leverage",
        paragraphs: [
          "Margin is a good-faith deposit, not the cost of the contract. Brokers set their own intraday margins, which can be far lower than exchange overnight margins. Low margin is not a reason to trade larger; it only means less of your account stands between you and a margin call.",
          "Losses in futures can exceed the money in your account. Read your broker's margin and liquidation policy before trading live.",
        ],
      },
      {
        h2: "Journal the process, not just the P&L",
        paragraphs: [
          "After each session, record whether you followed your rules: Was the stop written before entry? Did you respect the daily limit? Did you skip when your setup wasn't there? Grading the process lets you improve even on red days, and it surfaces the habits that cost the most.",
        ],
      },
    ],
    faq: [
      {
        q: "How much money do I need to start trading futures?",
        a: "It depends on your broker's margin requirements and, more importantly, how much you can afford to lose. Micro contracts lower the dollar risk per point, but no amount guarantees success. Never trade money you need.",
      },
      {
        q: "Are micro futures good for beginners?",
        a: "Micros like MES and MNQ are one-tenth the size of their E-mini versions, which makes it easier to keep dollar risk small while you learn. They carry the same leverage-related risks.",
      },
      {
        q: "Can I lose more than I deposit trading futures?",
        a: "Yes. Because futures are leveraged, losses can exceed the funds in your account. Use stops, size conservatively, and understand your broker's liquidation rules.",
      },
    ],
  },
  {
    slug: "nq-vs-es-futures-for-new-traders",
    kicker: "Markets",
    title: "NQ vs ES: Which Futures Contract Should a New Trader Learn On?",
    metaTitle: "NQ vs ES Futures for New Traders | Sweep Capital Group",
    metaDescription:
      "NQ vs ES compared: point values, volatility, micros, and how each affects your stop size and risk. A practical guide for newer futures traders.",
    intro:
      "ES and NQ are the two most-watched equity index futures. They often move in the same direction, but they behave differently enough that the choice matters, especially for your stop size and how much each point costs you. Here's a practical comparison.",
    readMinutes: 6,
    published: "2026-11-19",
    sections: [
      {
        h2: "What each contract tracks",
        paragraphs: [
          "ES is the E-mini S&P 500, tied to 500 large U.S. companies across sectors. NQ is the E-mini Nasdaq-100, tied to 100 of the largest non-financial companies on the Nasdaq, with heavy technology weighting. Both trade on CME Globex nearly around the clock on weekdays.",
        ],
      },
      {
        h2: "Point value and typical movement",
        paragraphs: [
          "ES is $50 per point; NQ is $20 per point. That makes NQ look cheaper, but NQ's index level is much higher and it typically moves many more points in a session than ES. In practice, NQ's dollar swings per contract are often larger and faster.",
          "For a newer trader, faster movement means wider stops in points, quicker decisions, and more slippage risk around news. ES tends to move in a steadier, more measured way, which some traders find easier to read while learning.",
        ],
        bullets: [
          "ES: $12.50 per tick, $50 per point. Micro (MES): $1.25 per tick.",
          "NQ: $5.00 per tick, $20 per point. Micro (MNQ): $0.50 per tick.",
        ],
      },
      {
        h2: "Why the micro versions matter",
        paragraphs: [
          "MES and MNQ are one-tenth the size of ES and NQ. If a stop on NQ would risk $400 per contract, the same stop on MNQ risks $40. That lets you practice real execution with your actual stop placement without oversizing.",
        ],
      },
      {
        h2: "How to choose",
        paragraphs: ["There's no universally right answer. Some practical guidelines:"],
        bullets: [
          "If your stops keep getting too large in dollars, start with MES or MNQ.",
          "If you find fast, extended moves hard to manage, ES or MES may suit you better while you learn.",
          "Pick one market and learn its daily rhythm before switching. Jumping between the two makes your journal harder to read.",
          "Check correlation: trading ES and NQ at the same time in the same direction is often close to doubling one position.",
        ],
      },
      {
        h2: "The framework matters more than the ticker",
        paragraphs: [
          "Concepts like prior-session highs and lows, liquidity sweeps, and opening ranges apply to both markets. What changes is the size of the move and therefore your position size. Write your risk in dollars first, then let the contract choice follow.",
        ],
      },
    ],
    faq: [
      {
        q: "Is NQ or ES better for beginners?",
        a: "Many newer traders find ES (or MES) easier because it tends to move in a steadier way, while NQ often moves more points, faster. Either can work if you size from your stop and start with micros.",
      },
      {
        q: "How much is one point on NQ vs ES?",
        a: "One point on ES is $50 and one point on NQ is $20. On the micros, MES is $5 per point and MNQ is $2 per point.",
      },
      {
        q: "Should I trade ES and NQ at the same time?",
        a: "They are often highly correlated, so holding both in the same direction can concentrate risk. Most newer traders are better off learning one market well first.",
      },
    ],
  },
  {
    slug: "liquidity-sweep-futures-trading",
    kicker: "Concepts",
    title: "What Is a Liquidity Sweep in Futures Trading?",
    metaTitle: "What Is a Liquidity Sweep? Futures Trading Guide | Sweep Capital",
    metaDescription:
      "A plain-English explanation of liquidity sweeps on ES and NQ: why prior highs and lows matter, how a sweep differs from a breakout, and how to define risk.",
    intro:
      "If you've spent time around futures traders you've heard it: \"price swept the highs.\" A liquidity sweep is a quick run through an obvious level, often a prior high or low, followed by a move back the other way. Here's what traders mean by it, why it happens, and how to think about risk around it.",
    readMinutes: 6,
    published: "2026-11-19",
    sections: [
      {
        h2: "Why obvious levels attract orders",
        paragraphs: [
          "Prior-day highs and lows, overnight highs and lows, and the opening range are levels everyone can see. That makes them natural places for stop-loss orders and breakout entries to cluster. Buy stops tend to sit just above highs; sell stops just below lows.",
          "When price reaches those levels, those resting orders get filled. That pool of orders is what traders loosely call liquidity.",
        ],
      },
      {
        h2: "Sweep vs. breakout",
        paragraphs: [
          "A breakout is a move through a level that keeps going. A sweep is a move through a level that fails to hold and returns back inside. On the chart, a sweep often shows up as a wick beyond the level with a close back inside the prior range.",
          "You can't know in advance which one you're looking at. That's why the useful question isn't \"is this a sweep?\" but \"what has to happen next for my idea to be valid, and where am I wrong?\"",
        ],
      },
      {
        h2: "How the Session Sweep framework uses it",
        paragraphs: ["At Sweep Capital Group we teach the sweep as a condition, not a signal:"],
        bullets: [
          "Map the prior session's high and low before the open.",
          "Wait for one of them to be taken. No sweep, no interest.",
          "Look for price to return back through the level, then drop to the 5- and 15-minute charts for a defined entry (the 5-15 Gap).",
          "Write the invalidation before entering. If price goes back beyond the sweep extreme, the idea is wrong.",
          "If none of that happens cleanly, skip the session.",
        ],
      },
      {
        h2: "Common mistakes",
        paragraphs: ["Most problems come from treating every wick as a reversal:"],
        bullets: [
          "Entering the moment a level is touched, before any return.",
          "Placing the stop so tight that normal noise takes it out, or so wide the dollar risk breaks your rules.",
          "Ignoring scheduled news, which can make sweeps and breakouts far more violent.",
          "Trading every level on the chart instead of a few you mapped in advance.",
        ],
      },
    ],
    faq: [
      {
        q: "Is a liquidity sweep the same as a stop hunt?",
        a: "Traders often use the terms loosely for the same idea: price running through a level where stop orders cluster and then reversing. Whether anyone is intentionally hunting stops is debated; the practical point is that obvious levels attract orders.",
      },
      {
        q: "Do liquidity sweeps always reverse?",
        a: "No. Sometimes what looks like a sweep becomes a sustained breakout. That's why a written invalidation level and a predefined dollar risk matter more than the label.",
      },
    ],
  },
  {
    slug: "how-to-choose-a-futures-trading-course",
    kicker: "Buying guide",
    title: "How to Choose a Futures Trading Course (and Red Flags to Avoid)",
    metaTitle: "How to Choose a Futures Trading Course: Red Flags | Sweep Capital",
    metaDescription:
      "What a legitimate futures trading course should include, the red flags that signal a scam, and the questions to ask before you pay for any trading education.",
    intro:
      "Trading education ranges from genuinely useful to outright predatory. Since we sell a course ourselves, read this with that bias in mind, but these are the same questions we'd want a friend to ask before paying anyone, including us.",
    readMinutes: 6,
    published: "2026-11-19",
    sections: [
      {
        h2: "Red flags",
        paragraphs: ["Walk away, or at least slow down, if you see any of these:"],
        bullets: [
          "Guaranteed profits, guaranteed funding, or \"replace your income in 30 days\" claims.",
          "Screenshots of big wins with no context, no losing trades, and no explanation of risk.",
          "Pressure tactics: countdown timers that reset, \"only 2 spots left\" every week.",
          "Signals or copy-trading sold as education. Being told what to click is not learning a skill.",
          "No clear refund terms, or recurring billing buried in the fine print.",
          "Anyone offering to trade your money for you without being properly registered.",
        ],
      },
      {
        h2: "What a solid course should include",
        paragraphs: ["Good futures education usually covers:"],
        bullets: [
          "Contract mechanics: tick values, margin, sessions, and how leverage works.",
          "Risk management first: position sizing from the stop, daily loss limits, and when to stop.",
          "A small number of clearly defined setups with written entry and invalidation rules.",
          "A journaling and review process so you can see whether you're following the rules.",
          "Honest discussion of losing streaks and the fact that most traders lose money.",
        ],
      },
      {
        h2: "Questions to ask before you pay",
        paragraphs: ["Ask the seller directly, and get the answers in writing:"],
        bullets: [
          "Is this a one-time payment or a subscription?",
          "What is the refund policy, exactly?",
          "Will I learn a process I can apply myself, or am I following someone's calls?",
          "What kind of personal feedback is included, and for how long?",
          "What do you say about results? (The right answer: they're not guaranteed.)",
        ],
      },
      {
        h2: "Where Sweep Capital Group fits",
        paragraphs: [
          "Our programs are one-time payments: The Course ($1,000) is the self-paced curriculum and community; Course + Coaching ($1,500) adds 1:1 walkthroughs and trade reviews during an agreed coaching window. We teach a written framework (Session Sweep, the 5-15 Gap, and Power of 3), not signals, and we don't promise results. The details and the refund window are on the mentorship page, so you can check them against the questions above.",
        ],
      },
    ],
    faq: [
      {
        q: "Are futures trading courses worth it?",
        a: "It depends on the course and on you. A course can shorten the learning curve on mechanics and risk, but no course can guarantee profitability. Prioritize risk education, clear rules, and honest terms.",
      },
      {
        q: "How can I tell if a trading course is a scam?",
        a: "Be wary of guaranteed returns, unverifiable win screenshots, high-pressure scarcity, hidden subscriptions, and offers to manage your money. The CFTC and NFA publish guidance on spotting trading fraud.",
      },
    ],
  },
];

export function getLearnArticle(slug: string): LearnArticle {
  const a = LEARN_ARTICLES.find((x) => x.slug === slug);
  if (!a) throw new Error(`Unknown learn article: ${slug}`);
  return a;
}
