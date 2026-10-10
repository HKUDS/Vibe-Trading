import ReactMarkdown, { type Options } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

const rehypePlugins: Options["rehypePlugins"] = [rehypeHighlight, rehypeKatex];

export default function EnhancedMarkdown({ content, remarkPlugins, components }: {
  content: string;
  remarkPlugins: Options["remarkPlugins"];
  components: Options["components"];
}) {
  return (
    <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
      {content}
    </ReactMarkdown>
  );
}
