import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("ict-liquidity-concepts-for-beginners");

export const Route = createFileRoute("/learn/ict-liquidity-concepts-for-beginners")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
