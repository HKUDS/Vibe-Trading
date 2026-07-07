import { BadgeCheck } from "lucide-react";
import type { ResearchClaimsResponse } from "@/lib/api";
import { redactResearchText } from "./redaction";

export function ClaimAuditPanel({
  claimsResponse,
  claimIds = [],
}: {
  claimsResponse?: ResearchClaimsResponse | null;
  claimIds?: string[];
}) {
  const claims = claimsResponse?.claim_set?.claims || [];
  const ids = claimsResponse?.claim_ids?.length ? claimsResponse.claim_ids : claimIds;

  return (
    <section className="rounded-md border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <BadgeCheck className="h-4 w-4 text-muted-foreground" />
        Claim Audit
      </div>
      {claims.length > 0 ? (
        <div className="space-y-2">
          {claims.map((claim) => (
            <div key={claim.claim_id} className="rounded-md border bg-background/50 p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono">{redactResearchText(claim.claim_id)}</span>
                <span className="rounded-md bg-muted px-2 py-0.5 text-muted-foreground">
                  {redactResearchText(claim.claim_type)}
                </span>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">{redactResearchText(claim.claim_text)}</p>
              {(claim.evidence_refs || []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(claim.evidence_refs || []).map((ref) => (
                    <span key={ref} className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
                      {redactResearchText(ref)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : ids.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {ids.map((id) => (
            <span key={id} className="rounded-md bg-muted px-2 py-1 font-mono text-xs text-muted-foreground">
              {redactResearchText(id)}
            </span>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No claims recorded.</p>
      )}
    </section>
  );
}
