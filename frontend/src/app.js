console.log("🚀 APP.JS HAS SUCCESSFULLY LOADED!");

// Set this to your local Python server address.
// When you deploy to Google Cloud, change this to your public Cloud Run URL!

const API_BASE_URL = "";

// ==========================================
// 1. GLOBAL INITIALIZATION & SYSTEM CHECK
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
    initializeApp();
});

async function initializeApp() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/system-status`);
        const status = await response.json();

        // Always show the dashboard
        fetchDashboardData(); 

    } catch (error) {
        console.error("System status check failed, defaulting to active season.", error);
        fetchDashboardData();
    }
}

// ==========================================
// 2. OFF-SEASON UTILITIES
// ==========================================

function enableOffSeasonMode() {
    // Hide standard grid, show glassmorphic pre-season screen
    document.getElementById('main-dashboard-grid').style.display = 'none';
    document.getElementById('off-season-home').classList.remove('hidden');

    // Block the "My Team" navigation link and show the toast
    const myTeamBtn = document.getElementById('nav-my-team');
    if (myTeamBtn) {
        myTeamBtn.addEventListener('click', (e) => {
            e.preventDefault();
            showToast("You can see your team insights when the next season starts.");
        });
    }

    const lastSeasonBtn = document.getElementById('last-season-btn');
    if (lastSeasonBtn) {
        lastSeasonBtn.addEventListener('click', () => {
            document.getElementById('off-season-home').classList.add('hidden');
            document.getElementById('main-dashboard-grid').style.display = '';
            fetchDashboardData();
        });
    }
}

function showToast(message) {
    const toast = document.getElementById('toast-notification');
    toast.innerText = message;
    toast.classList.remove('translate-y-full', 'opacity-0');
    toast.classList.add('translate-y-0', 'opacity-100');
    
    setTimeout(() => {
        toast.classList.remove('translate-y-0', 'opacity-100');
        toast.classList.add('translate-y-full', 'opacity-0');
    }, 3000);
}

// ==========================================
// 3. NORMAL DASHBOARD CODE
// ==========================================

async function fetchDashboardData() {
	try {
		// We use Promise.all to fetch all 4 endpoints at the exact same time, vastly speeding up page load
		const [picksRes, riskRes, fixtureRes, perfRes] = await Promise.all([
			fetch(`${API_BASE_URL}/api/top-picks`),
			fetch(`${API_BASE_URL}/api/risk-alerts`),
			fetch(`${API_BASE_URL}/api/target-fixture`),
			fetch(`${API_BASE_URL}/api/top-performers`)
		]);

		const picks = await picksRes.json();
		const risk = await riskRes.json();
		const fixture = await fixtureRes.json();
		const perf = await perfRes.json();

		populateTopPicks(picks.top_picks);
		populateRiskAlert(risk.alert);
		populateFixture(fixture.target_fixture);
		populatePerformers(perf.top_performers);

	} catch (error) {
		console.error("Dashboard Engine Error:", error);
	}
}

function populateTopPicks(data) {
	if (!data || data.length < 3) return;

	// #1 Pick (Haaland card)
	const pick0Bg = document.getElementById('pick-0-bg');
	if (pick0Bg) pick0Bg.style.backgroundImage = `url('${data[0].image_url}')`;
	const pick0Name = document.getElementById('pick-0-name');
	if (pick0Name) pick0Name.textContent = data[0].name;
	const pick0Sub = document.getElementById('pick-0-sub');
	if (pick0Sub) pick0Sub.textContent = `FWD • ${data[0].price}`;
	const pick0Proj = document.getElementById('pick-0-proj');
	if (pick0Proj) pick0Proj.textContent = `${data[0].projected_points}pts`;
	const pick0Index = document.getElementById('pick-0-index');
	if (pick0Index) pick0Index.textContent = data[0].custom_index;
	const pick0Own = document.getElementById('pick-0-own');
	if (pick0Own) pick0Own.textContent = `${data[0].ownership_percent}%`;

	// #2 Pick
	const pick1Bg = document.getElementById('pick-1-bg');
	if (pick1Bg) pick1Bg.style.backgroundImage = `url('${data[1].image_url}')`;
	const pick1Name = document.getElementById('pick-1-name');
	if (pick1Name) pick1Name.textContent = data[1].name;
	const pick1Index = document.getElementById('pick-1-index');
	if (pick1Index) pick1Index.textContent = data[1].custom_index;

	// #3 Pick
	const pick2Bg = document.getElementById('pick-2-bg');
	if (pick2Bg) pick2Bg.style.backgroundImage = `url('${data[2].image_url}')`;
	const pick2Name = document.getElementById('pick-2-name');
	if (pick2Name) pick2Name.textContent = data[2].name;
	const pick2Index = document.getElementById('pick-2-index');
	if (pick2Index) pick2Index.textContent = data[2].custom_index;
}

function populateRiskAlert(data) {
	if (!data) {
		const riskName = document.getElementById('risk-name');
		if (riskName) riskName.textContent = "No Alerts";
		const riskReason = document.getElementById('risk-reason');
		if (riskReason) riskReason.textContent = "Squad is healthy";
		return;
	}
	const riskName = document.getElementById('risk-name');
	if (riskName) riskName.textContent = data.name;
	const riskReason = document.getElementById('risk-reason');
	if (riskReason) riskReason.textContent = data.reason;
	const riskChance = document.getElementById('risk-chance');
	if (riskChance) riskChance.textContent = `Chance: ${data.chance}`;
	const riskBg = document.getElementById('risk-bg');
	if (riskBg) riskBg.style.backgroundImage = `url('${data.image_url}')`;
}

function populateFixture(data) {
	if (!data) return;
	const fixtureMatch = document.getElementById('fixture-match');
	if (fixtureMatch) fixtureMatch.textContent = data.match;
	const fixtureDiff = document.getElementById('fixture-diff');
	if (fixtureDiff) fixtureDiff.textContent = `Difficulty: ${data.difficulty}/5`;

	// Build the visual difficulty dots
	let dotsHtml = "";
	for (let i = 0; i < data.difficulty; i++) dotsHtml += `<div class="h-1.5 w-6 rounded-full bg-primary"></div>`;
	for (let i = 0; i < (5 - data.difficulty); i++) dotsHtml += `<div class="h-1.5 w-6 rounded-full bg-border-dark"></div>`;
	const fixtureDots = document.getElementById('fixture-dots');
	if (fixtureDots) fixtureDots.innerHTML = dotsHtml;
}

function populatePerformers(data) {
	if (!data) return;
	const container = document.getElementById('performers-container');
	if (!container) return;
	container.innerHTML = ""; // Clear loading text

	data.forEach(player => {
		const rankColor = player.rank === 1 ? "text-primary" : "text-text-muted";
		container.innerHTML += `
		<div class="flex items-center justify-between">
			<div class="flex items-center gap-3">
				<div class="relative">
					<div class="size-11 rounded-full bg-cover bg-center border-2 border-border-dark" style="background-image: url('${player.image_url}');"></div>
					<div class="absolute -bottom-1 -right-1 size-5 bg-background-dark rounded-full flex items-center justify-center border border-border-dark">
						<span class="text-[10px] font-bold ${rankColor}">${player.rank}</span>
					</div>
				</div>
				<div>
					<p class="text-sm font-bold">${player.name}</p>
					<p class="text-[11px] text-text-muted">${player.team}</p>
				</div>
			</div>
			<div class="text-right">
				<p class="text-sm font-bold text-white">${player.performance_index}</p>
				<p class="text-[10px] text-text-muted uppercase">Index</p>
			</div>
		</div>`;
	});
}

export {};

