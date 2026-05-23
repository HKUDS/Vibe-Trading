import { useParams } from "react-router-dom";

export default function StrategyDetail() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">Strategy: {id}</h1>
      <p className="text-muted-foreground">Coming in task 4.4</p>
    </div>
  );
}
