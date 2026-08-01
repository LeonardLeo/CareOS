import { FIGURES } from "@/content/site";
import { Reveal } from "@/components/reveal";

/** The problem, in numbers. Each figure carries its source; see `content/site.ts`. */
export function Figures() {
  return (
    <div className="figures">
      {FIGURES.map((figure, index) => (
        <Reveal key={figure.value} className="figure" delay={index * 70}>
          <div className={`figure__value${figure.signal ? " figure__value--signal" : ""}`}>
            {figure.value}
          </div>
          <p className="figure__label">{figure.label}</p>
          <p className="figure__source">{figure.source}</p>
        </Reveal>
      ))}
    </div>
  );
}
