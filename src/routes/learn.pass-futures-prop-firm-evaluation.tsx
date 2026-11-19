import { createFileRoute } from "@tanstack/react-router";
import { LearnArticlePage, learnHead } from "@/components/LearnArticle";
import { getLearnArticle } from "@/lib/learn-articles";

const article = getLearnArticle("pass-futures-prop-firm-evaluation");

export const Route = createFileRoute("/learn/pass-futures-prop-firm-evaluation")({
  head: () => learnHead(article),
  component: () => <LearnArticlePage article={article} />,
});
