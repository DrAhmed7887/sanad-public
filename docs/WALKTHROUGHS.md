# Judge-facing local walkthroughs

This guide covers the six walkthroughs on the generated board (`dist/board.html`) and the Screen 1 quick controls. Start each flow by reloading the page to clear simulated workflow overlays. You can jump straight to key episodes using the three one-click buttons (**Bed 1 R1 @ 22:20**, **Bed 6 Late Fluid @ 02:00**, **Bed 9 Stale Feed @ 01:15**), step with **5 min ->** and **<- 5 min**, or test combinations in the **Test Custom Bed State** panel on Screen 1.

## 1. Orientation, missing inputs, and non-triggering text

This walkthrough shows how the board separates missing inputs from silent beds.

1. Choose **Night nurse view**. The board starts at **19:00 on November 20, 2026** with 17 fictional bed tiles.
2. Inspect **Bed 2**: R1 is `unknown` with `sat_not_recorded`.
3. Inspect **Bed 7**: when no configured rule is `met`, the tile says `No configured rule triggered on the available data`.
4. Optionally inspect **Bed 14** for `unknown/weight_missing`; the demonstration does not guess a missing weight.

## 2. R1 review wording and source lines

This walkthrough checks the SBT screen wording and criterion provenance.

1. Click **Bed 1 R1 @ 22:20** from Screen 1 (or choose **On-call doctor view** and jump to **22:20**).
2. Open the **Bed 1 / R1** episode raised at 22:20 in **On-call doctor view**.
3. The selected cell shows R1 `met`; the review panel shows the approved wording and eight static criterion/source rows (criteria 0, a-f, and duration).

## 3. Acknowledgement does not complete a check

This walkthrough verifies that workflow acknowledgement leaves the R3 evaluation `met`.

1. Reload and choose **Night nurse view**; advance to **01:10**.
2. Open **Inbox: N open (simulated)** and select **Bed 10 / R3**. The ward-tile route reaches the same bed detail.
3. R3 is `met` and its workflow is `notified`.
4. Select **Acknowledge (simulated)**. The workflow changes to `acknowledged`; the R3 evaluation remains `met` because no new check was recorded by that action.

## 4. A stale feed remains visible

This walkthrough shows how stale observations raise a visible feed alert instead of silence.

1. Click **Bed 9 Stale Feed @ 01:15** (or choose **Night nurse view** and jump to **01:15**).
2. The banner reads `feed alert · beds 9`, and Bed 9 has a visible feed chip.
3. Bed 9's observation-based R1 and R2a cells are `unknown` with `stale_data`. The failure is not folded into the non-triggering text.

## 5. Combined R2 review at the documentation boundary

This walkthrough demonstrates as-known-at timing when a late fluid record arrives.

1. Click **Bed 6 Late Fluid @ 02:00** or open **On-call doctor view** and jump to **02:00**.
2. Open the still-open **Bed 6 / R2** item.
3. R2a and R2b are both `met`, and the combined review message is visible.
4. The underlying fictional scenario includes a fluid transaction with event time 20:00 and documented time 02:00; the board changes only when that record becomes known. See [Bed 6 in the scenario oracle](../data/SCENARIOS.md) for the expected timings.

## 6. Simulated deferral and reload reset

This walkthrough verifies memory-only workflow overlays and reload reset.

1. Reload and choose **On-call doctor view**; advance to **01:30**.
2. Open Bed 15's new R1 episode.
3. Keep a listed reason, choose owner **charge nurse** and until **01:30**, then select **Deferred (simulated)**.
4. The workflow chip reads `deferred · charge nurse · until 01:30`; the engine's R1 evaluation remains `met`.
5. Reload the page: the simulated workflow overlay is gone. Dataset-documented deferrals are distinct from these memory-only overlays and still replay from the precomputed cells.
