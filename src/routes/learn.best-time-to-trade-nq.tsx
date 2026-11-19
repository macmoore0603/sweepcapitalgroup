import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("best-time-to-trade-nq");

export const Route = createFileRoute("/learn/best-time-to-trade-nq")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
