import { blockers } from './orders-api.js';
const $ = id => document.getElementById(id);
export const draftRoute = (workspace, draft = '') => `#/workspaces/${workspace}/draft-orders/${draft ? `${draft}/` : ''}`;
function text(tag, value, className = '') {
  const element = document.createElement(tag); element.textContent = value; element.className = className; return element;
}
function fields(id, entries) {
  $(id).replaceChildren(...entries.flatMap(([label, value]) => [text('dt', label), text('dd', value === '' || value === null ? 'Not provided' : String(value))]));
}
export function renderDrafts(state, visible, canConvert, editLine = null) {
  $('drafts-screen').hidden = !visible;
  $('draft-list-panel').hidden = Boolean(state.draftId);
  $('draft-detail-panel').hidden = !state.draftId;
  $('draft-back').hidden = !state.draftId;
  $('draft-back').href = state.workspace ? draftRoute(state.workspace.id) : '#';
  $('draft-refresh').disabled = state.loading || state.converting || state.linesLoading;
  $('draft-message').textContent = state.message || state.errors.revision || '';
  $('draft-conflict').replaceChildren(...state.conflict.map(reason => text('li', `Conversion rejection: ${blockers[reason.code][0]} (${reason.count})`)));
  $('draft-count').textContent = state.loading ? 'Loading drafts…' : `${state.count} draft orders`;
  $('draft-rows').replaceChildren(...state.rows.map(draft => {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    const link = text('a', draft.customer_name || 'Unnamed customer');
    link.href = draftRoute(state.workspace.id, draft.id);
    cell.append(link, text('div', draft.customer_reference || 'No customer reference', 'muted small'), text('div', draft.id, 'muted small identity'));
    row.append(cell, text('td', draft.status === 'converted' ? 'Converted' : 'Draft'), text('td', String(draft.line_count)), text('td', new Date(draft.updated_at).toLocaleString()));
    return row;
  }));
  $('draft-list-state').hidden = Boolean(state.rows.length);
  $('draft-list-state').textContent = state.errors.list || (state.loading ? 'Loading workspace drafts…' : 'This workspace has no drafts yet.');
  $('draft-page-label').textContent = `Page ${state.page} of ${Math.max(1, Math.ceil(state.count / 50))}`;
  $('draft-previous').disabled = state.loading || Boolean(state.errors.list) || state.page <= 1;
  $('draft-next').disabled = state.loading || Boolean(state.errors.list) || state.page * 50 >= state.count;
  $('draft-content').hidden = !state.draft;
  $('draft-detail-state').hidden = Boolean(state.draft);
  $('draft-detail-state').textContent = state.errors.detail || (state.loading ? 'Loading draft details…' : 'Draft unavailable. Refresh to try again.');
  if (!state.draft) {
    // Remove private text as well as hiding panels, including on logout.
    for (const id of ['draft-fields', 'draft-intake', 'draft-review', 'draft-lines', 'draft-blockers', 'conversion-number', 'conversion-id']) $(id).replaceChildren();
    $('convert-draft').hidden = true; $('conversion-result').hidden = true;
    if ($('conversion-confirm').open) $('conversion-confirm').close();
    return;
  }
  const draft = state.draft;
  $('draft-status').textContent = draft.status === 'converted' ? 'Converted · source locked' : 'Draft';
  fields('draft-fields', [['Customer', draft.customer_name], ['Customer reference', draft.customer_reference], ['Draft ID', draft.id], ['Source', 'Manual intake'], ['Initiating user ID', draft.initiating_user_id], ['Created', new Date(draft.created_at).toLocaleString()], ['Last header update', new Date(draft.updated_at).toLocaleString()]]);
  $('draft-intake').textContent = draft.original_intake_text || 'No intake text provided.';
  $('draft-review-state').textContent = state.errors.review || (state.review ? '' : 'Loading review observations…');
  fields('draft-review', state.review ? [['All lines', state.review.line_count], ['Unresolved lines', state.review.unresolved_line_count], ['Unmatched lines', state.review.unmatched_line_count], ['Missing quantities', state.review.missing_quantity_line_count], ['Inactive catalogue items', state.review.inactive_catalogue_line_count], ['Customer reference', state.review.customer_reference_empty ? 'Optional; not provided' : 'Provided']] : []);
  $('draft-readiness-state').textContent = state.errors.readiness || (state.readiness ? state.readiness.ready_to_convert ? 'Ready for internal conversion' : 'Internal conversion is blocked' : 'Checking readiness…');
  $('draft-blockers').replaceChildren(...(state.readiness?.blocking_reasons ?? []).map(reason => {
    const item = document.createElement('li'); const [message, target] = blockers[reason.code];
    const link = text('button', `${message} (${reason.count})`, 'blocker-link');
    link.addEventListener('click', () => { $(target).scrollIntoView({ block: 'center' }); $(target).focus(); });
    item.append(link); return item;
  }));
  $('draft-assessed').textContent = state.assessedAt ? `Assessed ${new Date(state.assessedAt).toLocaleTimeString()}. Refresh to update.` : '';
  $('draft-lines').replaceChildren(...state.lines.map(line => {
    const row = document.createElement('tr'); const request = document.createElement('td');
    request.append(text('div', line.requested_sku || 'No requested SKU', 'sku'), text('div', line.requested_description || 'No description', 'muted small'));
    const quantity = document.createElement('td'); quantity.append(text('div', line.quantity ?? 'Missing quantity', 'exact-quantity'), text('div', line.unit || 'Unit not provided', 'muted small'));
    const match = document.createElement('td');
    match.append(text('div', line.catalogue_item_id ? line.catalogue_sku_snapshot : 'Unmatched · manual request', 'sku'), text('div', line.catalogue_description_snapshot, 'muted small'));
    if (line.catalogue_item_id) match.append(text('div', line.catalogue_item_id, 'muted small identity'));
    if (editLine && ['admin', 'reviewer'].includes(state.workspace.role) && state.draft.status === 'draft') {
      const actions = document.createElement('div'); actions.className = 'line-actions';
      for (const [label, mode] of [['Edit line', 'line'], [line.catalogue_item_id ? 'Detach catalogue' : 'Attach catalogue', line.catalogue_item_id ? 'detach' : 'attach']]) {
        const button = text('button', label, 'quiet'); button.type = 'button';
        button.disabled = !state.revision || state.loading || state.dirty || state.converting;
        button.addEventListener('click', () => editLine(mode, line)); actions.append(button);
      }
      match.append(actions);
    }
    row.append(text('td', String(line.position)), request, quantity, match); return row;
  }));
  $('draft-line-count').textContent = `${state.lineCount} lines · 50 per page`;
  $('draft-lines-state').hidden = Boolean(state.lines.length);
  $('draft-lines-state').textContent = state.errors.lines || (state.loading || state.linesLoading ? 'Loading requested lines…' : 'No requested lines.');
  $('draft-line-page-label').textContent = `Page ${state.linePage} of ${Math.max(1, Math.ceil(state.lineCount / 50))}`;
  $('draft-line-previous').disabled = state.loading || state.linesLoading || Boolean(state.errors.lines) || state.linePage <= 1;
  $('draft-line-next').disabled = state.loading || state.linesLoading || Boolean(state.errors.lines) || state.linePage * 50 >= state.lineCount;
  $('conversion-result').hidden = !state.result;
  $('conversion-number').textContent = state.result?.purchase_order_number ?? '';
  $('conversion-id').textContent = state.result ? `Purchase-order ID: ${state.result.id}` : '';
  $('conversion-permission').textContent = state.workspace.role !== 'admin' ? 'Only workspace administrators can convert drafts.' : state.uncertain ? 'A retry reconciles the same source draft. No duplicate purchase order will be created.' : draft.status === 'converted' ? 'Retrieve the existing purchase order with an authorized repeat request.' : 'Review the requested lines and readiness blockers before confirming.';
  $('convert-draft').hidden = state.workspace.role !== 'admin';
  $('convert-draft').disabled = !canConvert;
  $('convert-draft').textContent = state.converting ? 'Conversion pending…' : state.uncertain ? 'Check conversion result' : draft.status === 'converted' ? 'Show purchase order' : 'Convert to purchase order';
}
