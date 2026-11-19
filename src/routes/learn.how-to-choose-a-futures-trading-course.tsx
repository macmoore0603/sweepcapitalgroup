import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("how-to-choose-a-futures-trading-course");

export const Route = createFileRoute("/learn/how-to-choose-a-futures-trading-course")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
