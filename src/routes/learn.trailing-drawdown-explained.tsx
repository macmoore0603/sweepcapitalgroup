import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("trailing-drawdown-explained");

export const Route = createFileRoute("/learn/trailing-drawdown-explained")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
