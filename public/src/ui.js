// Shared UI helpers for both pages: image loading, motion, toast, and page chrome.

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

export const FALLBACK_IMG =
    "https://resources.premierleague.com/premierleague/photos/players/110x140/Photo-Missing.png";

const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => entities[c]);

export const $ = (id) => document.getElementById(id);

// Expected points always read with one decimal (JSON turns 20.0 into 20).
export const xp = (value) => Number(value).toFixed(1);

// Swap a skeleton for real text.
export function setText(el, text) {
    if (typeof el === "string") el = $(el);
    if (!el) return;
    el.textContent = text;
    el.classList.remove("skel");
}

// Try each URL in order, fading the image in once one loads.
export function setImage(img, urls) {
    if (typeof img === "string") img = $(img);
    if (!img) return;
    const queue = [...urls.filter(Boolean), FALLBACK_IMG];
    img.classList.remove("is-loaded");
    img.onload = () => img.classList.add("is-loaded");
    img.onerror = () => {
        const next = queue.shift();
        if (next) img.src = next;
    };
    img.src = queue.shift();
}

// Player art ships at 110x140; the same asset path has a retina-sharp 250x250 variant.
export const hiRes = (url) => (url ? url.replace("/110x140/", "/250x250/") : url);

// Animate a number from 0 to its final value. Keeps the API's own decimal precision.
export function countUp(el, raw, { duration = 900 } = {}) {
    if (typeof el === "string") el = $(el);
    if (!el) return;
    const text = String(raw);
    const target = parseFloat(text);
    el.classList.remove("skel");
    if (Number.isNaN(target) || reduceMotion.matches) {
        el.textContent = text;
        return;
    }
    const decimals = (text.split(".")[1] || "").length;
    const start = performance.now();
    const tick = (now) => {
        const t = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - t, 3);
        el.textContent = (target * eased).toFixed(decimals);
        if (t < 1) requestAnimationFrame(tick);
        else el.textContent = text;
    };
    requestAnimationFrame(tick);
}

// Grow a bar/gauge from empty on the next frame so the CSS transition runs.
export function fill(el, percent) {
    if (typeof el === "string") el = $(el);
    if (!el) return;
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    requestAnimationFrame(() => requestAnimationFrame(() => el.style.setProperty("--p", value)));
}

// Fade/slide elements in as they enter the viewport, lightly staggered per batch.
let revealObserver;
export function reveal(root = document) {
    const targets = root.querySelectorAll("[data-reveal]:not(.is-in)");
    if (!("IntersectionObserver" in window) || reduceMotion.matches) {
        targets.forEach((el) => el.classList.add("is-in"));
        return;
    }
    revealObserver ??= new IntersectionObserver(
        (entries) => {
            let i = 0;
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.style.setProperty("--i", Math.min(i++, 8));
                entry.target.classList.add("is-in");
                revealObserver.unobserve(entry.target);
            });
        },
        { rootMargin: "0px 0px -6% 0px", threshold: 0.08 }
    );
    targets.forEach((el) => revealObserver.observe(el));

    // Safety net: never leave on-screen content hidden if the observer is slow to fire.
    setTimeout(() => {
        targets.forEach((el) => {
            if (!el.classList.contains("is-in") && el.getBoundingClientRect().top < window.innerHeight) {
                el.classList.add("is-in");
            }
        });
    }, 1500);
}

let toastTimer;
export function toast(message) {
    const el = $("toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("is-visible"), 3200);
}

// Elements every page shares: the date chip and the sticky mobile bar's scrolled state.
export function initChrome() {
    const date = $("today");
    if (date) {
        date.textContent = new Date().toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
        });
    }

    const topbar = document.querySelector(".topbar");
    if (topbar && "IntersectionObserver" in window) {
        const sentinel = document.createElement("div");
        sentinel.setAttribute("aria-hidden", "true");
        sentinel.style.cssText = "position:absolute;top:0;height:1px;width:1px;pointer-events:none";
        document.body.prepend(sentinel);
        new IntersectionObserver(([e]) => topbar.classList.toggle("is-stuck", !e.isIntersecting)).observe(sentinel);
    }
}

// Season label comes from the API; the page works fine without it.
export async function loadSeasonLabel() {
    try {
        const res = await fetch("/api/system-status");
        const status = await res.json();
        document.querySelectorAll(".js-season").forEach((el) => setText(el, status.season_label));
    } catch (error) {
        console.error("System status check failed.", error);
        document.querySelectorAll(".js-season").forEach((el) => setText(el, "FPL"));
    }
}
