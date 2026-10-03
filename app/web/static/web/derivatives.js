(() => {
  'use strict';
  const form = document.getElementById('derivative-form');
  if (!form) return;
  const rotation = form.querySelector('[name=rotation]');
  const sha = form.querySelector('[name=preview_sha256]');
  const pageRotation = document.querySelector('.rotation-select');
  rotation.addEventListener('change', () => {
    const option = [...pageRotation.options].find(o => o.value === rotation.value);
    if (option) sha.value = option.dataset.sha;
  });
  document.getElementById('use-derivative-region').addEventListener('click', () => {
    const feedback = document.getElementById('derivative-feedback');
    try {
      const sources = JSON.parse(sessionStorage.getItem(form.dataset.storageKey) || '[]');
      const source = [...sources].reverse().find(s => s.page_id === form.dataset.pageId);
      if (!source) { feedback.textContent = '请先在本页框选并加入区域。'; return; }
      form.querySelector('[name=display_bbox]').value = JSON.stringify(source.display_bbox);
      rotation.value = String(source.rotation);
      sha.value = source.preview_sha256;
      feedback.textContent = '已使用本页最后加入的区域。输出保持原图方向。';
    } catch (_) { feedback.textContent = '区域数据无效，请重新框选。'; }
  });
})();
