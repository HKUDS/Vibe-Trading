import { FinalCTA } from "@/components/home/FinalCTA";
import { FounderSection } from "@/components/home/FounderSection";
import { HeroSection } from "@/components/home/HeroSection";
import { IntelligencePipeline } from "@/components/home/IntelligencePipeline";
import { OpportunityPreview } from "@/components/home/OpportunityPreview";
import { PerformanceLabPreview } from "@/components/home/PerformanceLabPreview";
import { PricingSection } from "@/components/home/PricingSection";
import { ProfitProjectionEngine } from "@/components/home/ProfitProjectionEngine";
import { RiskManagementPreview } from "@/components/home/RiskManagementPreview";
import { WhyTradeCoreFX } from "@/components/home/WhyTradeCoreFX";

export function Home() {
  return (
    <div className="overflow-x-hidden">
      <HeroSection />
      <WhyTradeCoreFX />
      <IntelligencePipeline />
      <OpportunityPreview />
      <ProfitProjectionEngine />
      <RiskManagementPreview />
      <PerformanceLabPreview />
      <FounderSection />
      <PricingSection />
      <FinalCTA />
    </div>
  );
}
