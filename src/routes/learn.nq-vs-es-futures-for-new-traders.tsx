import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("nq-vs-es-futures-for-new-traders");

export const Route = createFileRoute("/learn/nq-vs-es-futures-for-new-traders")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
