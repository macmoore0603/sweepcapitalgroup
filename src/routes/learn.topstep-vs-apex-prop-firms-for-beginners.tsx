import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("topstep-vs-apex-prop-firms-for-beginners");

export const Route = createFileRoute("/learn/topstep-vs-apex-prop-firms-for-beginners")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
