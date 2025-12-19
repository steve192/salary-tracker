document.addEventListener("DOMContentLoaded", () => {
    const employerInput = document.querySelector("input[name='employer_name']");
    const suggestionsBox = document.getElementById("employer-suggestions");
    const employerNamesScript = document.getElementById("employer-names-data");
    const employerNames = employerNamesScript ? JSON.parse(employerNamesScript.textContent) : [];

    if (employerInput && suggestionsBox) {
        const maxSuggestions = 5;
        const normalize = (value) => value.toLowerCase();

        const renderSuggestions = () => {
            const term = employerInput.value.trim();
            const matches = (term
                ? employerNames.filter((name) => normalize(name).includes(normalize(term)))
                : employerNames
            ).slice(0, maxSuggestions);

            suggestionsBox.innerHTML = "";

            const addItem = (label, value, isCreate = false) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = `quick-employer__item${isCreate ? " quick-employer__item--create" : ""}`;
                btn.dataset.value = value;
                btn.textContent = label;
                suggestionsBox.appendChild(btn);
            };

            matches.forEach((name) => addItem(name, name));

            const exactMatch = employerNames.some((name) => normalize(name) === normalize(term));
            if (term && !exactMatch) {
                addItem(`Create “${term}”`, term, true);
            }

            suggestionsBox.hidden = suggestionsBox.childElementCount === 0;
        };

        const closeSuggestions = () => {
            suggestionsBox.hidden = true;
        };

        employerInput.addEventListener("input", renderSuggestions);
        employerInput.addEventListener("focus", renderSuggestions);

        suggestionsBox.addEventListener("mousedown", (event) => {
            event.preventDefault();
        });

        suggestionsBox.addEventListener("click", (event) => {
            const target = event.target.closest(".quick-employer__item");
            if (!target) return;
            employerInput.value = target.dataset.value || "";
            closeSuggestions();
            employerInput.focus();
        });

        document.addEventListener("click", (event) => {
            if (event.target === employerInput || suggestionsBox.contains(event.target)) {
                return;
            }
            closeSuggestions();
        });
    }

    const tzDisplay = document.getElementById("tz-display");
    if (tzDisplay && Intl && Intl.DateTimeFormat) {
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        tzDisplay.textContent = tz;
    }

    const timelineScript = document.getElementById("timeline-data");
    const canvas = document.getElementById("salaryChart");
    if (!timelineScript || !canvas) {
        return;
    }

    const timeline = JSON.parse(timelineScript.textContent);
    if (!timeline.labels.length) {
        canvas.replaceWith(document.createTextNode("Add salary entries to see your compensation trend."));
        return;
    }

    const bonusHighlighter = {
        id: "bonusHighlighter",
        afterDatasetsDraw(chart, args, opts) {
            const { ctx, chartArea, scales } = chart;
            const windows = opts.windows || [];
            windows.forEach((window) => {
                const startLabel = window.startLabel;
                const endLabel = window.endLabel;
                const startIndex = chart.data.labels.indexOf(startLabel);
                const endIndex = chart.data.labels.indexOf(endLabel);
                if (startIndex === -1 || endIndex === -1) return;
                const xStart = scales.x.getPixelForValue(startIndex);
                const xEnd = scales.x.getPixelForValue(endIndex);
                ctx.save();
                ctx.fillStyle = "rgba(255, 193, 7, 0.1)";
                ctx.fillRect(xStart, chartArea.top, xEnd - xStart, chartArea.bottom - chartArea.top);
                ctx.restore();
            });
        },
    };

    const employerChangeMarker = {
        id: "employerChangeMarker",
        afterDatasetsDraw(chart, args, opts) {
            const switches = opts.switches || [];
            if (!switches.length) return;
            const { ctx, chartArea, scales } = chart;
            if (!chartArea) return;
            switches.forEach((marker) => {
                const index = chart.data.labels.indexOf(marker.label);
                if (index === -1) return;
                const x = scales.x.getPixelForValue(index);
                ctx.save();
                ctx.strokeStyle = "rgba(148, 163, 184, 0.6)";
                ctx.setLineDash([4, 4]);
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(x, chartArea.top);
                ctx.lineTo(x, chartArea.bottom);
                ctx.stroke();
                ctx.setLineDash([]);
                if (marker.employer) {
                    const text = marker.employer;
                    ctx.fillStyle = "#c9d1d9";
                    ctx.font = "12px 'Inter', 'Segoe UI', sans-serif";
                    ctx.textBaseline = "top";
                    const textWidth = ctx.measureText(text).width;
                    const margin = 6;
                    let textX = x + 4;
                    if (textX + textWidth > chartArea.right - margin) {
                        textX = chartArea.right - textWidth - margin;
                    }
                    if (textX < chartArea.left + margin) {
                        textX = chartArea.left + margin;
                    }
                    ctx.fillText(text, textX, chartArea.top + 4);
                }
                ctx.restore();
            });
        },
    };

    const fmt = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" });
    const windows = (timeline.bonusWindows || []).map((window) => ({
        ...window,
        startLabel: fmt.format(new Date(window.start)),
        endLabel: window.end ? fmt.format(new Date(window.end)) : timeline.labels[timeline.labels.length - 1],
    }));

    Chart.register(bonusHighlighter);
    Chart.register(employerChangeMarker);
    const zoomPlugin = window.ChartZoom || window["chartjs-plugin-zoom"];
    if (zoomPlugin) {
        Chart.register(zoomPlugin);
    }

    const datasets = [
        {
            label: "Base salary",
            data: timeline.baseSeries,
            borderColor: "#58a6ff",
            tension: 0.3,
            pointRadius: 2,
        },
        {
            label: "Total compensation (incl. bonuses)",
            data: timeline.totalSeries,
            borderColor: "#f78166",
            tension: 0.3,
            borderDash: [6, 6],
            pointRadius: 0,
        },
    ];

    const hasInflationSeries =
        timeline.inflationMeta?.ready &&
        Array.isArray(timeline.inflationSeries) &&
        timeline.inflationSeries.some((value) => typeof value === "number");
    if (hasInflationSeries) {
        const inflationLabel = (() => {
            const mode = timeline.inflationMeta?.mode;
            switch (mode) {
                case "PER_EMPLOYER":
                    return "Inflation-adjusted per-employer baseline";
                case "LAST_INCREASE":
                    return "Inflation-adjusted raise segments";
                case "MANUAL":
                    return "Inflation-adjusted custom baseline";
                default:
                    return "Inflation-adjusted initial salary";
            }
        })();
        datasets.push({
            label: inflationLabel,
            data: timeline.inflationSeries,
            borderColor: "#0ea5e9",
            borderWidth: 2,
            tension: 0.15,
            borderDash: [3, 3],
            pointRadius: 0,
            spanGaps: true,
        });
    }

    const numericValues = datasets
        .flatMap((dataset) => dataset.data)
        .filter((value) => typeof value === "number");
    const minValue = Math.min(...numericValues);
    const maxValue = Math.max(...numericValues);
    const range = maxValue - minValue || Math.abs(maxValue) || 1;
    const padding = range * 0.1;
    const suggestedMin = minValue - padding;
    const suggestedMax = maxValue + padding;

    const chartWrapper = canvas.closest(".chart-wrapper");
    const ctx = canvas.getContext("2d");
    if (chartWrapper) {
        chartWrapper.style.height = "100%";
    }
    const salaryChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: timeline.labels,
            datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { position: "bottom" },
                tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.formattedValue}` } },
                bonusHighlighter: { windows },
                employerChangeMarker: { switches: timeline.employerSwitches || [] },
                zoom: {
                    limits: { x: { min: timeline.labels[0], max: timeline.labels[timeline.labels.length - 1] } },
                    pan: { enabled: true, mode: "x" },
                    zoom: {
                        drag: {
                            enabled: true,
                            backgroundColor: "rgba(88, 166, 255, 0.12)",
                            borderColor: "#58a6ff",
                            borderWidth: 1,
                        },
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: "x",
                    },
                },
            },
            scales: {
                y: {
                    beginAtZero: false,
                    suggestedMin,
                    suggestedMax,
                    ticks: { padding: 8 },
                },
            },
        },
    });

    const resetZoomButton = document.getElementById("chartZoomReset");
    if (resetZoomButton && salaryChart.resetZoom) {
        resetZoomButton.addEventListener("click", () => {
            salaryChart.resetZoom();
        });
    }

    const fullscreenButton = document.getElementById("chartFullscreenToggle");
    const updateFullscreenLabel = () => {
        if (!fullscreenButton || !chartWrapper) return;
        const active = document.fullscreenElement === chartWrapper;
        fullscreenButton.textContent = active ? "Exit fullscreen" : "Fullscreen";
    };

    if (fullscreenButton && chartWrapper && chartWrapper.requestFullscreen) {
        fullscreenButton.addEventListener("click", () => {
            const active = document.fullscreenElement === chartWrapper;
            if (active) {
                if (document.exitFullscreen) {
                    document.exitFullscreen();
                }
                return;
            }
            chartWrapper.requestFullscreen().catch(() => {
                /* ignored */
            });
        });

        document.addEventListener("fullscreenchange", () => {
            updateFullscreenLabel();
            salaryChart.resize();
        });

        updateFullscreenLabel();
    }

    document.querySelectorAll(".toggle-breakdown").forEach((button) => {
        const targetId = button.getAttribute("data-target");
        if (!targetId) return;
        const targetRow = document.getElementById(targetId);
        if (!targetRow) return;
        const updateLabel = () => {
            const hidden = targetRow.hasAttribute("hidden");
            button.textContent = hidden ? "Show months" : "Hide months";
        };
        button.addEventListener("click", () => {
            if (targetRow.hasAttribute("hidden")) {
                targetRow.removeAttribute("hidden");
            } else {
                targetRow.setAttribute("hidden", "");
            }
            updateLabel();
        });
        updateLabel();
    });
});
