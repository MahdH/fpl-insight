import { $, esc, xp, setText, setImage, hiRes, countUp, fill, reveal, toast, initChrome, loadSeasonLabel } from "./ui.js";

initChrome();
reveal();
loadSeasonLabel();
loadDashboard();

async function getJSON(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${path} responded ${res.status}`);
    return res.json();
}

// Each endpoint renders independently, so one slow or failing call never blanks the others.
async function loadDashboard() {
    const sections = [
        ["/api/top-picks", (d) => populateTopPicks(d.top_picks)],
        ["/api/risk-alerts", (d) => populateRiskAlert(d.alert)],
        ["/api/target-fixture", (d) => populateFixture(d.target_fixture)],
        ["/api/top-performers", (d) => populatePerformers(d.top_performers)],
    ];

    const results = await Promise.allSettled(sections.map(async ([path, render]) => render(await getJSON(path))));

    const failed = results.filter((r) => r.status === "rejected");
    failed.forEach((r) => console.error("Dashboard Engine Error:", r.reason));
    if (failed.length) toast("Couldn't load some live data. Pull to refresh and try again.");

    clearSkeletons();
}

// Anything still shimmering after loading (error or empty data) becomes a quiet dash.
function clearSkeletons() {
    document.querySelectorAll("main .skel").forEach((el) => {
        if (el.hasAttribute("aria-hidden")) return;
        el.textContent = "—";
        el.classList.remove("skel");
    });
    const list = $("performers-container");
    if (list?.getAttribute("aria-busy") === "true") {
        list.innerHTML = `<li class="state-msg">Performance data isn't available right now.</li>`;
        list.setAttribute("aria-busy", "false");
    }
}

function populateTopPicks(data) {
    if (!data || data.length < 3) return;
    const [first, second, third] = data;

    const hero = $("pick-0-img");
    hero.alt = first.name;
    setImage(hero, [hiRes(first.image_url), first.image_url]);
    setText("pick-0-name", first.name);
    setText("pick-0-sub", `FWD • ${first.price}`);
    countUp("pick-0-index", xp(first.custom_index));
    countUp("pick-0-proj", first.projected_points);
    countUp("pick-0-own", first.ownership_percent);

    [second, third].forEach((pick, i) => {
        const n = i + 1;
        setImage(`pick-${n}-img`, [pick.image_url]);
        setText(`pick-${n}-name`, pick.name);
        countUp(`pick-${n}-index`, xp(pick.custom_index));
        fill(`pick-${n}-bar`, (pick.custom_index / first.custom_index) * 100);
    });
}

function populateRiskAlert(data) {
    const card = $("risk-name").closest(".risk");

    if (!data) {
        setText("risk-name", "No alerts");
        setText("risk-reason", "Squad is healthy");
        card.querySelector(".avatar").hidden = true;
        $("risk-foot").hidden = true;
        return;
    }

    setImage("risk-img", [data.image_url]);
    setText("risk-name", data.name);
    setText("risk-reason", data.reason);

    const chance = parseFloat(data.chance);
    countUp("risk-chance", String(chance));
    fill("risk-gauge", chance);

    if (data.ownership) {
        const chip = document.createElement("span");
        chip.className = "chip chip--sm risk__chip";
        chip.textContent = `${data.ownership} owned`;
        $("risk-reason").after(chip);
    }
}

function populateFixture(data) {
    if (!data) return;

    const [home, away] = String(data.match).split(" vs ");
    const match = $("fixture-match");
    match.classList.remove("skel");
    match.innerHTML = away ? `${esc(home)}<span>vs</span>${esc(away)}` : esc(data.match);

    const edge = data.team ? ` · ${data.team} xG ${data.expected_goals}` : "";
    setText("fixture-diff", `Difficulty ${data.difficulty}/5${edge}`);
    const dots = $("fixture-dots");
    dots.setAttribute("aria-label", `Fixture difficulty ${data.difficulty} out of 5`);
    [...dots.children].forEach((dot, i) => {
        dot.style.setProperty("--n", i);
        requestAnimationFrame(() => requestAnimationFrame(() => dot.classList.toggle("on", i < data.difficulty)));
    });
}

function populatePerformers(data) {
    const list = $("performers-container");
    if (!data || !list) return;

    list.innerHTML = data
        .map(
            (p) => `
        <li class="perf__item" data-reveal>
            <div class="perf__who">
                <span class="avatar-wrap">
                    <span class="avatar avatar--lg"><img alt="" /></span>
                    <b class="rank rank--${esc(p.rank)}">${esc(p.rank)}</b>
                </span>
                <div>
                    <p class="perf__name">${esc(p.name)}</p>
                    <p class="perf__team">${esc(p.team)}</p>
                    <p class="perf__form">Form <b>${esc(p.form)}</b></p>
                </div>
            </div>
            <div class="perf__stat">
                <p class="metric">${esc(xp(p.performance_index))}</p>
                <p class="label-sm">xP · 5 GWs</p>
            </div>
        </li>`
        )
        .join("");
    list.setAttribute("aria-busy", "false");

    const items = list.querySelectorAll(".perf__item");
    data.forEach((p, i) => {
        setImage(items[i].querySelector("img"), [p.image_url]);
        countUp(items[i].querySelector(".metric"), xp(p.performance_index));
    });
    reveal(list);
}
