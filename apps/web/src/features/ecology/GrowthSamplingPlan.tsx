import type { Identity } from "./ecologyApi";
import type { GrowthPlanUnit } from "./ecologyAnalysisApi";

export function GrowthSamplingPlan({
  identities,
  plan,
  onChange,
}: {
  identities: Identity[];
  plan: GrowthPlanUnit[];
  onChange: (plan: GrowthPlanUnit[]) => void;
}) {
  const units = new Map<string, string[]>();
  for (const row of identities) {
    const id = row.experimental_unit_id;
    if (id) units.set(id, [...(units.get(id) ?? []), row.organism_key]);
  }
  for (const unit of plan) {
    const id = unit.experimental_unit_id;
    units.set(id, [
      ...new Set([...(units.get(id) ?? []), ...unit.organism_keys]),
    ]);
  }

  function replace(unit: GrowthPlanUnit | null, id: string) {
    const others = plan.filter((item) => item.experimental_unit_id !== id);
    onChange(unit ? [...others, unit] : others);
  }

  return (
    <fieldset>
      <legend>Planned growth sampling</legend>
      <p>
        Choose experimental units and expected organisms. Record at least two
        distinct UTC dates for each unit. Include organisms with missing photos.
      </p>
      {units.size === 0 && <p>Assign organisms to experimental units first.</p>}
      {[...units]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([id, organisms]) => {
          const unit = plan.find((item) => item.experimental_unit_id === id);
          return (
            <fieldset key={id}>
              <legend>{id}</legend>
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(unit)}
                  onChange={(event) =>
                    replace(
                      event.target.checked
                        ? {
                            experimental_unit_id: id,
                            organism_keys: [],
                            dates: ["", ""],
                          }
                        : null,
                      id,
                    )
                  }
                />
                Include {id} in sampling plan
              </label>
              {unit && (
                <>
                  {organisms.map((organism) => (
                    <label key={organism}>
                      <input
                        type="checkbox"
                        checked={unit.organism_keys.includes(organism)}
                        onChange={(event) =>
                          replace(
                            {
                              ...unit,
                              organism_keys: event.target.checked
                                ? [...unit.organism_keys, organism]
                                : unit.organism_keys.filter(
                                    (key) => key !== organism,
                                  ),
                            },
                            id,
                          )
                        }
                      />
                      Expect {organism} in {id}
                    </label>
                  ))}
                  {unit.dates.map((day, index) => (
                    <div key={index}>
                      <label>
                        {id} planned date {index + 1} (UTC)
                        <input
                          type="date"
                          required
                          value={day}
                          onChange={(event) => {
                            const dates = [...unit.dates];
                            dates[index] = event.target.value;
                            replace({ ...unit, dates }, id);
                          }}
                        />
                      </label>
                      {unit.dates.length > 2 && (
                        <button
                          type="button"
                          onClick={() =>
                            replace(
                              {
                                ...unit,
                                dates: unit.dates.filter(
                                  (_, position) => position !== index,
                                ),
                              },
                              id,
                            )
                          }
                        >
                          Remove {id} planned date {index + 1}
                        </button>
                      )}
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() =>
                      replace({ ...unit, dates: [...unit.dates, ""] }, id)
                    }
                  >
                    Add {id} planned date
                  </button>
                </>
              )}
            </fieldset>
          );
        })}
    </fieldset>
  );
}
