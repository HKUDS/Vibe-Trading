import { Database } from "lucide-react";

export interface DataSourceSummary {
  audit_id?: string;
  source?: string;
  selected_source?: string;
  fallback_chain?: string[];
  row_count?: number;
  symbol_count?: number;
}

export function DataProvenancePanel({ dataSources = [] }: { dataSources?: DataSourceSummary[] }) {
  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Database className="h-4 w-4 text-muted-foreground" />
        Data Provenance
      </div>
      {dataSources.length === 0 ? (
        <p className="text-sm text-muted-foreground">No data provenance recorded.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="py-2 pr-4">Source</th>
                <th className="py-2 pr-4">Selected</th>
                <th className="py-2 pr-4">Fallback Path</th>
                <th className="py-2 text-right">Rows</th>
              </tr>
            </thead>
            <tbody>
              {dataSources.map((source, index) => (
                <tr key={source.audit_id || index} className="border-b last:border-0">
                  <td className="py-2 pr-4 font-mono text-xs">{source.source || "unknown"}</td>
                  <td className="py-2 pr-4 font-mono text-xs">{source.selected_source || "unknown"}</td>
                  <td className="py-2 pr-4 text-xs text-muted-foreground">
                    {(source.fallback_chain || []).join(" -> ") || "None recorded"}
                  </td>
                  <td className="py-2 text-right tabular-nums">{source.row_count ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
