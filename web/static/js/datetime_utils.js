/**
 * @file datetime_utils.js
 * @description Shared UTC datetime parsing/formatting helpers.
 */

const UTC_DATE_TIME_FORMATTER = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
});

const UTC_DATE_FORMATTER = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
});

function toUtcDate(value) {
    if (!value) return null;
    const date = parseUtcTimestamp(value);
    if (Number.isNaN(date.getTime())) return null;
    return date;
}

export function parseUtcTimestamp(value) {
    if (!value) return null;
    if (value instanceof Date) return new Date(value.getTime());
    if (typeof value === 'number') return new Date(value);
    if (typeof value !== 'string') return new Date(value);

    const trimmedValue = value.trim();
    if (!trimmedValue) return null;

    const isTimezoneMissing = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(trimmedValue);
    const normalizedValue = isTimezoneMissing ? `${trimmedValue}Z` : trimmedValue;
    return new Date(normalizedValue);
}

export function formatUtcDateTime(value) {
    const date = toUtcDate(value);
    if (!date) return '-';
    const parts = UTC_DATE_TIME_FORMATTER.formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second} UTC`;
}

export function formatUtcDate(value) {
    const date = toUtcDate(value);
    if (!date) return '-';
    const parts = UTC_DATE_FORMATTER.formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
}

export function parseDatetimeLocalAsUtc(value) {
    if (!value) return null;
    const trimmedValue = value.trim();
    if (!trimmedValue) return null;
    const utcDate = new Date(`${trimmedValue}Z`);
    if (Number.isNaN(utcDate.getTime())) return null;
    return utcDate;
}

export function datetimeLocalToUtcIso(value) {
    const utcDate = parseDatetimeLocalAsUtc(value);
    if (!utcDate) return null;
    return utcDate.toISOString();
}

export function findNearestTimeIndexUtc(timeValues, nowDate = new Date()) {
    if (!Array.isArray(timeValues) || timeValues.length === 0) return -1;
    const nowUtcDate = toUtcDate(nowDate);
    if (!nowUtcDate) return -1;

    let nearestIndex = -1;
    let smallestDiffMs = Number.POSITIVE_INFINITY;
    for (let i = 0; i < timeValues.length; i++) {
        const candidateDate = toUtcDate(timeValues[i]);
        if (!candidateDate) continue;
        const diffMs = Math.abs(candidateDate.getTime() - nowUtcDate.getTime());
        if (diffMs < smallestDiffMs) {
            smallestDiffMs = diffMs;
            nearestIndex = i;
        }
    }
    return nearestIndex;
}
