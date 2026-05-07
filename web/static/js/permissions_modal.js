/**
 * Permissions reference modal: current-user badges and optional row dimming.
 */
import { getUserProfile } from '/static/js/auth.js';

/** @typedef {{ role?: string, username?: string, is_pic?: boolean, is_mos?: boolean, disabled?: boolean }} UserProfile */

/** @type {UserProfile | null} */
let cachedUserForPermissionsModal = null;

/**
 * @param {string} showFor
 * @param {UserProfile | null} user
 * @returns {boolean}
 */
function user_matches_show_for(show_for, user) {
    if (!user) return false;
    if (show_for === 'any') return true;

    const role = user.role || '';
    const is_admin = role === 'admin';
    const is_pilot_role = role === 'pilot';
    const can_act_as_pilot = is_admin || is_pilot_role;

    if (show_for === 'admin') return is_admin;
    if (show_for === 'pilot') return can_act_as_pilot;
    if (show_for === 'pic') return is_admin || (is_pilot_role && Boolean(user.is_pic));
    if (show_for === 'mos') return is_admin || (is_pilot_role && Boolean(user.is_mos));

    return true;
}

/**
 * @param {UserProfile | null} user
 * @param {boolean} dim_inaccessible
 */
function apply_permissions_row_dimming(user, dim_inaccessible) {
    const modal = document.getElementById('permissionsReferenceModal');
    if (!modal) return;

    modal.querySelectorAll('tr[data-show-for]').forEach((tr) => {
        const key = tr.getAttribute('data-show-for') || 'any';
        const is_owner_scoped_rule = Boolean(
            tr.querySelector('.badge.text-bg-warning.text-dark')
        );
        const match = user_matches_show_for(key, user);
        // Owner-scoped rules depend on record ownership context we do not have here.
        const dim = Boolean(dim_inaccessible && !match && !is_owner_scoped_rule);
        tr.classList.toggle('opacity-25', dim);
        tr.classList.toggle('text-muted', dim);
    });
}

/**
 * @param {UserProfile | null} user
 */
function render_permissions_user_badges(user) {
    const name_el = document.getElementById('permissionsCurrentUserName');
    const badges_el = document.getElementById('permissionsCurrentUserBadges');
    if (!name_el || !badges_el) return;

    if (!user) {
        name_el.textContent = '—';
        badges_el.innerHTML =
            '<span class="badge text-bg-secondary">Not signed in</span>' +
            '<span class="text-muted small ms-1">Sign in to see your role and designations.</span>';
        return;
    }

    name_el.textContent = user.username || '—';
    const parts = [];

    const role = user.role || 'unknown';
    const role_class = role === 'admin' ? 'text-bg-danger' : 'text-bg-primary';
    parts.push(`<span class="badge ${role_class}">${escape_html(role)}</span>`);

    if (user.is_pic) parts.push('<span class="badge text-bg-info">PIC</span>');
    if (user.is_mos) parts.push('<span class="badge text-bg-secondary">MOS</span>');
    if (user.disabled) parts.push('<span class="badge text-bg-warning text-dark">Disabled</span>');

    badges_el.innerHTML = parts.join(' ');
}

/**
 * @param {string} raw
 * @returns {string}
 */
function escape_html(raw) {
    const div = document.createElement('div');
    div.textContent = raw;
    return div.innerHTML;
}

async function refresh_permissions_modal_user_state() {
    const user = await getUserProfile();
    cachedUserForPermissionsModal = user;
    render_permissions_user_badges(user);

    const highlight_switch = document.getElementById('permissionsHighlightSwitch');
    const dim_on = Boolean(highlight_switch && highlight_switch.checked);
    apply_permissions_row_dimming(user, dim_on);
}

document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('permissionsReferenceModal');
    const highlight_switch = document.getElementById('permissionsHighlightSwitch');

    if (modal) {
        modal.addEventListener('show.bs.modal', () => {
            void refresh_permissions_modal_user_state();
        });
    }

    if (highlight_switch) {
        highlight_switch.addEventListener('change', () => {
            apply_permissions_row_dimming(cachedUserForPermissionsModal, highlight_switch.checked);
        });
    }
});
