import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("micro-futures-mnq-mes-explained");

export const Route = createFileRoute("/learn/micro-futures-mnq-mes-explained")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
