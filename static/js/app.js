/**
 * Shared utilities for MobilityTwin frontend.
 */

const MT = {
    /** Default map center (Belgium) */
    MAP_CENTER: [50.5, 4.35],
    MAP_ZOOM: 8,

    /** Color interpolation: green → yellow → red */
    valueToColor(ratio) {
        ratio = Math.max(0, Math.min(1, ratio));
        let r, g, b;
        if (ratio < 0.5) {
            const t = ratio * 2;
            r = Math.round(34 + 221 * t);
            g = Math.round(180 - 40 * t);
            b = Math.round(34 - 30 * t);
        } else {
            const t = (ratio - 0.5) * 2;
            r = Math.round(255 - 35 * t);
            g = Math.round(140 - 120 * t);
            b = Math.round(4 + 30 * t);
        }
        return `rgb(${r},${g},${b})`;
    },

    /** Create a Leaflet map with CartoDB Positron tiles */
    createMap(elementId, options = {}) {
        const map = L.map(elementId, {
            zoomControl: true,
            ...options,
        }).setView(
            options.center || this.MAP_CENTER,
            options.zoom || this.MAP_ZOOM
        );

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(map);

        return map;
    },

    /** Fetch JSON from API with query params */
    async fetchApi(endpoint, params = {}) {
        const url = new URL(`/api${endpoint}`, window.location.origin);
        for (const [key, value] of Object.entries(params)) {
            if (value !== null && value !== undefined && value !== '') {
                url.searchParams.set(key, value);
            }
        }
        const res = await fetch(url);
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        return res.json();
    },

    /** Build standard filter params from Alpine state */
    filterParams(filters) {
        const params = {
            start: filters.startDate,
            end: filters.endDate,
            weekdays: filters.weekdays.join(','),
            exclude_pub: filters.excludePub || false,
            exclude_sch: filters.excludeSch || false,
        };
        if (filters.useHour) {
            params.hour_start = filters.hourStart;
            params.hour_end = filters.hourEnd;
        }
        return params;
    },

    /** Format number with locale separators */
    fmt(n, decimals = 0) {
        if (n === null || n === undefined) return '—';
        return Number(n).toLocaleString('en', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    },

    /** Default filters state */
    defaultFilters() {
        const today = new Date();
        const weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 7);

        return {
            startDate: weekAgo.toISOString().slice(0, 10),
            endDate: today.toISOString().slice(0, 10),
            weekdays: [0, 1, 2, 3, 4],
            excludePub: false,
            excludeSch: false,
            useHour: false,
            hourStart: 7,
            hourEnd: 19,
        };
    },
};
