import { $, esc, xp, setImage, reveal, toast, initChrome, loadSeasonLabel } from "./ui.js";

initChrome();
reveal();
loadSeasonLabel();

const POSITIONS = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
// Goalkeeper at the top of the pitch, forwards at the bottom.
const ROWS = { 1: "pitch-gk", 2: "pitch-def", 3: "pitch-mid", 4: "pitch-fwd" };

const DEFAULT_TEAM = { name: "Your squad", meta: "Enter a Team ID to begin", gameweek: "Game Week --" };

const form = $("manager-form");
const input = $("manager-id-input");
const submit = form.querySelector("button");
const pitchEmpty = $("pitch-empty");

form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadManagerTeam();
});

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

function setLoading() {
    Object.values(ROWS).forEach((id) => ($(id).innerHTML = ""));
    setPitchMessage("Fetching squad data…");
    $("bench-container").innerHTML = "";
    $("suggestions-container").innerHTML = `<p class="state-msg state-msg--busy">Finding the best swaps for your squad…</p>`;
    $("transfer-note").hidden = true;
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
        // Fetch both endpoints concurrently. The squad is essential; transfers can fail on their own.
        const [teamRes, suggestionsRes] = await Promise.all([
            fetch(`/api/my-team/${managerId}`),
            fetch(`/api/transfer-suggestions/${managerId}`),
        ]);
        const teamData = await teamRes.json();
        if (teamData.error) throw new Error(teamData.error);

        const suggestionsData = await suggestionsRes.json().catch(() => ({ error: true }));

        setTeamHeader({
            name: teamData.team_name || "Your squad",
            meta: [teamData.manager_name, `ID ${teamData.manager_id}`].filter(Boolean).join(" · "),
            gameweek: `Game Week ${teamData.gameweek}`,
        });

        renderPitch(teamData.squad.starting_xi);
        renderBench(teamData.squad.bench);
        renderSuggestions(suggestionsData);

        input.blur();
        if (window.matchMedia("(max-width: 1023px)").matches) {
            $("pitch-empty").closest(".pitch").scrollIntoView({ behavior: "smooth", block: "start" });
        }
    } catch (error) {
        console.error(error);
        toast("Could not load team. Check the ID and try again.");
        setTeamHeader(DEFAULT_TEAM);
        setPitchMessage("Error loading team.", "error");
        $("suggestions-container").innerHTML = `<p class="state-msg state-msg--error">Engine failed to run.</p>`;
    } finally {
        submit.disabled = false;
    }
}

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
        <div class="player" style="--i: ${order}">
            <div class="player__img">
                <span class="avatar"><img alt="" /></span>
                ${badge}
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
        <div class="bench__item" style="--i: ${i}">
            <span class="avatar"><img alt="" /></span>
            <span class="bench__name">${esc(p.name)}</span>
            <span class="bench__meta">${esc(POSITIONS[p.position])} • ${esc(p.price)}</span>
        </div>`
        )
        .join("");
    hydrateImages(container, bench);
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

function renderSuggestions(data) {
    const container = $("suggestions-container");

    if (data.error) {
        container.innerHTML = `<p class="state-msg state-msg--error">Couldn't work out transfers for this squad.</p>`;
        return;
    }

    if (data.bank) $("bank-chip").textContent = `Bank ${data.bank}`;

    const swaps = data.suggestions || [];
    if (swaps.length === 0) {
        container.innerHTML = `<p class="state-msg">No clear upgrades right now. Your squad looks well set for the next 5 gameweeks.</p>`;
        return;
    }

    container.innerHTML = swaps
        .map(
            (s, i) => `
        <article class="swap" style="--i: ${i}" aria-label="Sell ${esc(s.out.name)}, buy ${esc(s.in.name)}">
            <div class="swap__players">
                ${swapSide(s.out, "out")}
                <span class="swap__arrow" aria-hidden="true"><svg class="icon"><use href="/src/icons.svg#i-arrow-right"/></svg></span>
                ${swapSide(s.in, "in")}
            </div>
            <div class="swap__foot">
                <span class="chip chip--sm chip--gain">+${esc(xp(s.xp_gain))} xP · 5 GWs</span>
                <span class="chip chip--sm">${esc(costLabel(s.cost_change))}</span>
                <p class="swap__reason">${esc(s.reason)}</p>
            </div>
        </article>`
        )
        .join("");

    // Images appear in the order out, in, out, in, ...
    hydrateImages(
        container,
        swaps.flatMap((s) => [s.out, s.in])
    );
    $("transfer-note").hidden = false;
}

function hydrateImages(container, players) {
    container.querySelectorAll("img").forEach((img, i) => setImage(img, [players[i].image_url]));
}
