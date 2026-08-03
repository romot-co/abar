# Operating ABAR as an audio research agent

This file describes the external audio-refinement loop. It does not grant authority to answer listening questions or change Project current best directly.

## Role and authority

The agent operates ABAR. It initializes the Project, prepares and measures proposals,
creates listening Sessions, interprets completed results, and maintains the record.

The human supplies the purpose and listening judgments. Preserve the human's wording when
establishing the Project brief. Do not invent, broaden, or silently replace the formal purpose.
The agent may ask for missing purpose or listening material, but should perform the resulting
setup itself.

ABAR enforces the boundary between operation and judgment. Never manufacture a human
preference, infer an unanswered Judgment, or bypass the sealed comparison path.

## Bootstrap a Project

Choose one persistent Workspace directory for the Project. Use the same explicit
`--workspace <directory>` value for every CLI command and when launching the UI. One
Workspace contains at most one Project.

Begin with:

```bash
abar --workspace /absolute/path/to/project-workspace --json status
```

If `project_name` is null, initialize the Project from the human's stated purpose and the
available listening material. Do not call `project show` before initialization because no
Project view exists yet.

```bash
abar --workspace /absolute/path/to/project-workspace --json \
  --actor audio-research-agent --idempotency-key project-init-v1 \
  project init --name "Product name" --brief "Human-stated purpose" \
  --material /absolute/path/to/listening-material.wav
```

Reuse one idempotency key if this logical initialization must be retried. Attach additional
   Material and Clips as needed, then write the initial Project note. Attach an already registered
   Material with `--existing-material <id>`; `--material` always imports a file. Before asking the human to
listen, ensure that the UI is available from the same Workspace. Launch
`abar --workspace <directory> ui` when necessary and give the resulting UI to the human.

## Standard loop

The abbreviated commands below omit the required `--workspace <directory>` prefix only for
readability. Continue using the Workspace selected during bootstrap.

Repeat this sequence:

1. Observe: run `abar --json status` and `abar --json project show --since <event_seq>`.
2. Record understanding: update the Project note. Register an Indicator only when a measurement has a stable external definition.
3. Prepare resources: add Material, Clips, and a reproducible Variant manifest with provenance.
   For a command renderer using the standard three-path contract, use
   `variant add --bundle <directory> --entry <relative-file>`; ABAR packages the directory and
   creates the manifest. Use `--manifest ... --archive ...` only for a custom execution contract.
   When an external measurement needs the exact audio for a registered Variant, use
   `variant materialize <variant> --clip <id> --output <directory>`. This records audio
   derivation facts but never changes current best or in-use.
4. Ask one useful question: create a short or standard Project Session against current best.
   Standard defaults to three evidence comparisons; set an explicit larger evidence count when
   one question must be observed across more Materials. Omit `--recipe` to inherit the Project
   primary Recipe; pass it only for an intentional Session-level override. Best Update remains
   fixed at three.
5. Hand the Session to the human in `abar ui`, then follow the waiting boundary below.
6. Report measurements by AudioContent or PreparedPair identity, then return to observation.

Use `--json --actor <stable-agent-id>` for agent writes. Keep one idempotency key per logical operation when retrying.

`material add` accepts multiple file arguments and returns each Material ID with its default
Clip IDs. Canonical agent write commands are `project init`, `project brief set`, `project recipe set`,
`project config set`, `material add`, `material clip add`, `variant add`, `note write`,
`project session create`, `project session best-update`, `project session close`,
`project simplification create`, `indicator add`, `indicator set`, and
`indicator value record`. `variant materialize` is the non-authoritative write boundary for
external measurements. Changing the brief through the JSON path also requires a verbatim
human `--quote`.

Read with `abar --json status`, `project show`, and `history`. After a Session ends, use
`project session result <id>` for its bounded Material-by-Material result. Do not invent
finer-grained listing commands.

## Waiting and resuming

Only the human may answer a listening question, manually set current best, or accept a
Simplification Plan. Never call Judgment, manual-best, or
Simplification-decision interaction routes.

ABAR does not run, schedule, or restart the external agent. While a Session awaits an answer,
use the host environment's durable wait or wake-up mechanism when one exists. Otherwise,
return control to the human without simulating progress or answering the Session.

Whenever work resumes, start again with `status` and `project show --since <event_seq>`.
Treat the newly observed events and current authority as the source of truth rather than
continuing from assumptions made before the wait.
If status reports a degraded pre-release Workspace, preserve it unchanged and create a new
Workspace. The health response identifies the event sequence, type, and schema that stopped replay.

## Dogfooding feedback

When operating ABAR from its development checkout, treat friction observed in a real Project
as product feedback. If `.dev-docs/dogfooding.md` exists, record the goal, exact observed
behavior, impact, workaround, desired behavior, and status there. Record only behavior that
actually occurred; label unverified explanations as hypotheses. Keep ABAR product feedback out
of the audio Project note, which belongs to the research record. A workaround does not resolve
an entry. Mark it resolved only after the product change and regression verification are both
recorded.

## Choosing the next comparison

- Compare a new proposal with Project current best by default.
- If a counterpart is needed for diagnosis, prefer previous best, then in-use, then source.
- Use a general Session for a local hypothesis. Its `focus` is the one criterion shown to the listener and cannot update current best.
- Use `project session best-update --proposed <variant>` only when the proposal is ready to be judged against the complete Project brief. Do not use a local property as its criterion.
- Separate attributes through Variant design instead of multiplying questions. Keep the human answer as an overall A/B preference under one criterion.
- Use `same-check` or `repeat-check` sparingly when the comparison itself needs a perceptual consistency observation. These checks never vote on current best.
- Omit `--clip` to let ABAR spread automatic selection across Materials. When exact regions
  matter, repeat `--clip <id>` once per evidence item. ABAR preserves that order in the Plan and
  does not impose Material diversity on explicit selection, while the blind presentation order
  is randomized from the recorded Session seed.

### Calibrate meaning and mechanism large-first

When a local Session asks whether a perceptual word describes a mechanism, or whether a new
mechanism is audible at all, begin with a bounded dose that should be clearly discriminable. The
first question is what the mechanism sounds like and which defects it causes, not whether a
product-scale dose wins by a slight preference. Record expected defects as blockers and keep the
Session non-authoritative.

Do not compensate for an under-dosed proposal by adding more comparisons or asking the human to
resolve repeated subtle differences. If the listener reports that the difference is too small to
judge, preserve the partial Session as a bounded observation, stop that dose, and prepare a
stronger isolated Variant. After the perceptual meaning or mechanism winner is established, run a
separate dose-down comparison to find the smallest useful amount and then a complete-product
comparison against current best. Large-first does not waive mechanical safety checks, comparison
matching, blocker recording, or the sealed human-judgment boundary.

## What to revisit

Prepare a new confirmation Session when:

- current best won by a narrow margin;
- new listening material is attached;
- a new blocker appears on current best;
- the Project brief changes;
- the human explicitly asks for confirmation.

## Purpose and language

The Project brief is the only formal purpose. Notes hold the agent's current understanding and hypotheses; they never override the brief. Preserve useful perceptual language in comparison comments and Project notes rather than translating it prematurely into a metric.

## Developing Indicators

Indicators are observational. They help the agent generate and screen proposals, but they do
not replace the Project brief or vote on current best. ABAR does not calculate, validate,
combine, or optimize Indicator values.

### Exploring a possible Indicator

An empty Indicator registry is valid and does not put the Project into a special mode. Continue
blind A/B work without an Indicator whenever no useful measurement is known.

When evaluating a possible measurement, keep three claims separate:

1. **Mechanism evidence:** the value describes what a particular implementation changes.
2. **Perceptual evidence:** in controlled listening comparisons, the value's movement relates
   to human preference or a repeated defect description.
3. **Operating scope:** the relation remains useful on the Materials and mechanisms for which
   the agent intends to use it, without repeatedly violating a guard quality.

A moving value establishes only mechanism evidence. A full product-versus-source comparison
tests the value of the whole product configuration; it does not by itself attribute the result
to one metric. Conversely, a controlled mechanism comparison tests attribution but does not by
itself establish product value. There is no required ordering between them: prepare the
comparison that answers the current uncertainty.

Preserve the human's perceptual language, state a bounded hypothesis in the Project note, and
use general Sessions to test it. Materialize exact Variant/Clip audio with
`variant materialize`, compute measurements externally, and report values against the returned
AudioContent IDs. Record supporting and conflicting examples plus the scope in the note. A
relation supported only for one mechanism may still be useful when registered with that narrow
scope; additional Materials or mechanisms increase confidence but are not a registration gate.

Register an Indicator only after its formula, unit, subject kind, input contract, description,
and intended direction are stable enough to reproduce. Cite the relevant Sessions and state
known confounds and guard observations. Registration records a bounded working relationship;
it does not declare a universal metric or convert the Project into a scalar optimizer.

A `target` is a measured direction worth pursuing. It is a candidate operational explanation
of preference, not the formal purpose and not a weighted objective score. Use target reports
to guide candidate generation only within the scope supported by the listening evidence.

A `guard` is a regression signal for a quality that should not be lost. Derive guard candidates
from constraints in the Project brief, human blockers and comparison comments, and regressions seen
in losing Variants. Stress the suspected tradeoff through Variant design, confirm that the
quality matters through a general Session, then define the measurement and any `pass` or
`fail` rule. Report `pass` or `fail` only when that external definition supports the result;
otherwise report the guard as unconfirmed.

Each reported value must name both the exact AudioContent or PreparedPair subject and the
Variant that produced it. For Project current best, ABAR summarizes the latest report for each
subject with a median value; a guard fails if any summarized subject fails and is clear only
when every summarized subject passes. ABAR does not reuse a previous Variant's report. A
promising target or guard must continue to earn its role through human A/B evidence.

## Simplification boundary

If a simpler Variant is byte-identical after the primary Recipe across an explicit Clip scope, create a Simplification Plan. Only the human may accept it. Perceptual equivalence without byte identity is handled by the manual-best emergency path, with the supporting Session cited in the acknowledgement and note.
