(() => {
  const uuid = () => {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, char => {
      const value = Math.random() * 16 | 0;
      return (char === "x" ? value : (value & 3 | 8)).toString(16);
    });
  };

  const parseSources = value => {
    try {
      const parsed = JSON.parse(value || "[]");
      return Array.isArray(parsed) ? parsed.filter(row => row && typeof row === "object") : [];
    } catch (_error) {
      return [];
    }
  };

  document.querySelectorAll(".region-editor").forEach(root => {
    const sourcesField = root.querySelector("#id_sources") || root.closest("form")?.querySelector("#id_sources");
    const sourceList = root.querySelector(".selected-source-list");
    const emptyLabel = root.querySelector(".selection-empty");
    const feedback = root.querySelector(".selection-feedback");
    const countLabel = document.querySelector("#source-count");
    const storageKey = root.dataset.storageKey;
    const pageLabels = new Map([...root.querySelectorAll(".region-card")]
      .map(card => [card.dataset.pageId, card.dataset.pageLabel || "资料页"]));
    let sources = parseSources(sourcesField ? sourcesField.value : "[]");

    if (storageKey && root.dataset.edit !== "true") {
      const saved = parseSources(sessionStorage.getItem(storageKey));
      if (saved.length) sources = [...saved, ...sources];
      sessionStorage.removeItem(storageKey);
    }

    const pointInCanvas = (event, canvas) => {
      const box = canvas.getBoundingClientRect();
      return {
        x: Math.max(0, Math.min(canvas.width, (event.clientX - box.left) * canvas.width / box.width)),
        y: Math.max(0, Math.min(canvas.height, (event.clientY - box.top) * canvas.height / box.height)),
      };
    };

    const draw = card => {
      const canvas = card.querySelector(".region-canvas");
      const ctx = canvas.getContext("2d");
      const width = Number(card.dataset.width);
      const height = Number(card.dataset.height);
      if (!width || !height) return;
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      ctx.clearRect(0, 0, width, height);
      const rotation = Number(card.dataset.rotation);
      sources.filter(source => source.page_id === card.dataset.pageId && Number(source.rotation) === rotation)
        .forEach(source => paintBox(ctx, source.display_bbox, "#0b6e99", width, height));
      if (card.currentRect) paintBox(ctx, card.currentRect, "#d78314", width, height);
    };

    const paintBox = (ctx, bbox, color, width, height) => {
      if (!Array.isArray(bbox) || bbox.length !== 4) return;
      const [x0, y0, x1, y1] = bbox.map(Number);
      if (![x0, y0, x1, y1].every(Number.isFinite)) return;
      ctx.fillStyle = `${color}33`;
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(2, Math.min(width, height) / 500);
      ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    };

    const render = () => {
      if (sourcesField) {
        sourcesField.value = JSON.stringify(sources.map(source => ({
          page_id: source.page_id,
          rotation: Number(source.rotation),
          preview_sha256: source.preview_sha256,
          display_bbox: source.display_bbox,
        })));
      }
      if (sourceList) {
        sourceList.replaceChildren();
        sources.forEach((source, index) => {
          const row = document.createElement("li");
          const label = document.createElement("span");
          label.textContent = `${pageLabels.get(source.page_id) || "资料页"} · ${source.rotation}° · [${source.display_bbox.join(", ")}]`;
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "quiet-button remove-source";
          remove.textContent = "移除";
          remove.setAttribute("aria-label", `移除第 ${index + 1} 个来源区域`);
          remove.addEventListener("click", () => { sources.splice(index, 1); render(); });
          row.append(label, remove);
          sourceList.append(row);
        });
      }
      if (emptyLabel) emptyLabel.hidden = sources.length > 0;
      if (countLabel) countLabel.textContent = `${sources.length} 个区域`;
      root.querySelectorAll(".region-card").forEach(draw);
    };

    const addSource = (card, bbox) => {
      const width = Number(card.dataset.width);
      const height = Number(card.dataset.height);
      const values = Array.isArray(bbox) ? bbox.map(Number) : [];
      if (values.length !== 4 || !values.every(Number.isFinite)) return;
      const [x0, y0, x1, y1] = values.map(Math.round);
      if (x0 < 0 || y0 < 0 || x1 > width || y1 > height || x1 - x0 < 2 || y1 - y0 < 2) {
        if (feedback) feedback.textContent = "区域必须位于图片范围内且有实际面积。";
        return;
      }
      sources.push({
        page_id: card.dataset.pageId,
        rotation: Number(card.dataset.rotation),
        preview_sha256: card.dataset.previewSha,
        display_bbox: [x0, y0, x1, y1],
      });
      if (feedback) feedback.textContent = "";
      card.currentRect = null;
      render();
    };

    root.querySelectorAll(".region-card").forEach(card => {
      const canvas = card.querySelector(".region-canvas");
      const image = card.querySelector(".region-image");
      const selector = card.querySelector(".rotation-select");
      let start = null;

      image.addEventListener("load", () => draw(card));
      if (image.complete) draw(card);

      selector?.addEventListener("change", () => {
        const option = selector.selectedOptions[0];
        card.dataset.rotation = option.value;
        card.dataset.width = option.dataset.width;
        card.dataset.height = option.dataset.height;
        card.dataset.previewSha = option.dataset.sha;
        image.src = option.dataset.url;
        image.width = Number(option.dataset.width);
        image.height = Number(option.dataset.height);
        card.currentRect = null;
        draw(card);
      });

      canvas.addEventListener("pointerdown", event => {
        event.preventDefault();
        start = pointInCanvas(event, canvas);
        canvas.setPointerCapture(event.pointerId);
        card.currentRect = [start.x, start.y, start.x, start.y];
        draw(card);
      });
      canvas.addEventListener("pointermove", event => {
        if (!start) return;
        const point = pointInCanvas(event, canvas);
        card.currentRect = [Math.min(start.x, point.x), Math.min(start.y, point.y), Math.max(start.x, point.x), Math.max(start.y, point.y)];
        draw(card);
      });
      const stop = event => {
        if (!start) return;
        const point = pointInCanvas(event, canvas);
        card.currentRect = [Math.min(start.x, point.x), Math.min(start.y, point.y), Math.max(start.x, point.x), Math.max(start.y, point.y)].map(Math.round);
        start = null;
        draw(card);
      };
      canvas.addEventListener("pointerup", stop);
      canvas.addEventListener("pointercancel", () => { start = null; card.currentRect = null; draw(card); });

      card.querySelector(".add-region")?.addEventListener("click", () => {
        if (card.currentRect) addSource(card, card.currentRect);
      });
      card.querySelector(".add-coordinates")?.addEventListener("click", () => {
        const inputs = [".coord-x0", ".coord-y0", ".coord-x1", ".coord-y1"].map(selectorClass => card.querySelector(selectorClass));
        if (inputs.some(input => !input || input.value.trim() === "")) {
          if (feedback) feedback.textContent = "请填写 x0、y0、x1、y1 四个坐标。";
          return;
        }
        addSource(card, inputs.map(input => input.value));
      });
    });

    root.querySelector(".continue-question")?.addEventListener("click", () => {
      if (storageKey) sessionStorage.setItem(storageKey, JSON.stringify(sources));
    });
    root.closest("form")?.addEventListener("submit", render);
    render();
  });
})();
