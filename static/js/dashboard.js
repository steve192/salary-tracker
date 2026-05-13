import { Chart, registerables } from "chart.js";
import zoomPlugin from "chartjs-plugin-zoom";

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

    Chart.register(...registerables, bonusHighlighter, employerChangeMarker, zoomPlugin);

    const hasInflationSeries =
        timeline.inflationMeta?.ready &&
        Array.isArray(timeline.inflationSeries) &&
        timeline.inflationSeries.some((value) => typeof value === "number");
    const hasPurchasingPowerSeries =
        hasInflationSeries &&
        Array.isArray(timeline.purchasingPowerBaseSeries) &&
        Array.isArray(timeline.purchasingPowerTotalSeries) &&
        timeline.purchasingPowerBaseSeries.some((value) => typeof value === "number");

    const inflationLabel = (() => {
        const mode = timeline.inflationMeta?.mode;
        switch (mode) {
            case "PER_EMPLOYER":
                return "Salary needed since joining employer";
            case "LAST_INCREASE":
                return "Salary needed after each raise";
            case "MANUAL":
                return "Salary needed from your chosen start";
            default:
                return "Salary needed to keep up";
        }
    })();

    const nominalDatasets = [
        {
            label: "Monthly salary",
            data: timeline.baseSeries,
            borderColor: "#58a6ff",
            tension: 0.3,
            pointRadius: 2,
        },
        {
            label: "Salary plus bonuses",
            data: timeline.totalSeries,
            borderColor: "#f78166",
            tension: 0.3,
            borderDash: [6, 6],
            pointRadius: 0,
        },
    ];

    if (hasInflationSeries) {
        nominalDatasets.push({
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

    const purchasingPowerDatasets = hasPurchasingPowerSeries
        ? [
              {
                  label: "Monthly salary value",
                  data: timeline.purchasingPowerBaseSeries,
                  borderColor: "#58a6ff",
                  tension: 0.3,
                  pointRadius: 2,
                  spanGaps: true,
              },
              {
                  label: "Salary plus bonuses value",
                  data: timeline.purchasingPowerTotalSeries,
                  borderColor: "#f78166",
                  tension: 0.3,
                  borderDash: [6, 6],
                  pointRadius: 0,
                  spanGaps: true,
              },
              {
                  label: "Starting salary value",
                  data: timeline.purchasingPowerReferenceSeries,
                  borderColor: "#0ea5e9",
                  borderWidth: 2,
                  tension: 0,
                  borderDash: [3, 3],
                  pointRadius: 0,
                  spanGaps: true,
              },
          ]
        : nominalDatasets;

    const chartModes = {
        nominal: nominalDatasets,
        "purchasing-power": purchasingPowerDatasets,
    };
    let activeChartMode = "nominal";

    const calculatePaddedRange = (values) => {
        const minValue = Math.min(...values);
        const maxValue = Math.max(...values);
        const range = maxValue - minValue || Math.abs(maxValue) || 1;
        const padding = range * 0.1;
        return {
            min: minValue - padding,
            max: maxValue + padding,
        };
    };

    const numericDatasetValues = (chartDatasets) =>
        chartDatasets
        .flatMap((dataset) => dataset.data)
        .filter((value) => typeof value === "number" && Number.isFinite(value));

    const paddedRangeForDatasets = (chartDatasets) => calculatePaddedRange(numericDatasetValues(chartDatasets));
    const initialYRange = paddedRangeForDatasets(chartModes[activeChartMode]);
    const suggestedMin = initialYRange.min;
    const suggestedMax = initialYRange.max;

    const clampIndex = (value) => Math.max(0, Math.min(timeline.labels.length - 1, value));
    const scaleValueToIndex = (value) => {
        if (typeof value === "number" && Number.isFinite(value)) {
            return value;
        }
        const index = timeline.labels.indexOf(value);
        return index === -1 ? 0 : index;
    };

    const getVisibleIndexRange = (chart) => {
        const xScale = chart.scales.x;
        const minIndex = clampIndex(Math.floor(scaleValueToIndex(xScale.min)));
        const maxIndex = clampIndex(Math.ceil(scaleValueToIndex(xScale.max)));
        return {
            min: Math.min(minIndex, maxIndex),
            max: Math.max(minIndex, maxIndex),
        };
    };

    const visibleYValues = (chart) => {
        const visibleRange = getVisibleIndexRange(chart);
        return chart.data.datasets.flatMap((dataset, datasetIndex) => {
            if (!chart.isDatasetVisible(datasetIndex)) {
                return [];
            }
            return dataset.data
                .slice(visibleRange.min, visibleRange.max + 1)
                .filter((value) => typeof value === "number" && Number.isFinite(value));
        });
    };

    const setYAxisRange = (chart, range) => {
        const yScaleOptions = chart.options.scales.y;
        yScaleOptions.min = range.min;
        yScaleOptions.max = range.max;
        chart.update("none");
    };

    const restoreFullYAxisRange = (chart) => {
        const yScaleOptions = chart.options.scales.y;
        const fullYRange = paddedRangeForDatasets(chart.data.datasets);
        delete yScaleOptions.min;
        delete yScaleOptions.max;
        yScaleOptions.suggestedMin = fullYRange.min;
        yScaleOptions.suggestedMax = fullYRange.max;
        chart.update("none");
    };

    const fitYAxisToVisibleData = (chart) => {
        const values = visibleYValues(chart);
        if (!values.length) {
            restoreFullYAxisRange(chart);
            return;
        }
        setYAxisRange(chart, calculatePaddedRange(values));
    };

    const scheduleVisibleYAxisFit = (chart) => {
        window.requestAnimationFrame(() => fitYAxisToVisibleData(chart));
    };

    const chartWrapper = canvas.closest(".chart-wrapper");
    const ctx = canvas.getContext("2d");
    const supportsDragZoom = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    const salaryChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: timeline.labels,
            datasets: chartModes[activeChartMode],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    position: "bottom",
                    onClick(event, legendItem, legend) {
                        Chart.defaults.plugins.legend.onClick.call(this, event, legendItem, legend);
                        scheduleVisibleYAxisFit(legend.chart);
                    },
                },
                tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.formattedValue}` } },
                bonusHighlighter: { windows },
                employerChangeMarker: { switches: timeline.employerSwitches || [] },
                zoom: {
                    limits: { x: { min: timeline.labels[0], max: timeline.labels[timeline.labels.length - 1] } },
                    pan: {
                        enabled: !supportsDragZoom,
                        mode: "x",
                        onPan: ({ chart }) => scheduleVisibleYAxisFit(chart),
                        onPanComplete: ({ chart }) => scheduleVisibleYAxisFit(chart),
                    },
                    zoom: {
                        drag: {
                            enabled: supportsDragZoom,
                            backgroundColor: "rgba(88, 166, 255, 0.12)",
                            borderColor: "#58a6ff",
                            borderWidth: 1,
                        },
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        mode: "x",
                        onZoom: ({ chart }) => scheduleVisibleYAxisFit(chart),
                        onZoomComplete: ({ chart }) => scheduleVisibleYAxisFit(chart),
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

    document.querySelectorAll("[data-chart-mode]").forEach((button) => {
        const mode = button.dataset.chartMode;
        if (!chartModes[mode] || (mode === "purchasing-power" && !hasPurchasingPowerSeries)) {
            button.hidden = true;
            return;
        }
        button.addEventListener("click", () => {
            activeChartMode = mode;
            salaryChart.data.datasets = chartModes[activeChartMode];
            document.querySelectorAll("[data-chart-mode]").forEach((modeButton) => {
                const active = modeButton.dataset.chartMode === activeChartMode;
                modeButton.classList.toggle("active", active);
                modeButton.setAttribute("aria-pressed", active ? "true" : "false");
            });
            document.querySelectorAll("[data-chart-explanation]").forEach((explanation) => {
                explanation.hidden = explanation.dataset.chartExplanation !== activeChartMode;
            });
            scheduleVisibleYAxisFit(salaryChart);
        });
    });

    const chartCenterPoint = (chart) => {
        const area = chart.chartArea;
        return {
            x: (area.left + area.right) / 2,
            y: (area.top + area.bottom) / 2,
        };
    };

    const zoomChartHorizontally = (chart, factor) => {
        if (!chart.zoom) return;
        chart.zoom(
            {
                x: factor,
                y: 1,
                focalPoint: chartCenterPoint(chart),
            },
            "zoom",
        );
        scheduleVisibleYAxisFit(chart);
    };

    const zoomInButton = document.getElementById("chartZoomIn");
    if (zoomInButton && salaryChart.zoom) {
        zoomInButton.addEventListener("click", () => {
            zoomChartHorizontally(salaryChart, 1.3);
        });
    }

    const zoomOutButton = document.getElementById("chartZoomOut");
    if (zoomOutButton && salaryChart.zoom) {
        zoomOutButton.addEventListener("click", () => {
            zoomChartHorizontally(salaryChart, 0.77);
        });
    }

    const resetZoomButton = document.getElementById("chartZoomReset");
    if (resetZoomButton && salaryChart.resetZoom) {
        resetZoomButton.addEventListener("click", () => {
            salaryChart.resetZoom();
            restoreFullYAxisRange(salaryChart);
        });
    }

    const fullscreenButton = document.getElementById("chartFullscreenToggle");
    const updateFullscreenLabel = () => {
        if (!fullscreenButton || !chartWrapper) return;
        const active = document.fullscreenElement === chartWrapper;
        fullscreenButton.textContent = active ? "⛶" : "⛶";
        fullscreenButton.title = active ? "Exit fullscreen" : "Enter fullscreen";
        fullscreenButton.setAttribute("aria-label", active ? "Exit fullscreen" : "Enter fullscreen");
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
