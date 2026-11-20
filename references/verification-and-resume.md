# Verification and resume

## A small record that another session can use

For implementation, installation, or resumable work, keep a single `workflow.md` in a unique run folder. Use the user’s designated work area when provided. Otherwise use `video-workflows` under the active Codex home, or `watch-and-do/runs` under the platform’s per-user data directory. Keep extracted media in its evidence directory and link to it. Reuse the same record on follow-up. A summary-only request needs no persistent run record.

Include:

- **Source and evidence**: exact URL or file, relevant time ranges, cache paths and modality limits.
- **Goal and decisions**: chosen route, confirmed requirements and changes, implementation assumptions, authorized destination.
- **State and outputs**: current stage, real workspace, artifact paths, version and launch or repeat command.
- **Tools actually used**: record the software and CLI versions, the skills used, and the step each performed. When a step needed no separate skill, record that explicitly. Distinguish proposed substitutes and unknown versions. Preserve these facts in the local project experience and its public draft.
- **Checks and findings**: expected result, method and observed result; record fixes, failed attempts or rollbacks that affect the next decision.
- **Next**: one concrete action, blocked prerequisites and any hands-on checks still needed.

For “continue”, use the supplied record or project pointer; if neither is present, consult only the local run directory or the active project index. When multiple runs plausibly match, disambiguate before mutating. Check the artifact exists and that its version and source match the record before reuse. Re-run stale or failed checks, not the entire extraction. Handoff on request by returning the record location plus the immediate next action. Do not create or message another chat unless asked.

## Check the result that matters

Write acceptance criteria in terms of observable outcome. Test on the intended surface where available: run the app and interact with it, inspect the output file, or check the actual installed command or discoverable skill. Report results by the evidence obtained:

- **Program check**: build, unit test, simulation, scripted replay or inspection, with scope.
- **Real run**: actual environment, action and observed output.
- **Visual or audio review**: which rendered state or recording was inspected.
- **Hands-on**: what a real person or physical device confirmed, or the exact outstanding check.

Passing a mock webcam or a build does not verify live gestures, and existence of a skill file does not by itself verify discovery or behavior. If the user reports that a checked result still feels wrong, record the failure in their terms, reproduce what is practical, investigate the cause, fix it, rerun the affected checks, then ask for the specific hands-on retest if needed.

When the active environment already requires and authorizes long-term project memory, use `obsidian-memory` and its project rules at the relevant checkpoints. Record actual results, material failures, and the recovery pointer. Keep unverified ideas separate and omit secrets, cookies, and private chat text. Without a configured memory workflow, the work record is the durable handoff.
