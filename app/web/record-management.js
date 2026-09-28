/* Correct confirmed records while preserving their source and version history. */
(() => {
  const editDialog = document.getElementById('recordEditDialog');
  const trashDialog = document.getElementById('recordTrashDialog');
  const historyDialog = document.getElementById('recordHistoryDialog');
  let editing = null;
  const esc = value => escapeHtml(String(value ?? ''));
  const field = (name, label, value, options = {}) => {
    const required = options.required ? ' required' : '';
    const kind = options.kind || 'text';
    const input = kind === 'textarea'
      ? `<textarea name="${name}"${required}>${esc(value)}</textarea>`
      : `<input name="${name}" type="${kind}" value="${esc(value)}"${required}${kind === 'number' ? ' step="any"' : ''}>`;
    return `<label class="${options.wide ? 'record-field-wide' : ''}"><span>${esc(label)}</span>${input}</label>`;
  };
  const value = (form, name) => form.elements.namedItem(name)?.value.trim() ?? '';
  const nullable = text => text || null;
  const refresh = async () => {
    await Promise.all([loadDocuments(), loadMedications(), loadOverview(), loadMetrics(), loadCosts()]);
  };
  const setForm = (kind, id, title, hint, fields, record) => {
    editing = {kind, id, record};
    document.getElementById('recordEditTitle').textContent = title;
    document.getElementById('recordEditHint').textContent = hint;
    document.getElementById('recordEditFields').innerHTML = fields;
    document.getElementById('recordEditError').textContent = '';
    editDialog.showModal();
    editDialog.querySelector('input:not([type="hidden"]),textarea')?.focus();
  };

  async function openDocumentEdit(id) {
    try {
      const doc = state.currentDocument?.id === id ? state.currentDocument : await api.get(`/api/documents/${id}`);
      if (doc.deleted_at) throw new Error('请先从回收站恢复这份资料');
      const receipt = doc.receipt || doc.type_specific_data?.receipt;
      const hasReceiptFields = Boolean(receipt) || /发票|收费|收据|结算|票据/.test(doc.document_type || '');
      setForm('document', id, `编辑 ${doc.title}`, '原件保留不变；修改的字段和旧值会保留在版本记录中。', [
        field('title', '资料标题 *', doc.title, {required:true, wide:true}),
        field('document_type', '资料类型 *', doc.document_type, {required:true}),
        field('primary_date', '主要日期', doc.primary_date, {kind:'date'}),
        field('hospital', '医院', doc.hospital),
        field('department', '科室', doc.department),
        field('doctor', '医生', doc.doctor),
        field('amount', '总金额', doc.amount, {kind:'number'}),
        ...(hasReceiptFields ? [
          field('insurance_amount', '医保支付', receipt?.insurance_amount, {kind:'number'}),
          field('personal_amount', '个人支付', receipt?.personal_amount, {kind:'number'}),
          field('currency', '币种（如 CNY）', receipt?.currency || 'CNY'),
        ] : []),
        field('key_information', '关键信息（每行一条）', (doc.key_information || []).join('\n'), {kind:'textarea', wide:true}),
      ].join(''), doc);
    } catch (error) { toast(errorText(error)); }
  }

  function openLabEdit(id) {
    const doc = state.currentDocument;
    const lab = doc?.lab_results?.find(item => item.id === id);
    if (!lab || doc.deleted_at) return;
    setForm('lab', id, `修正检验结果：${lab.name}`, '修正后对应的指标结果和趋势会重新计算；原值保留在文档版本记录中。', [
      field('name', '检验项目 *', lab.name, {required:true}),
      field('result', '原始结果', lab.result),
      field('unit', '单位', lab.unit),
      field('reference_range', '原报告参考范围', lab.reference_range),
      field('flag', '原报告提示', lab.flag),
      field('observed_date', '检验日期', lab.observed_date, {kind:'date'}),
      field('condition', '检测条件', lab.condition, {wide:true}),
    ].join(''), {doc, lab});
  }

  async function openEntryEdit(id) {
    try {
      const metricId = state.metricDetailId;
      const result = await api.get(`/api/metric-entries?metric_id=${encodeURIComponent(metricId)}&limit=200`);
      const entry = result.items.find(item => item.id === id);
      if (!entry || entry.voided) throw new Error('日常记录不存在或已移入回收站');
      const metric = state.metricDetailMetric;
      setForm('entry', id, `编辑 ${metric?.name || '日常记录'}`, '只修改手动记录；检验报告结果请在原始资料中修正。', [
        field('record_date', '日期 *', entry.record_date, {kind:'date', required:true}),
        field('raw_value', '原始结果 *', entry.raw_value, {required:true}),
        ...(metric?.record_type === 'qualitative' ? [field('text_value', '文字结果', entry.text_value)] : [
          field('value1', '数值 1', entry.value1, {kind:'number'}),
          ...(metric?.record_type === 'pair' ? [field('value2', '数值 2', entry.value2, {kind:'number'})] : []),
        ]),
        field('unit', '单位', entry.unit),
        field('condition', '条件', entry.condition),
      ].join(''), entry);
    } catch (error) { toast(errorText(error)); }
  }

  async function openMedicationEdit() {
    try {
      const med = await api.get(`/api/medications/${state.medicationDetailId}`);
      if (med.deleted_at) throw new Error('请先从回收站恢复药品');
      setForm('medication', med.id, `编辑 ${med.name}`, '来源原图、包装与用药事件保持可追溯。', [
        field('name', '药品名称 *', med.name, {required:true, wide:true}),
        field('generic_name', '通用名', med.generic_name),
        field('brand_name', '商品名', med.brand_name),
        field('strength', '规格', med.strength),
        field('dosage_form', '剂型', med.dosage_form),
        field('manufacturer', '厂家', med.manufacturer),
        field('approval_number', '批准文号', med.approval_number),
        field('quantity', '数量', med.quantity),
        field('route', '给药途径', med.route),
        field('dose_each_time', '个人实际每次用量', med.dose_each_time),
        field('frequency', '个人实际频次', med.frequency),
        field('timing', '服用时间', med.timing),
        field('planned_end_date', '计划结束日期', med.planned_end_date, {kind:'date'}),
      ].join(''), med);
    } catch (error) { toast(errorText(error)); }
  }

  async function saveEdit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!editing || !form.reportValidity()) return;
    const {kind, id, record} = editing;
    const errorBox = document.getElementById('recordEditError');
    errorBox.textContent = '';
    try {
      if (kind === 'document') {
        const payload = {
          expected_version: record.version,
          title: value(form, 'title'), document_type: value(form, 'document_type'),
          primary_date: nullable(value(form, 'primary_date')),
          hospital: nullable(value(form, 'hospital')),
          department: nullable(value(form, 'department')),
          doctor: nullable(value(form, 'doctor')),
          amount: nullable(value(form, 'amount')),
          key_information: value(form, 'key_information').split(/\r?\n/).map(x => x.trim()).filter(Boolean),
        };
        const receipt = record.receipt || record.type_specific_data?.receipt;
        if (form.elements.namedItem('currency')) {
          const details = structuredClone(record.type_specific_data || {});
          const prior = details.receipt || receipt || {};
          details.receipt = {
            receipt_number:prior.receipt_number || null,
            settlement_time:prior.settlement_time || null,
            payment_method:prior.payment_method || null,
            line_items:prior.line_items || [],
            total_amount:payload.amount,
            insurance_amount: nullable(value(form, 'insurance_amount')),
            personal_amount: nullable(value(form, 'personal_amount')),
            currency: value(form, 'currency').toUpperCase() || 'CNY',
          };
          payload.type_specific_data = details;
        }
        await api.patch(`/api/documents/${id}`, payload);
        if (state.currentDocument?.id === id) {
          state.currentDocument = await api.get(`/api/documents/${id}`);
          renderDocumentDetail();
        }
      } else if (kind === 'lab') {
        const payload = {expected_document_version:record.doc.version};
        for (const name of ['name','result','unit','reference_range','flag','observed_date','condition'])
          payload[name] = nullable(value(form, name));
        await api.patch(`/api/documents/${record.doc.id}/lab-results/${id}`, payload);
        state.currentDocument = await api.get(`/api/documents/${record.doc.id}`);
        renderDocumentDetail();
      } else if (kind === 'entry') {
        const payload = {expected_version:record.version, record_date:value(form,'record_date'), raw_value:value(form,'raw_value'),
          unit:nullable(value(form,'unit')), condition:nullable(value(form,'condition'))};
        if (form.elements.namedItem('value1')) payload.value1 = nullable(value(form,'value1'));
        if (form.elements.namedItem('value2')) payload.value2 = nullable(value(form,'value2'));
        if (form.elements.namedItem('text_value')) payload.text_value = nullable(value(form,'text_value'));
        await api.patch(`/api/metric-entries/${id}`, payload);
      } else if (kind === 'medication') {
        const payload = {expected_version:record.version};
        for (const name of ['name','generic_name','brand_name','strength','dosage_form','manufacturer',
          'approval_number','quantity','route','dose_each_time','frequency','timing','planned_end_date'])
          payload[name] = nullable(value(form, name));
        await api.patch(`/api/medications/${id}`, payload);
        await window.openMedicationDetail(id, true);
      }
      editDialog.close();
      await refresh();
      if (kind === 'entry' && state.metricDetailId) await window.openMetricDetail(state.metricDetailId, true);
      toast('修改已保存，相关统计已更新');
    } catch (error) { errorBox.textContent = errorText(error); }
  }

  async function changeDocumentTrash(restore = false, doc = state.currentDocument) {
    if (!doc) return;
    if (!restore && !window.confirm(`将“${doc.title}”移入回收站？相关指标、费用和档案统计会同步移除，可随时恢复。`)) return;
    try {
      const result = await api.post(`/api/documents/${doc.id}/${restore ? 'restore' : 'trash'}`, {expected_version:doc.version});
      if (state.currentDocument?.id === doc.id) {
        state.currentDocument = await api.get(`/api/documents/${doc.id}`);
        renderDocumentDetail();
      }
      await refresh();
      toast(restore ? '资料已恢复，统计已更新' : '资料已移入回收站，统计已更新');
      return result;
    } catch (error) { toast(errorText(error)); }
  }

  async function changeMedicationTrash(restore = false, med = state.currentMedication) {
    if (!med) return;
    if (!restore && !window.confirm(`将“${med.name}”移入回收站？可从药品回收站恢复。`)) return;
    try {
      await api.post(`/api/medications/${med.id}/${restore ? 'restore' : 'trash'}`, {expected_version:med.version});
      await refresh();
      if (state.currentView === 'medication-detail') showView('drugs', {refresh:false, restoreScroll:true});
      toast(restore ? '药品已恢复' : '药品已移入回收站');
    } catch (error) { toast(errorText(error)); }
  }

  async function changeEntryTrash(id, restore = false, source = null) {
    if (!restore && !window.confirm('将这条手动记录移入回收站？趋势会同步更新，可恢复。')) return;
    try {
      const entry = source || (await api.get(`/api/metric-entries?metric_id=${encodeURIComponent(state.metricDetailId)}&limit=200`)).items.find(item => item.id === id);
      if (!entry) throw new Error('日常记录不存在');
      await api.patch(`/api/metric-entries/${id}`, {expected_version:entry.version, voided:!restore});
      await Promise.all([loadMetrics(), loadOverview()]);
      if (state.metricDetailId) await window.openMetricDetail(state.metricDetailId, true);
      if (restore) await showEntryTrash();
      toast(restore ? '日常记录已恢复' : '日常记录已移入回收站');
    } catch (error) { toast(errorText(error)); }
  }

  async function showEntryTrash() {
    try {
      const result = await api.get(`/api/metric-entries?metric_id=${encodeURIComponent(state.metricDetailId)}&voided=true&limit=200`);
      document.getElementById('recordTrashTitle').textContent = `${state.metricDetailMetric?.name || '指标'} · 日常记录回收站`;
      document.getElementById('recordTrashHint').textContent = '恢复后重新参与该指标的历史和趋势。';
      document.getElementById('recordTrashItems').innerHTML = result.items.length
        ? result.items.map(item => `<article class="record-trash-item"><div><strong>${esc(item.raw_value)} ${esc(item.unit)}</strong><p>${esc(item.record_date)}</p></div><button class="btn small" type="button" data-restore-entry="${esc(item.id)}" data-version="${item.version}">恢复</button></article>`).join('')
        : '<div class="empty compact-empty">没有已移除的日常记录</div>';
      if (!trashDialog.open) trashDialog.showModal();
    } catch (error) { toast(errorText(error)); }
  }

  window.loadTrashDocuments = async function loadTrashDocuments() {
    try {
      document.getElementById('archiveCollection').classList.add('hidden');
      document.getElementById('archiveStatus').textContent = '回收站中的资料可查看、恢复；不会参与当前档案统计。';
      const result = await api.get('/api/documents/trash');
      const search = document.getElementById('archiveSearch').value.trim().toLocaleLowerCase();
      const items = result.items.filter(item => !search || [item.title,item.document_type,item.hospital]
        .some(text => String(text || '').toLocaleLowerCase().includes(search)));
      document.getElementById('archiveList').innerHTML = items.length
        ? items.map(item => `<article class="record-trash-item"><div><strong>${esc(item.title)}</strong><p>${esc([item.document_type,item.primary_date,item.hospital].filter(Boolean).join(' · '))}</p></div><div class="record-head-actions"><button class="btn small" type="button" data-document="${esc(item.id)}">查看</button><button class="btn small" type="button" data-restore-document="${esc(item.id)}" data-version="${item.version}">恢复</button></div></article>`).join('')
        : `<div class="empty">${search ? '没有符合搜索条件的资料' : '回收站为空'}</div>`;
    } catch (error) { toast(errorText(error)); }
  };

  async function showMedicationTrash() {
    try {
      const result = await api.get('/api/medications/trash');
      document.getElementById('recordTrashTitle').textContent = '药品回收站';
      document.getElementById('recordTrashHint').textContent = '恢复药品后，如来源资料仍在回收站，请先恢复来源资料。';
      document.getElementById('recordTrashItems').innerHTML = result.items.length
        ? result.items.map(item => `<article class="record-trash-item"><div><strong>${esc(item.name)}</strong><p>${esc([item.generic_name,item.strength].filter(Boolean).join(' · '))}</p></div><button class="btn small" type="button" data-restore-medication="${esc(item.id)}" data-version="${item.version}">恢复</button></article>`).join('')
        : '<div class="empty compact-empty">回收站为空</div>';
      trashDialog.showModal();
    } catch (error) { toast(errorText(error)); }
  }

  async function showHistory(kind, id, title) {
    const path = kind === 'document' ? `/api/documents/${id}/revisions`
      : kind === 'medication' ? `/api/medications/${id}/revisions`
      : `/api/metric-entries/${id}/revisions`;
    try {
      const result = await api.get(path);
      document.getElementById('recordHistoryTitle').textContent = `${title} · 修改记录`;
      document.getElementById('recordHistoryItems').innerHTML = result.items.length
        ? result.items.map(item => `<article class="record-history-item"><strong>${esc(new Date(item.created_at).toLocaleString('zh-CN'))}</strong><p>第 ${esc(item.from_version)} 版 · 修改：${esc((item.changed_fields || []).join('、'))}</p><details><summary>查看修改前的数据</summary><pre>${esc(JSON.stringify(item.snapshot, null, 2))}</pre></details></article>`).join('')
        : '<div class="empty compact-empty">尚无修改记录</div>';
      historyDialog.showModal();
    } catch (error) { toast(errorText(error)); }
  }

  document.getElementById('recordEditForm').addEventListener('submit', saveEdit);
  document.body.addEventListener('click', async event => {
    const target = event.target.closest('button');
    if (!target) return;
    if (target.matches('[data-close-record-edit]')) return editDialog.close();
    if (target.matches('[data-close-record-trash]')) return trashDialog.close();
    if (target.matches('[data-close-record-history]')) return historyDialog.close();
    if (target.id === 'archiveTrashToggle') {
      state.archiveTrashMode = !state.archiveTrashMode;
      target.textContent = state.archiveTrashMode ? '返回档案' : '回收站';
      if (state.archiveTrashMode) await window.loadTrashDocuments(); else renderArchive();
      return;
    }
    if (target.id === 'documentEditBtn') return openDocumentEdit(state.currentDocument.id);
    if (target.dataset.editDocumentId) return openDocumentEdit(target.dataset.editDocumentId);
    if (target.id === 'documentTrashBtn') return changeDocumentTrash();
    if (target.id === 'documentRestoreBtn') return changeDocumentTrash(true);
    if (target.dataset.restoreDocument) return changeDocumentTrash(true, {id:target.dataset.restoreDocument,version:Number(target.dataset.version)});
    if (target.id === 'documentHistoryBtn') return showHistory('document',state.currentDocument.id,state.currentDocument.title);
    if (target.dataset.editLabId) return openLabEdit(target.dataset.editLabId);
    if (target.id === 'medicationEditBtn') return openMedicationEdit();
    if (target.id === 'medicationRemoveBtn') return changeMedicationTrash();
    if (target.id === 'medicationHistoryBtn') return showHistory('medication',state.medicationDetailId,state.currentMedication?.name||'药品');
    if (target.id === 'medicationTrashBtn') return showMedicationTrash();
    if (target.dataset.restoreMedication) {
      const med = {id:target.dataset.restoreMedication,version:Number(target.dataset.version)};
      await changeMedicationTrash(true,med);
      trashDialog.close();
      return;
    }
    if (target.id === 'metricEntryTrashBtn') return showEntryTrash();
    if (target.dataset.editEntry) return openEntryEdit(target.dataset.editEntry);
    if (target.dataset.trashEntry) return changeEntryTrash(target.dataset.trashEntry);
    if (target.dataset.restoreEntry) return changeEntryTrash(target.dataset.restoreEntry,true,
      {id:target.dataset.restoreEntry,version:Number(target.dataset.version)});
  });
})();
