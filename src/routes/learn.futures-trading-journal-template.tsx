import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("futures-trading-journal-template");

export const Route = createFileRoute("/learn/futures-trading-journal-template")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
