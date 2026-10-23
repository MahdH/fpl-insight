import { $, esc, xp, setImage, reveal, toast, initChrome, loadSeasonLabel } from "./ui.js";

initChrome();
reveal();
loadSeasonLabel();

const POSITIONS = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
// Goalkeeper at the top of the pitch, forwards at the bottom.
const ROWS = { 1: "pitch-gk", 2: "pitch-def", 3: "pitch-mid", 4: "pitch-fwd" };

const CHIP_ORDER = ["none", "wildcard", "freehit", "bboost", "3xc"];
const CHIP_LABELS = { none: "No chip", wildcard: "Wildcard", freehit: "Free Hit", bboost: "Bench Boost", "3xc": "Triple Captain" };
const REBUILD_CHIPS = new Set(["wildcard", "freehit"]); // unlimited transfers: the whole squad is rebuilt
const PLAN_VIEW_LABELS = { wildcard: "Wildcard squad", freehit: "Free Hit squad" };
const MAX_TRANSFERS = 5;
const HIT_COST = 4;
const CARD_LIMIT = 3; // more swaps than this are shown as compact rows

const DEFAULT_TEAM = { name: "Your squad", meta: "Enter a Team ID to begin", gameweek: "Game Week --" };

const state = { managerId: null, current: null, plan: null, chip: "none", view: "current", transfers: "1", request: 0 };

const form = $("manager-form");
const input = $("manager-id-input");
const submit = form.querySelector("button");
const pitchEmpty = $("pitch-empty");
const controls = $("plan-controls");
const chipGroup = $("chip-group");
const transferSelect = $("transfer-count");
const suggestions = $("suggestions-container");

form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadManagerTeam();
});

chipGroup.addEventListener("click", (event) => {
    const button = event.target.closest(".chip-btn");
    if (!button || button.disabled || button.dataset.chip === state.chip) return;
    state.chip = button.dataset.chip;
    markChip();
    requestPlan({ chipChanged: true });
});

transferSelect.addEventListener("change", () => {
    state.transfers = transferSelect.value;
    requestPlan();
});

$("pitch-toggle").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.view = button.dataset.view;
    showSquad();
});

// ---------- Loading a team ----------

function setTeamHeader({ name, meta, gameweek }) {
    $("team-name").textContent = name;
    $("team-meta").textContent = meta;
    $("gw-label").textContent = gameweek;
}

function setPitchMessage(text, tone) {
    pitchEmpty.textContent = text;
    pitchEmpty.classList.toggle("is-error", tone === "error");
    pitchEmpty.classList.remove("is-hidden");
}

function hidePlanDetails() {
    for (const id of ["plan-summary", "plan-highlight", "plan-notes", "transfer-note"]) $(id).hidden = true;
}

function setLoading() {
    state.request++; // abandons any plan still on its way for the previous team
    Object.assign(state, { current: null, plan: null, chip: "none", view: "current" });
    Object.values(ROWS).forEach((id) => ($(id).innerHTML = ""));
    setPitchMessage("Fetching squad data…");
    $("bench-container").innerHTML = "";
    controls.hidden = true;
    $("pitch-toggle").hidden = true;
    hidePlanDetails();
    suggestions.innerHTML = `<p class="state-msg state-msg--busy">Finding the best swaps for your squad…</p>`;
    $("bank-chip").textContent = "Recommended";
    $("team-name").textContent = "Loading…";
    $("team-meta").textContent = "";
}

async function loadManagerTeam() {
    const managerId = input.value.trim();
    if (!/^\d+$/.test(managerId)) {
        toast("Please enter a valid FPL Manager ID.");
        input.focus();
        return;
    }

    submit.disabled = true;
    setLoading();

    try {
        // Fetch both endpoints concurrently. The squad is essential; the plan can fail on its own.
        const [teamRes, planRes] = await Promise.all([
            fetch(`/api/my-team/${managerId}`),
            fetch(`/api/transfer-suggestions/${managerId}`),
        ]);
        const teamData = await teamRes.json();
        if (teamData.error) throw new Error(teamData.error);

        const plan = planRes.ok ? await planRes.json().catch(() => ({ error: true })) : { error: true };

        state.managerId = managerId;
        state.current = teamData.squad;
        setTeamHeader({
            name: teamData.team_name || "Your squad",
            meta: [teamData.manager_name, `ID ${teamData.manager_id}`].filter(Boolean).join(" · "),
            gameweek: `Game Week ${teamData.gameweek}`,
        });

        showSquad();
        if (!plan.error) renderControls(teamData, plan);
        applyPlan(plan);

        input.blur();
        if (window.matchMedia("(max-width: 1023px)").matches) {
            $("pitch-empty").closest(".pitch").scrollIntoView({ behavior: "smooth", block: "start" });
        }
    } catch (error) {
        console.error(error);
        toast("Could not load team. Check the ID and try again.");
        setTeamHeader(DEFAULT_TEAM);
        setPitchMessage("Error loading team.", "error");
        suggestions.innerHTML = `<p class="state-msg state-msg--error">Engine failed to run.</p>`;
    } finally {
        submit.disabled = false;
    }
}

// ---------- Chip and transfer controls ----------

function renderControls(teamData, plan) {
    const chips = teamData.chips;
    const available = new Set(chips.available);
    const used = new Set(chips.used);

    chipGroup.innerHTML = CHIP_ORDER.map((chip) => {
        const unavailable = chip !== "none" && !available.has(chip);
        const reason = used.has(chip) ? "Already played this half of the season" : "Not available this gameweek";
        return `<button type="button" class="chip-btn${unavailable ? " chip-btn--used" : ""}" role="radio"
                    data-chip="${chip}" aria-checked="${chip === state.chip}"
                    ${unavailable ? `disabled title="${esc(reason)}"` : ""}>${CHIP_LABELS[chip]}</button>`;
    }).join("");

    const free = teamData.free_transfers ?? 1;
    transferSelect.innerHTML = Array.from({ length: MAX_TRANSFERS }, (_, i) => {
        const count = i + 1;
        const hits = Math.max(0, count - free);
        const cost = hits ? `up to −${hits * HIT_COST} pts` : "free";
        return `<option value="${count}">${count} transfer${count > 1 ? "s" : ""} · ${cost}</option>`;
    }).join("");
    transferSelect.value = String(plan.transfers_requested ?? free);
    state.transfers = transferSelect.value;
    transferSelect.disabled = false;
    controls.hidden = false;
}

function markChip() {
    chipGroup.querySelectorAll(".chip-btn").forEach((button) => {
        button.setAttribute("aria-checked", String(button.dataset.chip === state.chip));
    });

    // Wildcard and Free Hit have no transfer limit, so the dropdown says so and is locked.
    const rebuild = REBUILD_CHIPS.has(state.chip);
    const unlimited = transferSelect.querySelector('option[value="unlimited"]');
    if (rebuild && !unlimited) {
        transferSelect.insertAdjacentHTML("beforeend", `<option value="unlimited">Unlimited · no hit</option>`);
    } else if (!rebuild && unlimited) {
        unlimited.remove();
    }
    transferSelect.value = rebuild ? "unlimited" : state.transfers;
    transferSelect.disabled = rebuild;
}

function renderHint(plan) {
    const hint = $("transfer-hint");
    if (REBUILD_CHIPS.has(plan.chip)) {
        hint.textContent = `${CHIP_LABELS[plan.chip]} gives unlimited transfers with no points hit.`;
    } else if (plan.free_transfers_known) {
        const free = plan.free_transfers;
        hint.textContent = `You have ${free} free transfer${free === 1 ? "" : "s"}, worked out from your history. Each extra costs −${HIT_COST} pts.`;
    } else {
        hint.textContent = `Couldn't read your free transfers, so 1 is assumed. Each extra costs −${HIT_COST} pts.`;
    }
}

async function requestPlan({ chipChanged = false } = {}) {
    const request = ++state.request;
    const params = new URLSearchParams({ chip: state.chip });
    if (!REBUILD_CHIPS.has(state.chip)) params.set("transfers", transferSelect.value);

    controls.classList.add("is-busy");
    hidePlanDetails();
    suggestions.innerHTML = `<p class="state-msg state-msg--busy">Optimising your squad…</p>`;

    let plan;
    try {
        const response = await fetch(`/api/transfer-suggestions/${state.managerId}?${params}`);
        plan = response.ok ? await response.json() : { error: "Couldn't work out transfers right now. Try again." };
    } catch (error) {
        console.error(error);
        plan = { error: "Couldn't work out transfers right now. Try again." };
    }
    if (request !== state.request) return; // a newer choice has replaced this one

    controls.classList.remove("is-busy");
    applyPlan(plan, { chipChanged });
}

// ---------- Showing a plan ----------

function applyPlan(plan, { chipChanged = false } = {}) {
    state.plan = plan.error ? null : plan;

    if (plan.error) {
        const message = typeof plan.error === "string" ? plan.error : "Couldn't work out transfers for this squad.";
        suggestions.innerHTML = `<p class="state-msg state-msg--error">${esc(message)}</p>`;
        hidePlanDetails();
        $("pitch-toggle").hidden = true;
        state.view = "current";
        showSquad();
        return;
    }

    $("bank-chip").textContent = `Bank ${plan.bank}`;
    renderHint(plan);
    renderSummary(plan);
    renderHighlight(plan.highlight);
    renderSwaps(plan);
    renderNotes(plan.notes);

    // Offer a preview of the proposed squad whenever the plan changes it.
    const changes = plan.suggestions.length > 0;
    $("pitch-toggle").hidden = !changes;
    $("pitch-toggle-plan").textContent = PLAN_VIEW_LABELS[plan.chip] || "After transfers";
    if (!changes) state.view = "current";
    else if (chipChanged) state.view = REBUILD_CHIPS.has(plan.chip) ? "plan" : "current";
    showSquad();
}

function showSquad() {
    const squad = state.view === "plan" && state.plan ? state.plan.squad : state.current;
    if (!squad) return;
    renderPitch(squad.starting_xi);
    renderBench(squad.bench);
    document.querySelectorAll("#pitch-toggle button").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
    });
}

const signed = (value) => `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(1)}`;

function renderSummary(plan) {
    const summary = plan.summary;
    const box = $("plan-summary");
    if (summary.transfers_used === 0) {
        box.hidden = true;
        return;
    }

    const rebuild = REBUILD_CHIPS.has(plan.chip);
    const stats = rebuild
        ? [
              ["Projected gain", `${signed(summary.xp_gain)} xP`, summary.horizon],
              ["Players changed", String(summary.transfers_used), "no points hit"],
              ["Bank after", summary.bank_after, "after the rebuild"],
          ]
        : [
              ["Projected gain", `${signed(summary.xp_gain)} xP`, summary.horizon],
              ["Points hit", summary.hit_cost ? `−${summary.hit_cost}` : "None", `${summary.transfers_used} transfer${summary.transfers_used === 1 ? "" : "s"}`],
              ["Net gain", `${signed(summary.net_gain)} xP`, `${summary.bank_after} in the bank`],
          ];

    box.innerHTML = stats
        .map(
            ([label, value, note], i) => `
        <div class="summary__stat${i === 2 && !rebuild && summary.net_gain < 0 ? " is-negative" : ""}">
            <span class="label-sm">${esc(label)}</span>
            <strong>${esc(value)}</strong>
            <span class="label-sm">${esc(note)}</span>
        </div>`
        )
        .join("");
    box.hidden = false;
}

function renderHighlight(highlight) {
    const box = $("plan-highlight");
    if (!highlight) {
        box.hidden = true;
        return;
    }

    if (highlight.kind === "bench") {
        box.innerHTML = `
            <span class="badge"><svg class="icon" aria-hidden="true"><use href="/src/icons.svg#i-bench"/></svg></span>
            <div>
                <p class="info__title">Bench Boost</p>
                <p class="info__text">Your bench is projected to add <b>${esc(signed(highlight.xp_next))} xP</b> next gameweek, and all of it counts with the chip.</p>
            </div>`;
    } else {
        box.innerHTML = `
            <span class="avatar avatar--lg"><img alt="" /></span>
            <div>
                <p class="info__title">Triple Captain pick</p>
                <p class="info__text"><b>${esc(highlight.name)}</b> (${esc(highlight.team)}, ${esc(highlight.price)}) is projected for
                ${esc(xp(highlight.xp_next))} xP next gameweek. The chip adds about <b>${esc(signed(highlight.xp_next))} points</b> over a normal captain.</p>
            </div>`;
        setImage(box.querySelector("img"), [highlight.image_url]);
    }
    box.hidden = false;
}

function costLabel(change) {
    if (change > 0) return `Costs £${change.toFixed(1)}m more`;
    if (change < 0) return `Saves £${Math.abs(change).toFixed(1)}m`;
    return "Same price";
}

function swapSide(player, role) {
    return `
        <div class="swap__side swap__side--${role}">
            <span class="swap__tag">${role === "out" ? "Sell" : "Buy"}</span>
            <span class="avatar avatar--lg"><img alt="" /></span>
            <p class="swap__name">${esc(player.name)}</p>
            <p class="swap__meta">${esc(POSITIONS[player.position])} • ${esc(player.team)} • ${esc(player.price)}</p>
            <p class="swap__xp">${esc(xp(player.xp_horizon))} xP</p>
        </div>`;
}

function swapCard(swap, i) {
    return `
        <article class="swap" style="--i: ${i}" aria-label="Sell ${esc(swap.out.name)}, buy ${esc(swap.in.name)}">
            <div class="swap__players">
                ${swapSide(swap.out, "out")}
                <span class="swap__arrow" aria-hidden="true"><svg class="icon"><use href="/src/icons.svg#i-arrow-right"/></svg></span>
                ${swapSide(swap.in, "in")}
            </div>
            <div class="swap__foot">
                <span class="chip chip--sm chip--gain">${esc(signed(swap.xp_gain))} xP</span>
                <span class="chip chip--sm">${esc(costLabel(swap.cost_change))}</span>
                <p class="swap__reason">${esc(swap.reason)}</p>
            </div>
        </article>`;
}

function swapRow(swap, i) {
    return `
        <article class="swap-row" style="--i: ${Math.min(i, 8)}" aria-label="Sell ${esc(swap.out.name)}, buy ${esc(swap.in.name)}">
            <span class="avatar"><img alt="" /></span>
            <div class="swap-row__who">
                <p class="swap__name">${esc(swap.out.name)}</p>
                <p class="swap__meta">${esc(swap.out.price)}</p>
            </div>
            <span class="swap-row__arrow" aria-hidden="true"><svg class="icon"><use href="/src/icons.svg#i-arrow-right"/></svg></span>
            <span class="avatar"><img alt="" /></span>
            <div class="swap-row__who">
                <p class="swap__name">${esc(swap.in.name)}</p>
                <p class="swap__meta">${esc(swap.in.price)}</p>
            </div>
            <span class="chip chip--sm chip--gain">${esc(signed(swap.xp_gain))}</span>
            <p class="swap-row__reason"><b>${esc(POSITIONS[swap.out.position])}</b> · ${esc(swap.reason)}</p>
        </article>`;
}

function renderSwaps(plan) {
    const swaps = plan.suggestions;
    if (swaps.length === 0) {
        suggestions.innerHTML = `<p class="state-msg">No transfers needed this gameweek.</p>`;
        $("transfer-note").hidden = true;
        return;
    }

    const compact = swaps.length > CARD_LIMIT;
    suggestions.classList.toggle("swaps--compact", compact);
    suggestions.innerHTML = swaps.map((swap, i) => (compact ? swapRow(swap, i) : swapCard(swap, i))).join("");

    // Images appear in the order out, in, out, in, ...
    hydrateImages(
        suggestions,
        swaps.flatMap((swap) => [swap.out, swap.in])
    );
    $("transfer-note").hidden = false;
}

function renderNotes(notes) {
    const list = $("plan-notes");
    list.innerHTML = (notes || []).map((note) => `<li>${esc(note)}</li>`).join("");
    list.hidden = !notes || notes.length === 0;
}

// ---------- Pitch and bench ----------

function renderPitch(starters) {
    let order = 0;
    for (const [position, rowId] of Object.entries(ROWS)) {
        const players = starters.filter((p) => p.position === Number(position));
        const row = $(rowId);
        row.innerHTML = players.map((p) => playerToken(p, order++)).join("");
        hydrateImages(row, players);
    }
    pitchEmpty.classList.add("is-hidden");
}

function playerToken(player, order) {
    let badge = "";
    if (player.is_captain) badge = `<span class="player__badge" title="Captain">C</span>`;
    else if (player.is_vice_captain) badge = `<span class="player__badge player__badge--v" title="Vice-captain">V</span>`;

    return `
        <div class="player${player.is_new ? " player--new" : ""}" style="--i: ${order}">
            <div class="player__img">
                <span class="avatar"><img alt="" /></span>
                ${badge}
                ${player.is_new ? `<span class="player__new">New</span>` : ""}
            </div>
            <span class="player__name">${esc(player.name)}</span>
            <span class="player__price">${esc(player.price)}</span>
        </div>`;
}

function renderBench(bench) {
    const container = $("bench-container");
    container.innerHTML = bench
        .map(
            (p, i) => `
        <div class="bench__item${p.is_new ? " bench__item--new" : ""}" style="--i: ${i}">
            <span class="avatar"><img alt="" /></span>
            <span class="bench__name">${esc(p.name)}</span>
            <span class="bench__meta">${esc(POSITIONS[p.position])} • ${esc(p.price)}</span>
        </div>`
        )
        .join("");
    hydrateImages(container, bench);
}

function hydrateImages(container, players) {
    container.querySelectorAll("img").forEach((img, i) => setImage(img, [players[i].image_url]));
}
