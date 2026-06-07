import { getFixtures } from "@/lib/api";
import { Reveal } from "@/components/Reveal";
import { SectionHeading } from "@/components/ui";
import { FixtureBrowser } from "@/components/FixtureBrowser";

export const metadata = { title: "Fixtures | The Arena" };

export default async function FixturesPage() {
  const fixtures = await getFixtures();
  return (
    <div className="flex flex-col gap-10">
      <Reveal>
        <SectionHeading
          kicker="The schedule"
          title="Every fixture"
          sub="All 104 matches from group stage to the final. Group games carry live market odds; knockout slots resolve as the bracket fills. Tap a match for every model's call."
        />
      </Reveal>
      <FixtureBrowser fixtures={fixtures} />
    </div>
  );
}
