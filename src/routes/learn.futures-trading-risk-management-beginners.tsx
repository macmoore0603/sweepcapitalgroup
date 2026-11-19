import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("futures-trading-risk-management-beginners");

export const Route = createFileRoute("/learn/futures-trading-risk-management-beginners")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
