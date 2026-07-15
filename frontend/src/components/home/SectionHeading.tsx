interface SectionHeadingProps {
  eyebrow?: string;
  title: string;
  intro?: string;
  align?: "left" | "center";
}

export function SectionHeading({ eyebrow, title, intro, align = "center" }: SectionHeadingProps) {
  return (
    <div className={align === "center" ? "mx-auto max-w-3xl text-center" : "max-w-3xl"}>
      {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">{eyebrow}</p>}
      <h2 className="mt-3 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">{title}</h2>
      {intro && <p className="mt-4 text-base leading-7 text-muted-foreground sm:text-lg">{intro}</p>}
    </div>
  );
}
