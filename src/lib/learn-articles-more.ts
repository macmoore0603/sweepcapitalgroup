import type { LearnArticle } from "./learn-articles";

export const LEARN_ARTICLES_MORE: LearnArticle[] = [
  {
    slug: "topstep-vs-apex-prop-firms-for-beginners",
    kicker: "Prop firms",
    title: "Topstep vs Apex vs Other Futures Prop Firms: What Beginners Should Compare",
    metaTitle: "Topstep vs Apex vs Other Prop Firms for Beginners | Sweep",
    metaDescription:
      "A neutral checklist for comparing futures prop firms like Topstep and Apex Trader Funding: drawdown type, daily limits, consistency rules, fees, and payouts.",
    intro:
      "Search \"best futures prop firm\" and you'll find a hundred affiliate lists with a discount code at the top. This guide isn't one of them. We don't take referral fees from any firm. Instead of crowning a winner, it shows the handful of rules that actually decide whether a beginner survives an evaluation, so you can compare Topstep, Apex Trader Funding, and any other firm yourself.",
    readMinutes: 8,
    published: "2026-11-19",
    sections: [
      {
        h2: "First, a warning about comparison tables",
        paragraphs: [
          "Prop firms change their rules, prices, and payout terms often, sometimes several times a year. Any table that lists exact numbers for Topstep, Apex, or anyone else is probably already out of date. Use this guide as a list of questions, then read each firm's current rulebook and help center before you buy anything.",
          "Also remember what an evaluation is: a paid product with a simulated account. Most people who buy one don't reach a payout. Treat the fee as a cost of practice you can afford to lose, not an investment.",
        ],
      },
      {
        h2: "1. What kind of drawdown is it?",
        paragraphs: [
          "This matters more than the price. Firms generally use one of three styles: a static drawdown fixed from the starting balance, an intraday trailing drawdown that follows your highest balance (including open profit) in real time, or an end-of-day trailing drawdown that only updates at the close.",
          "For most beginners, an end-of-day or static drawdown is more forgiving than an intraday trailing one, because a trade that runs in your favor and then comes back won't quietly tighten your limit. Read our trailing drawdown guide before choosing.",
        ],
      },
      {
        h2: "2. Is there a daily loss limit, and is it hard or soft?",
        paragraphs: [
          "Some firms fail the account if you hit the daily loss limit. Others just stop you for the day. Some don't use one at all. A daily limit can actually help a beginner, because it forces the stop that discipline should provide anyway, but you need to know whether breaking it ends the account.",
        ],
      },
      {
        h2: "3. Consistency rules and minimum days",
        paragraphs: [
          "Many firms limit how much of your total profit can come from one day, either during the evaluation or before payouts. Others require a minimum number of trading days. These rules punish the \"one huge day\" approach, which is a good thing for your habits, but they change how long an evaluation realistically takes.",
        ],
      },
      {
        h2: "4. The real cost: fees, resets, and activation",
        paragraphs: [
          "Compare the total cost of getting to a payout, not the sticker price. That includes the monthly or one-time evaluation fee, reset fees, any activation or data fees for the funded stage, and how often the firm runs discounts (frequent discounts mean the list price isn't the real price).",
        ],
        bullets: [
          "Evaluation price and whether it renews monthly",
          "Reset cost if you break a rule",
          "Activation or monthly fee on the funded account",
          "Market data or platform fees",
        ],
      },
      {
        h2: "5. Payout rules on the funded account",
        paragraphs: [
          "Look at the profit split, how soon you can request a payout, any minimum balance or buffer you must keep, payout caps, and whether the drawdown changes after funding. Read recent payout policy updates from the firm itself, not screenshots on social media.",
        ],
      },
      {
        h2: "6. Allowed instruments, news, and platforms",
        paragraphs: [
          "Check whether micros (MNQ, MES) are allowed and how they count toward contract limits, whether you can trade through major news releases, whether you must be flat by a set time, and which platforms are supported. A firm that bans the exact way you trade is the wrong firm no matter how cheap it is.",
        ],
      },
      {
        h2: "So which firm is best for a beginner?",
        paragraphs: [
          "Honestly, the one whose rules match a process you've already written down and practiced. Topstep, Apex Trader Funding, and the newer firms all have trade-offs, and the trader who passes is usually the one who sized small and followed a plan, not the one who found the perfect firm. If you don't have a written process yet, build that first, in a simulator, before paying for any evaluation.",
        ],
      },
    ],
    faq: [
      {
        q: "Is Topstep or Apex better for beginners?",
        a: "Neither is universally better. Compare drawdown type, daily loss rules, consistency rules, total cost, and payout terms against how you trade, and confirm the current rules on each firm's own site before buying.",
      },
      {
        q: "Do most traders pass prop firm evaluations?",
        a: "Firms rarely publish complete pass rates, and the figures that do circulate suggest most evaluations are not passed. Treat the fee as money you can afford to lose.",
      },
      {
        q: "Does Sweep Capital Group partner with any prop firm?",
        a: "No. We don't take affiliate or referral fees from prop firms, and nothing here is a recommendation to buy any specific firm's product.",
      },
    ],
  },
  {
    slug: "trailing-drawdown-explained",
    kicker: "Prop firms",
    title: "Trailing Drawdown Explained (With Simple Examples)",
    metaTitle: "Trailing Drawdown Explained: Intraday vs End-of-Day | Sweep",
    metaDescription:
      "What a trailing drawdown is, how intraday and end-of-day trailing differ, and worked examples showing how open profit can tighten your futures prop firm limit.",
    intro:
      "The trailing drawdown is the rule that ends more prop firm accounts than any bad trade. It sounds simple (your loss limit follows your account up), but the details, especially whether it trails intraday or at the close, change how you should manage every winning trade. Here's how it works, with numbers.",
    readMinutes: 7,
    published: "2026-11-19",
    sections: [
      {
        h2: "Static vs trailing drawdown",
        paragraphs: [
          "A static drawdown is a fixed floor. Start a $50,000 account with a $2,000 static drawdown and the account fails at $48,000, no matter how high you go first.",
          "A trailing drawdown is a floor that moves up as your account makes new highs. With a $2,000 trailing drawdown, if your balance peaks at $51,000 the floor moves to $49,000. It doesn't move back down when you lose. Most firms stop trailing once the floor reaches a set level (often the starting balance), but check your firm's exact rule.",
        ],
      },
      {
        h2: "Intraday trailing: open profit counts",
        paragraphs: [
          "With an intraday (real-time) trailing drawdown, the floor follows your highest equity including unrealized profit on open trades. That's the part that catches people.",
          "Example: you start at $50,000 with a $2,000 intraday trailing drawdown (floor $48,000). You enter a trade that runs to +$800 open profit, so peak equity is $50,800 and the floor jumps to $48,800. The trade reverses and you close it at breakeven. Your balance is still $50,000, but your cushion is now only $1,200, not $2,000. You lost 40% of your room on a trade that \"didn't lose money.\"",
        ],
      },
      {
        h2: "End-of-day trailing: only the close counts",
        paragraphs: [
          "With an end-of-day trailing drawdown, the floor only updates based on your balance at the session close. In the same example, the +$800 that came back during the day wouldn't move the floor at all. Only a winning close would.",
          "End-of-day trailing is more forgiving intraday, but it still ratchets up after every green day, so a few good days followed by one large loss can end the account.",
        ],
      },
      {
        h2: "How to trade under a trailing drawdown",
        paragraphs: [
          "The goal is to protect the cushion, not just the balance. A few habits that help:",
        ],
        bullets: [
          "Write down your floor in dollars before every session, and recalculate after every trade.",
          "Size trades from the remaining cushion, not the account size. A $50,000 account with $1,200 of room is really a $1,200 account.",
          "Under intraday trailing, decide in advance where you'll take partial profit or move your stop, so open profit doesn't become free drawdown.",
          "Use micro contracts (MES, MNQ) early in an evaluation, when the cushion is smallest.",
          "Stop for the day at a personal loss limit well inside the firm's limits.",
        ],
      },
      {
        h2: "When the trailing stops",
        paragraphs: [
          "Many firms stop trailing once the floor reaches the starting balance (or starting balance plus a small buffer). After that point the drawdown is effectively static, which is why the early days of a funded account are usually the most fragile. Read the exact wording in your firm's rulebook, since this detail varies more than any other.",
        ],
      },
    ],
    faq: [
      {
        q: "Does a trailing drawdown include unrealized profit?",
        a: "Under intraday (real-time) trailing, usually yes: the floor follows peak equity including open profit. Under end-of-day trailing, only the closing balance counts. Check your firm's rulebook.",
      },
      {
        q: "Is end-of-day or intraday trailing drawdown better for beginners?",
        a: "End-of-day trailing is generally more forgiving because open profit that comes back during the session doesn't tighten your limit. Either way, size from the remaining cushion.",
      },
    ],
  },
  {
    slug: "best-time-to-trade-nq",
    kicker: "Markets",
    title: "Best Time to Trade NQ (Nasdaq-100 Futures): A Session Guide for Beginners",
    metaTitle: "Best Time to Trade NQ Futures: Session Guide | Sweep Capital",
    metaDescription:
      "NQ and MNQ trading hours, the New York open, 8:30 and 10:00 ET data, the lunch lull, and the close. When volume is highest and when beginners should sit out.",
    intro:
      "Nasdaq-100 futures (NQ, and the micro MNQ) trade nearly 24 hours a day, five days a week. That doesn't mean every hour is worth trading. Volume, volatility, and the kind of moves you see change a lot across the day. Here's a plain map of the session in Eastern Time, and why many newer traders do better by trading a small window well.",
    readMinutes: 7,
    published: "2026-11-19",
    sections: [
      {
        h2: "NQ trading hours (Eastern Time)",
        paragraphs: [
          "NQ trades on CME Globex from Sunday 6:00 PM ET to Friday 5:00 PM ET, with a daily one-hour break from 5:00 to 6:00 PM ET. Holiday schedules differ, so check CME's calendar around holidays.",
          "In practice the day splits into the overnight session (Asia and London hours) and the regular US session around the stock market's 9:30 AM to 4:00 PM ET hours.",
        ],
      },
      {
        h2: "8:30 AM ET: economic data",
        paragraphs: [
          "Many major US reports (CPI, jobs, jobless claims, retail sales) are released at 8:30 AM ET. NQ can move sharply in seconds, with wide spreads and slippage. Many beginners choose to be flat before scheduled high-impact releases and wait for the market to settle. Some prop firms also restrict trading around news, so check your rules.",
        ],
      },
      {
        h2: "9:30 to 11:00 AM ET: the New York open",
        paragraphs: [
          "The cash equity open brings the most volume and the biggest ranges of the regular session. This is where setups like the opening range breakout and liquidity sweeps of the overnight or prior-day high and low tend to show up.",
          "It's also the fastest, most emotional part of the day. Higher volume means more opportunity and more risk. If you trade the open, use defined risk and consider micros while you learn. 10:00 AM ET is another common time for data releases.",
        ],
      },
      {
        h2: "11:30 AM to 1:30 PM ET: the lunch lull",
        paragraphs: [
          "Volume usually drops through the middle of the day. Moves get choppier and false breakouts are more common. For many newer traders, this is a good time to stop, journal the morning, and not trade.",
        ],
      },
      {
        h2: "2:00 to 4:00 PM ET: the afternoon and close",
        paragraphs: [
          "Activity often picks up into the last hour as positions are adjusted before the 4:00 PM ET cash close. On days with Federal Reserve announcements (usually 2:00 PM ET), the afternoon can be the most volatile part of the day.",
        ],
      },
      {
        h2: "A simple plan: one window, written rules",
        paragraphs: [
          "There's no time of day that guarantees good trades. What helps most beginners is choosing one window (for example, 9:45 to 11:00 AM ET), trading only your written setup inside it, and stopping when the window closes, win or lose. Fewer, cleaner decisions are easier to review and improve.",
        ],
        bullets: [
          "Check the economic calendar before the session.",
          "Mark the overnight high and low and the prior day's high and low.",
          "Decide your window and max loss before the open.",
          "Journal every trade at the end of the window.",
        ],
      },
    ],
    faq: [
      {
        q: "What time does NQ open?",
        a: "NQ futures open Sunday at 6:00 PM ET and trade nearly around the clock until Friday 5:00 PM ET, with a daily break from 5:00 to 6:00 PM ET. Most volume comes during the US session, especially after the 9:30 AM ET stock market open.",
      },
      {
        q: "Should beginners trade the New York open?",
        a: "It offers the most volume but also the fastest moves. If you trade it, define your risk in advance, consider micro contracts (MNQ), and avoid trading through scheduled high-impact data.",
      },
    ],
  },
  {
    slug: "micro-futures-mnq-mes-explained",
    kicker: "Basics",
    title: "Micro Futures Explained: MNQ and MES for Beginners",
    metaTitle: "Micro Futures Explained: MNQ vs MES Tick Values | Sweep",
    metaDescription:
      "What micro E-mini futures are, MNQ and MES tick and point values compared with NQ and ES, margin basics, and why micros help new traders size risk.",
    intro:
      "Micro E-mini futures are one-tenth the size of the standard E-mini contracts. For a new trader, that's the difference between risking $200 and $2,000 on the same chart idea. Here's how MNQ and MES work, what each tick is worth, and how to use them to keep risk small while you learn.",
    readMinutes: 6,
    published: "2026-11-19",
    sections: [
      {
        h2: "What micro futures are",
        paragraphs: [
          "CME launched Micro E-mini equity index futures in 2019. They track the same indexes as the E-minis (the Nasdaq-100 for NQ/MNQ and the S&P 500 for ES/MES) and trade during the same hours, but each contract is one-tenth the size.",
        ],
      },
      {
        h2: "Tick and point values",
        paragraphs: ["The numbers that matter most for sizing (always confirm current specs on CME's site):"],
        bullets: [
          "MNQ (Micro Nasdaq-100): tick size 0.25 points = $0.50; one point = $2.",
          "NQ (E-mini Nasdaq-100): tick size 0.25 points = $5.00; one point = $20.",
          "MES (Micro S&P 500): tick size 0.25 points = $1.25; one point = $5.",
          "ES (E-mini S&P 500): tick size 0.25 points = $12.50; one point = $50.",
        ],
      },
      {
        h2: "Why micros matter for beginners",
        paragraphs: [
          "Say your setup needs a 40-point stop on the Nasdaq. On one NQ contract that's $800 of risk. On one MNQ it's $80. With micros you can also scale in steps: 3 MNQ is $240 of risk on the same idea, which is impossible to do precisely with full-size contracts.",
          "That flexibility makes it far easier to follow a rule like \"risk no more than 1% of my account\" or \"risk no more than 10% of my remaining prop firm drawdown per trade.\"",
        ],
      },
      {
        h2: "Margin is not your risk",
        paragraphs: [
          "Brokers require margin to hold a position, and micro margins are much lower than E-mini margins. But margin is a deposit, not a loss limit. Futures are leveraged, and you can lose more than the margin, and in extreme cases more than your account balance. Your risk is defined by your stop and position size, so set both before entering.",
        ],
      },
      {
        h2: "Costs to watch",
        paragraphs: [
          "Commissions and exchange fees are charged per contract, so they're a larger share of each trade on micros than on E-minis. If you trade many contracts for small targets, fees add up. Factor them into your journal so you see your real results.",
        ],
      },
      {
        h2: "MNQ or MES?",
        paragraphs: [
          "MNQ moves more points per day than MES, so equal stops in points mean different dollar risk. MES tends to move more slowly and smoothly. Many newer traders start with MES for its slower pace, or MNQ if they want the Nasdaq's larger ranges, sized down. Our NQ vs ES guide covers the trade-offs in detail.",
        ],
      },
    ],
    faq: [
      {
        q: "How much is one tick on MNQ?",
        a: "One MNQ tick (0.25 index points) is worth $0.50, so one full point is $2. That's one-tenth of NQ, where a point is $20.",
      },
      {
        q: "How much is one tick on MES?",
        a: "One MES tick (0.25 index points) is worth $1.25, so one point is $5, one-tenth of ES.",
      },
      {
        q: "Can you lose more than you put in with micro futures?",
        a: "Yes. Micros are smaller, but they're still leveraged futures. Losses can exceed margin and, in extreme moves, your account balance. Always use a defined stop and size.",
      },
    ],
  },
  {
    slug: "futures-trading-journal-template",
    kicker: "Process",
    title: "Futures Trading Journal Template (Free, Copy-and-Paste)",
    metaTitle: "Futures Trading Journal Template: Free Fields & Review | Sweep",
    metaDescription:
      "A free futures trading journal template: the exact fields to log for every trade, a daily and weekly review routine, and the mistakes a journal helps you catch.",
    intro:
      "A journal is the cheapest edge-finding tool in trading, and the most skipped. Without one you're relying on memory, which is biased toward your best and worst trades. Below is a simple template you can paste into a spreadsheet or notebook today, plus the review routine that makes it useful.",
    readMinutes: 6,
    published: "2026-11-19",
    sections: [
      {
        h2: "Fields to log for every trade",
        paragraphs: ["Copy these as columns in a spreadsheet:"],
        bullets: [
          "Date and session window (for example, NY open)",
          "Instrument and contracts (for example, MNQ x2)",
          "Setup name (one of your written setups, or \"none\")",
          "Direction, entry price, stop price, target price",
          "Planned risk in dollars (before entry)",
          "Exit price and result in dollars, after fees",
          "R-multiple (result divided by planned risk)",
          "Followed the plan? (yes / no, and which rule was broken)",
          "Emotion before entry (calm, rushed, revenge, bored)",
          "Screenshot link: entry and exit",
        ],
      },
      {
        h2: "Why R-multiples beat dollar P&L",
        paragraphs: [
          "Logging results in R (multiples of the risk you planned) lets you compare trades of different sizes. A +$150 win on $50 of risk (+3R) is better trading than a +$300 win on $600 of risk (+0.5R). Over enough trades, your average R per setup tells you far more than your account balance.",
        ],
      },
      {
        h2: "The daily review (10 minutes)",
        paragraphs: ["At the end of every session, answer three questions in writing:"],
        bullets: [
          "Did I take only trades that matched a written setup?",
          "Did I respect my max loss per trade and per day?",
          "What's the one thing I'll do differently tomorrow?",
        ],
      },
      {
        h2: "The weekly review (30 minutes)",
        paragraphs: [
          "Once a week, filter by setup and look at win rate, average win and loss in R, and how many trades broke a rule. Most traders discover that their rule-breaking trades account for a large share of their losses, which is the single most useful thing a journal can show you.",
          "Also sort by time of day. Many newer traders find they do well in the first hour and give it back in the lunch chop.",
        ],
      },
      {
        h2: "Common journaling mistakes",
        paragraphs: [],
        bullets: [
          "Only logging losing trades (or only winners).",
          "Filling it in days later from memory.",
          "Leaving out fees, which hides how much small scalps really cost.",
          "Logging data but never reviewing it.",
          "Writing \"bad trade\" instead of naming the rule that was broken.",
        ],
      },
      {
        h2: "Keep it in the simulator first",
        paragraphs: [
          "A journal works the same on a simulator as on a live or prop account. Many traders run 30 to 50 simulated trades with a full journal before risking money, so their first real trades follow a process that's already been reviewed.",
        ],
      },
    ],
    faq: [
      {
        q: "What should a futures trading journal include?",
        a: "At minimum: date, instrument, setup, entry, stop, target, planned risk, result after fees, R-multiple, whether you followed your plan, and a screenshot. A short daily and weekly review makes it useful.",
      },
      {
        q: "Is a spreadsheet good enough for a trading journal?",
        a: "Yes. A spreadsheet with consistent columns and an honest weekly review is enough for most newer traders. Dedicated journaling software mainly saves time on imports and charts.",
      },
    ],
  },
  {
    slug: "ict-liquidity-concepts-for-beginners",
    kicker: "Concepts",
    title: "ICT and Liquidity Concepts for Beginners: What's Useful and What's Hype",
    metaTitle: "ICT Liquidity Concepts for Beginners, Explained Plainly | Sweep",
    metaDescription:
      "Buy-side and sell-side liquidity, fair value gaps, and kill zones in plain English, plus how to test these ideas honestly instead of trusting screenshots.",
    intro:
      "ICT-style concepts (liquidity, fair value gaps, \"kill zones\") are everywhere in futures content. Some of the ideas describe real things about how orders cluster in markets. A lot of the surrounding content is jargon, hindsight, and highlight reels. This guide explains the core concepts in plain English and shows how to test them before you trust them.",
    readMinutes: 8,
    published: "2026-11-19",
    sections: [
      {
        h2: "What \"liquidity\" means here",
        paragraphs: [
          "In this context, liquidity means resting orders, especially stop orders, clustered around obvious price levels. Traders who are long often place stops just below a recent low; traders who are short place stops just above a recent high. These clusters are often called sell-side liquidity (below lows) and buy-side liquidity (above highs).",
          "The idea: when price trades through an obvious high or low, those stops get triggered, which can produce a quick burst of orders. Sometimes price keeps going. Sometimes it reverses after the stops are taken, which is often called a liquidity sweep or stop run.",
        ],
      },
      {
        h2: "Fair value gaps",
        paragraphs: [
          "A fair value gap (FVG) is a three-candle pattern where the middle candle moves so fast that the wicks of the first and third candles don't overlap, leaving a price range that traded only briefly. Some traders watch for price to return to that range. It's a description of a fast, one-sided move, not a guarantee that price will come back.",
        ],
      },
      {
        h2: "Kill zones and time windows",
        paragraphs: [
          "\"Kill zones\" is a name for time windows when volume tends to rise, such as the London open and the New York open. The underlying point is solid: markets behave differently at different times of day. You don't need the label to use it. See our guide to the best time to trade NQ.",
        ],
      },
      {
        h2: "What's useful",
        paragraphs: [],
        bullets: [
          "Marking prior-day and overnight highs and lows gives you objective reference levels.",
          "Waiting for a level to be taken before acting can keep you from chasing.",
          "Focusing on specific time windows reduces overtrading.",
          "Defining invalidation (where the idea is wrong) before entry is just good risk management.",
        ],
      },
      {
        h2: "What's hype",
        paragraphs: [],
        bullets: [
          "Marked-up charts drawn after the move. Every concept looks perfect in hindsight.",
          "Claims of \"smart money\" intent that can't be verified.",
          "Dozens of overlapping concepts, so there's always a reason a trade \"should\" have worked.",
          "Win-rate or income claims with no full, verifiable track record behind them.",
        ],
      },
      {
        h2: "How to test liquidity concepts honestly",
        paragraphs: [
          "Pick one narrow, written rule. For example: \"After the NY open, if price takes the overnight low and closes back above it on the 5-minute chart, enter long with a stop below the sweep low.\" Then go back through 50+ sessions, log every instance (not just the good ones) in a journal, and look at the results in R-multiples. Then forward-test on a simulator.",
          "This is how we teach Sweep Capital Group's Session Sweep framework: a few written rules built on liquidity at prior-session levels, with the stop defined first and a clear reason to skip the day. Whatever you use, if you can't write the rule down, you can't test it.",
        ],
      },
    ],
    faq: [
      {
        q: "What is a liquidity sweep in trading?",
        a: "A liquidity sweep is when price trades through an obvious high or low, triggering stop orders clustered there, and then often reverses. It's a pattern to test, not a guaranteed signal.",
      },
      {
        q: "Do ICT concepts work?",
        a: "Some underlying ideas, like reference levels and time-of-day effects, are reasonable. Whether any specific rule has an edge for you can only be known by testing it on many sessions with a journal. No concept guarantees results.",
      },
    ],
  },
];
