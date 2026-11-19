import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("liquidity-sweep-futures-trading");

export const Route = createFileRoute("/learn/liquidity-sweep-futures-trading")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
