/**
 * @file pic_handoff_details.js
 * @description Shared renderer for PIC Handoff Checklist submission details (modal view).
 * Used by view_forms.js, dashboard.js, view_pic_handoffs.js, and my_pic_handoffs.js.
 */

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

const CATEGORY_ORDER = [
    'identity',
    'power',
    'tracker',
    'navigation',
    'system',
    'safety',
    'sensors',
    'comments',
];

const CATEGORY_LABELS = {
    identity: 'Identity & personnel',
    power: 'Power',
    tracker: 'Tracker & comms',
    navigation: 'Navigation',
    system: 'System status',
    safety: 'Safety (AIS / standoff / errors)',
    sensors: 'Sensors',
    comments: 'User comments',
};

function getCategory(itemId) {
    if (!itemId) return 'identity';
    const id = String(itemId);
    if (['glider_id_val', 'mission_title_val', 'current_mos_val', 'current_pic_val', 'last_pic_val', 'mission_status_val'].includes(id))
        return id === 'mission_status_val' ? 'identity' : 'identity';
    if (['total_battery_val', 'current_battery_wh_val', 'percent_battery_val'].includes(id)) return 'power';
    if (['tracker_battery_v_val', 'tracker_last_update_val', 'communications_val', 'telemetry_rate_val'].includes(id)) return 'tracker';
    if (['navigation_mode_val', 'target_waypoint_val', 'waypoint_details_val'].includes(id)) return 'navigation';
    if (['light_status_val', 'thruster_status_val', 'obstacle_avoid_val', 'line_follow_val'].includes(id)) return 'system';
    if (['boats_in_area_val', 'vessel_standoff_m_val', 'recent_errors_val'].includes(id)) return 'safety';
    if (/^sensor_.*_status$/.test(id) || /^sensor_.*_sampling_val$/.test(id) || /^wg_vm4_/.test(id)) return 'sensors';
    if (id === 'user_comments_val') return 'comments';
    return 'identity';
}

/** Sensor sampling item IDs that may appear after each sensor status row (WG-VM4 has no sampling). */
const SENSOR_SAMPLING_LABELS = {
    sensor_ctd_sampling_val: 'CTD Sample Rate',
    sensor_fluorometer_sampling_val: 'Fluorometer Sample Rate',
    sensor_waves_sampling_val: 'Waves Interval',
    sensor_weather_sampling_val: 'Weather Interval',
    sensor_vr2c_sampling_val: 'VR2C Status Interval',
};

const AT_A_GLANCE_IDS = [
    'glider_id_val',
    'mission_title_val',
    'mission_status_val',
    'current_battery_wh_val',
    'percent_battery_val',
    'recent_errors_val',
    'boats_in_area_val',
];

const LOW_BATTERY_PERCENT_THRESHOLD = 30;

function isNoIssuesValue(itemId, value) {
    if (!value) return false;
    const s = String(value).trim().toLowerCase();
    if (['recent_errors_val', 'boats_in_area_val'].includes(String(itemId)))
        return s === 'no recent errors.' || s === 'no recent ais contacts.';
    return false;
}

function formatItemValue(item) {
    const id = item.id ? String(item.id) : '';
    const raw = item.value;

    if (id.startsWith('sensor_') && id.endsWith('_status')) {
        const rawStr = raw != null ? String(raw).trim() : '';
        if (rawStr === 'On' || rawStr === 'Off') {
            return rawStr;
        }
        try {
            const v = typeof raw === 'string' ? JSON.parse(raw) : raw;
            const onOff = (v && (v.value === 'On' || v.default_on)) ? 'On' : 'Off';
            const lastStr = (v && v.last_time_str) ? v.last_time_str : '';
            return lastStr ? `${onOff} • Last data: ${lastStr}` : onOff;
        } catch (_) {
            return item.is_checked ? 'On' : 'Off';
        }
    }

    if (/^sensor_.*_sampling_val$/.test(id)) {
        return (raw !== undefined && raw !== null && String(raw).trim() !== '') ? String(raw) : null;
    }

    if (item.item_type === 'checkbox') {
        return item.is_checked ? 'Checked' : 'Unchecked';
    }
    if (id === 'user_comments_val') {
        return (raw && String(raw).trim()) ? String(raw) : 'No included comments';
    }
    if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
        return raw != null && String(raw).trim() !== '' ? String(raw) : 'N/A';
    }
    return raw != null && String(raw).trim() !== '' ? String(raw) : null;
}

function getItemById(sectionsData, itemId) {
    if (!sectionsData || !Array.isArray(sectionsData)) return null;
    for (const section of sectionsData) {
        const items = section.items || [];
        const found = items.find((i) => (i.id || '') === itemId);
        if (found) return found;
    }
    return null;
}

/**
 * Ensures the sensors list includes a sampling row after each sensor status row that has a known sampling field.
 * Inserts placeholder items (label + "Not provided") when submission data omits them (e.g. older submissions).
 */
function ensureSensorSamplingRows(items) {
    if (!items || items.length === 0) return items;
    const out = [];
    for (let i = 0; i < items.length; i++) {
        out.push(items[i]);
        const id = items[i].id ? String(items[i].id) : '';
        const statusMatch = id.match(/^sensor_(.+)_status$/);
        if (statusMatch) {
            const card = statusMatch[1];
            const samplingId = `sensor_${card}_sampling_val`;
            if (!SENSOR_SAMPLING_LABELS[samplingId]) continue;
            const next = items[i + 1];
            if (!next || next.id !== samplingId) {
                out.push({
                    id: samplingId,
                    label: SENSOR_SAMPLING_LABELS[samplingId],
                    value: null,
                    is_verified: undefined,
                    comment: undefined,
                });
            }
        }
    }
    return out;
}

/**
 * Renders PIC Handoff submission details as HTML string.
 * @param {Object} form - Submitted form object (sections_data, submission_timestamp, submitted_by_username, etc.)
 * @param {string[]} changedItemIds - Item IDs that have changed since last PIC (for badge)
 * @returns {string} HTML string for modal body
 */
export function renderPicHandoffDetails(form, changedItemIds = []) {
    const changedSet = new Set(Array.isArray(changedItemIds) ? changedItemIds : []);

    const submissionTimestampStr = String(form.submission_timestamp || '').endsWith('Z')
        ? String(form.submission_timestamp || '')
        : `${form.submission_timestamp}Z`;
    const submissionDate = new Date(submissionTimestampStr);
    const formattedTime = Number.isNaN(submissionDate.getTime())
        ? 'N/A'
        : submissionDate.toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium', hour12: false }) + ' UTC';

    let html = `<p class="mb-2"><strong>Submitted by:</strong> ${escapeHtml(form.submitted_by_username || 'Unknown')} at ${escapeHtml(formattedTime)}</p>`;
    html += '<div class="pic-handoff-color-guide mb-3"><span class="pic-handoff-color-guide-label">Color guide:</span> ';
    html += '<span class="pic-unverified-value me-2">Unverified</span> = autogenerated but not verified by submitter. ';
    html += '<span class="pic-handoff-color-guide-changed">Changed</span> = value changed since last PIC submission.</div>';
    html += '<hr class="my-3">';

    const sectionsData = form.sections_data;
    if (!sectionsData || !Array.isArray(sectionsData)) {
        html += '<p>No detailed section data available for this form.</p>';
        return html;
    }

    const allItems = [];
    sectionsData.forEach((section) => {
        (section.items || []).forEach((item) => allItems.push({ ...item, sectionTitle: section.title }));
    });

    const atGlanceItems = AT_A_GLANCE_IDS.map((id) => getItemById(sectionsData, id)).filter(Boolean);
    if (atGlanceItems.length > 0) {
        html += '<div class="pic-handoff-at-glance mb-4">';
        html += '<h5 class="pic-handoff-category mb-2">Handoff at a glance</h5>';
        html += '<ul class="list-group list-group-flush mb-0">';
        atGlanceItems.forEach((item) => {
            let val = formatItemValue(item);
            if (val !== null && (item.id === 'recent_errors_val' || item.id === 'boats_in_area_val')) {
                const firstLine = String(val).split('\n')[0];
                val = firstLine.length > 80 ? firstLine.slice(0, 77) + '...' : firstLine;
            }
            const displayVal = val === null ? 'N/A' : val;
            const isChanged = item.id && changedSet.has(item.id);
            const isUnverified = item.is_verified === false && !isNoIssuesValue(item.id, displayVal);
            const isLowBattery = item.id === 'percent_battery_val' &&
                typeof val === 'string' && !Number.isNaN(parseFloat(val)) && parseFloat(val) < LOW_BATTERY_PERCENT_THRESHOLD;
            let valueHtml = escapeHtml(displayVal);
            if (isUnverified) valueHtml = `<span class="pic-unverified-value">${valueHtml}</span>`;
            else if (isNoIssuesValue(item.id, displayVal)) valueHtml = `<span class="pic-handoff-value-success">${valueHtml}</span>`;
            else if (isLowBattery && item.id === 'percent_battery_val') valueHtml = `<span class="text-warning">${valueHtml}</span>`;
            const liClass = isChanged ? 'list-group-item pic-handoff-item-changed' : 'list-group-item';
            html += `<li class="${liClass}" data-item-id="${escapeHtml(item.id || '')}"><strong>${escapeHtml(item.label || '')}:</strong> ${valueHtml}`;
            if (isChanged) html += ' <span class="badge bg-warning text-dark">Changes since last PIC</span>';
            html += '</li>';
        });
        html += '</ul></div><hr class="my-3">';
    }

    const byCategory = {};
    CATEGORY_ORDER.forEach((cat) => { byCategory[cat] = []; });
    allItems.forEach((item) => {
        const cat = getCategory(item.id);
        if (byCategory[cat]) byCategory[cat].push(item);
        else byCategory.identity.push(item);
    });

    CATEGORY_ORDER.forEach((cat) => {
        let items = byCategory[cat];
        if (!items || items.length === 0) return;
        if (cat === 'sensors') {
            items = ensureSensorSamplingRows(items);
        }
        const label = CATEGORY_LABELS[cat];
        html += `<h6 class="pic-handoff-category mt-3 mb-2">${escapeHtml(label)}</h6>`;
        html += '<ul class="list-group list-group-flush mb-3">';
        items.forEach((item) => {
            const val = formatItemValue(item);
            const isChanged = item.id && changedSet.has(item.id);
            const isUnverified = item.is_verified === false && !isNoIssuesValue(item.id, val);
            const isLowBattery = item.id === 'percent_battery_val' &&
                val != null && !Number.isNaN(parseFloat(val)) && parseFloat(val) < LOW_BATTERY_PERCENT_THRESHOLD;

            let valueHtml;
            if (val === null) {
                valueHtml = '<em class="text-muted">Not provided</em>';
            } else {
                valueHtml = escapeHtml(String(val));
                if (isUnverified) valueHtml = `<span class="pic-unverified-value">${valueHtml}</span>`;
                else if (isNoIssuesValue(item.id, val)) valueHtml = `<span class="pic-handoff-value-success">${valueHtml}</span>`;
                else if (isLowBattery && item.id === 'percent_battery_val') valueHtml = `<span class="text-warning">${valueHtml}</span>`;
            }

            const liClass = isChanged ? 'list-group-item pic-handoff-item-changed' : 'list-group-item';
            html += `<li class="${liClass}" data-item-id="${escapeHtml(item.id || '')}"><strong>${escapeHtml(item.label || '')}:</strong> ${valueHtml}`;
            if (isChanged) html += ' <span class="badge bg-warning text-dark">Changes since last PIC</span>';
            if (item.is_verified) html += ' <span class="badge bg-success">Verified</span>';
            if (item.comment) html += `<br><small class="text-muted"><em>Comment: ${escapeHtml(item.comment)}</em></small>`;
            html += '</li>';
        });
        html += '</ul>';
    });

    return html;
}
