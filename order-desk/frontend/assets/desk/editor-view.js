const $ = id => document.getElementById(id);
let displayedVersion = -1;
export function renderEditor(editor) {
  const s = editor.state; const dialog = $('draft-editor');
  if (!s.open) {
    if (dialog.open) dialog.close();
    $('editor-form').reset(); $('editor-message').textContent = ''; $('attach-item').replaceChildren();
    $('editor-general-error').textContent = '';
    for (const label of $('editor-form').querySelectorAll('[data-error]')) label.textContent = '';
    for (const control of $('editor-form').querySelectorAll('[aria-invalid]')) control.removeAttribute('aria-invalid');
    return;
  }
  if (!dialog.open) dialog.showModal();
  const labels = { create: 'Create manual draft', header: 'Edit customer fields', 'add-line': 'Add requested line', line: 'Edit requested line', attach: 'Attach catalogue item', detach: 'Detach catalogue item' };
  $('editor-heading').textContent = labels[s.mode];
  $('editor-message').textContent = s.message;
  $('editor-header-fields').hidden = !['create', 'header'].includes(s.mode);
  $('editor-intake-field').hidden = s.mode !== 'create';
  $('editor-line-fields').hidden = !['add-line', 'line'].includes(s.mode);
  $('editor-position-field').hidden = s.mode !== 'add-line';
  $('editor-catalogue-fields').hidden = s.mode !== 'attach';
  $('editor-detach-note').hidden = s.mode !== 'detach';
  if (displayedVersion !== editor.version) {
    displayedVersion = editor.version;
    for (const control of $('editor-form').elements) if (control.name) control.value = s.input[control.name] ?? '';
    $('attach-query').value = s.catalogQuery;
  }
  for (const fieldset of $('editor-form').querySelectorAll('fieldset')) fieldset.disabled = s.pending;
  for (const label of $('editor-form').querySelectorAll('[data-error]')) {
    const errors = s.errors[label.dataset.error]; label.textContent = Array.isArray(errors) ? errors.join(' ') : errors ?? '';
    const control = $('editor-form').elements.namedItem(label.dataset.error);
    if (control) control.setAttribute('aria-invalid', errors ? 'true' : 'false');
  }
  $('editor-general-error').textContent = Object.entries(s.errors).filter(([field]) => !$('editor-form').elements.namedItem(field)).flatMap(([, error]) => Array.isArray(error) ? error : [error]).join(' ');
  $('editor-save').disabled = s.pending || s.blocked || !editor.canEdit(s.mode);
  $('editor-save').textContent = s.pending ? 'Saving…' : s.mode === 'create' ? 'Create draft' : s.mode === 'attach' ? 'Attach item' : s.mode === 'detach' ? 'Detach item' : 'Save changes';
  $('editor-discard').disabled = s.pending;
  $('editor-reload').hidden = !s.blocked; $('editor-reload').disabled = s.pending;
  $('attach-item').replaceChildren(new Option(s.catalogBusy ? 'Loading active items…' : s.items.length ? 'Choose an item' : 'No active items found', ''), ...s.items.map(item => new Option(`${item.sku} · ${item.description} · Active`, item.id)));
  $('attach-item').value = s.input.catalogue_item_id ?? '';
  $('attach-previous').disabled = s.catalogBusy || s.catalogPage <= 1;
  $('attach-next').disabled = s.catalogBusy || s.catalogPage * 50 >= s.catalogCount;
  $('attach-page').textContent = `Page ${s.catalogPage}`;
}
