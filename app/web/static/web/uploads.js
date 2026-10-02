(() => {
  const form = document.querySelector("#upload-form");
  const input = document.querySelector("#id_image");
  const status = document.querySelector("#upload-status");
  const results = document.querySelector("#upload-results");
  const submit = document.querySelector("#upload-submit");
  const refresh = document.querySelector("#refresh-after-upload");
  if (!form || !input || !status || !results || !submit || !refresh) return;

  input.multiple = true;
  const newKey = () => {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, char => {
      const value = Math.random() * 16 | 0;
      return (char === "x" ? value : (value & 3 | 8)).toString(16);
    });
  };

  form.addEventListener("submit", async event => {
    if (submit.disabled) {
      event.preventDefault();
      return;
    }
    if (!input.files || input.files.length === 0) return;
    event.preventDefault();
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
    const requestKey = form.querySelector("[name=request_key]");
    const files = [...input.files];
    let successes = 0;
    let failures = 0;
    results.replaceChildren();
    refresh.hidden = true;
    submit.disabled = true;
    input.disabled = true;
    submit.textContent = "正在上传…";
    form.setAttribute("aria-busy", "true");
    for (let index = 0; index < files.length; index += 1) {
      status.textContent = `正在处理第 ${index + 1}/${files.length} 张照片…`;
      const row = document.createElement("li");
      const fileName = document.createElement("span");
      fileName.textContent = files[index].name;
      const state = document.createElement("span");
      state.textContent = "正在上传";
      row.append(fileName, state);
      results.append(row);
      const payload = new FormData();
      payload.append("image", files[index]);
      payload.append("request_key", newKey());
      payload.append("csrfmiddlewaretoken", csrf);
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: payload,
          credentials: "same-origin",
          headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" },
        });
        const result = await response.json().catch(() => null);
        if (response.ok && result && result.ok) {
          successes += 1;
          row.classList.add("upload-success");
          state.textContent = result.duplicate_image ? "已成功加入（复用相同原图）" : "已成功保存";
        } else {
          failures += 1;
          row.classList.add("upload-error");
          state.textContent = result?.message || (response.status === 403
            ? "安全验证失败，请刷新页面后重试。"
            : `上传失败（HTTP ${response.status}）。`);
        }
      } catch (_error) {
        failures += 1;
        row.classList.add("upload-error");
        state.textContent = "网络请求失败，请检查连接后重新选择此照片上传。";
      }
      if (requestKey) requestKey.value = newKey();
    }
    status.textContent = `处理完成：${successes} 张成功，${failures} 张失败。`;
    refresh.hidden = successes === 0;
    submit.disabled = false;
    input.disabled = false;
    submit.textContent = "上传";
    form.removeAttribute("aria-busy");
  });

  refresh.addEventListener("click", () => window.location.reload());
})();
