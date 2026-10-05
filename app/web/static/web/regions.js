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
    const partitionMode = root.hasAttribute("data-partition-editor");
    const pageLabels = new Map([...root.querySelectorAll(".region-card")]
      .map(card => [card.dataset.pageId, card.dataset.pageLabel || "资料页"]));
    let sources = parseSources(sourcesField ? sourcesField.value : "[]");
    const storeSources = () => {
      if (!storageKey) return;
      try { sessionStorage.setItem(storageKey, JSON.stringify(sources)); } catch (_error) { /* Storage can be disabled. */ }
    };

    if (storageKey && root.dataset.edit !== "true") {
      let savedValue = "[]";
      try { savedValue = sessionStorage.getItem(storageKey) || "[]"; } catch (_error) { /* Storage can be disabled. */ }
      const saved = parseSources(savedValue);
      if (saved.length) sources = [...saved, ...sources];
      try { sessionStorage.removeItem(storageKey); } catch (_error) { /* Storage can be disabled. */ }
    }

    const pointInCanvas = (event, canvas) => {
      const box = canvas.getBoundingClientRect();
      return {
        x: Math.max(0, Math.min(canvas.width, (event.clientX - box.left) * canvas.width / box.width)),
        y: Math.max(0, Math.min(canvas.height, (event.clientY - box.top) * canvas.height / box.height)),
      };
    };

    const setupImageTools = card => {
      const viewport = card.querySelector(".image-wrap");
      const image = card.querySelector(".region-image");
      const canvas = card.querySelector(".region-canvas");
      if (!viewport || !image || !canvas) return null;

      viewport.classList.add("region-viewport");
      const stage = document.createElement("div");
      stage.className = "region-stage";
      viewport.insertBefore(stage, image);
      stage.append(image, canvas);

      const toolbar = document.createElement("div");
      toolbar.className = "region-image-tools";
      const button = (className, label, ariaLabel) => {
        const control = document.createElement("button");
        control.type = "button";
        control.className = `secondary-button region-tool-button ${className}`;
        control.textContent = label;
        control.setAttribute("aria-label", ariaLabel);
        return control;
      };
      const pageLabel = card.dataset.pageLabel || "图片";
      const zoomOut = button("region-zoom-out", "缩小", `缩小${pageLabel}`);
      const zoomIn = button("region-zoom-in", "放大", `放大${pageLabel}`);
      const panMode = button("region-pan-mode", "移动图片", `移动${pageLabel}`);
      const selectMode = button("region-select-mode", "框选区域", `框选${pageLabel}`);
      const reset = button("region-reset-view", "重置视图", `重置${pageLabel}视图`);
      panMode.setAttribute("aria-pressed", "false");
      selectMode.setAttribute("aria-pressed", "true");
      const zoomStatus = document.createElement("output");
      zoomStatus.className = "region-zoom-status";
      zoomStatus.setAttribute("aria-live", "polite");
      const modeStatus = document.createElement("span");
      modeStatus.className = "region-mode-status";
      modeStatus.setAttribute("aria-live", "polite");
      toolbar.append(zoomOut, zoomIn, panMode, selectMode, reset, zoomStatus, modeStatus);
      card.insertBefore(toolbar, viewport.nextSibling);

      let zoom = 1;
      let offsetX = 0;
      let offsetY = 0;
      let mode = "select";
      const clampPan = () => {
        offsetX = Math.max(viewport.clientWidth * (1 - zoom), Math.min(0, offsetX));
        offsetY = Math.max(viewport.clientHeight * (1 - zoom), Math.min(0, offsetY));
      };
      const updateView = () => {
        clampPan();
        if (zoom <= 1) mode = "select";
        stage.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${zoom})`;
        zoomStatus.textContent = `图片 ${Math.round(zoom * 100)}%`;
        modeStatus.textContent = mode === "pan" ? "移动模式：拖动图片查看。" : "框选模式：拖动图片选择区域。";
        zoomOut.disabled = zoom <= 1;
        zoomIn.disabled = zoom >= 4;
        panMode.disabled = zoom <= 1;
        panMode.setAttribute("aria-pressed", String(mode === "pan"));
        selectMode.setAttribute("aria-pressed", String(mode === "select"));
        canvas.style.cursor = mode === "pan" ? "grab" : "crosshair";
      };
      const setZoom = nextZoom => {
        const clamped = Math.max(1, Math.min(4, nextZoom));
        const factor = clamped / zoom;
        const centerX = viewport.clientWidth / 2;
        const centerY = viewport.clientHeight / 2;
        offsetX = centerX - (centerX - offsetX) * factor;
        offsetY = centerY - (centerY - offsetY) * factor;
        zoom = clamped;
        updateView();
      };
      const resetView = () => {
        zoom = 1;
        offsetX = 0;
        offsetY = 0;
        updateView();
      };
      const setMode = nextMode => {
        mode = nextMode;
        updateView();
      };
      const panTo = (x, y) => {
        offsetX = x;
        offsetY = y;
        updateView();
      };
      const updateAspect = () => {
        const width = Number(card.dataset.width);
        const height = Number(card.dataset.height);
        if (width > 0 && height > 0) viewport.style.aspectRatio = `${width} / ${height}`;
        resetView();
      };

      zoomOut.addEventListener("click", () => setZoom(zoom - 0.5));
      zoomIn.addEventListener("click", () => setZoom(zoom + 0.5));
      panMode.addEventListener("click", () => setMode("pan"));
      selectMode.addEventListener("click", () => setMode("select"));
      reset.addEventListener("click", resetView);
      updateAspect();
      return { canvas, setMode, updateAspect, panTo, getOffset: () => [offsetX, offsetY] };
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

    const render = (notify = false) => {
      if (sourcesField) {
        sourcesField.value = JSON.stringify(sources.map(source => ({
          page_id: source.page_id,
          rotation: Number(source.rotation),
          preview_sha256: source.preview_sha256,
          display_bbox: source.display_bbox,
          ...(partitionMode ? {kind: source.kind} : {}),
        })));
        if (notify) sourcesField.dispatchEvent(new Event('input', { bubbles: true }));
      }
      if (root.hasAttribute("data-page-editor")) storeSources();
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
          remove.addEventListener("click", () => { sources.splice(index, 1); render(true); });
          row.append(label, remove);
          if (partitionMode) {
            const selector = root.querySelector(".partition-kind").cloneNode(true);
            selector.className = "saved-partition-kind";
            selector.setAttribute("aria-label", `第 ${index + 1} 个分区类型`);
            selector.value = source.kind;
            selector.addEventListener("change", () => { source.kind = selector.value; render(true); });
            row.append(selector);
          }
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
        ...(partitionMode ? {kind: root.querySelector(".partition-kind").value} : {}),
      });
      if (feedback) feedback.textContent = "";
      card.currentRect = null;
      render(true);
    };

    root.querySelectorAll(".region-card").forEach(card => {
      const canvas = card.querySelector(".region-canvas");
      const image = card.querySelector(".region-image");
      const selector = card.querySelector(".rotation-select");
      const imageTools = setupImageTools(card);
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
        imageTools?.updateAspect();
        draw(card);
      });

      canvas.addEventListener("pointerdown", event => {
        event.preventDefault();
        canvas.setPointerCapture(event.pointerId);
        if (card.querySelector(".region-pan-mode")?.getAttribute("aria-pressed") === "true") {
          const [offsetX, offsetY] = imageTools?.getOffset() || [0, 0];
          start = { mode: "pan", clientX: event.clientX, clientY: event.clientY,
            offsetX, offsetY };
          canvas.style.cursor = "grabbing";
          return;
        }
        start = { mode: "select", point: pointInCanvas(event, canvas) };
        card.currentRect = [start.point.x, start.point.y, start.point.x, start.point.y];
        draw(card);
      });
      canvas.addEventListener("pointermove", event => {
        if (!start) return;
        if (start.mode === "pan") {
          imageTools?.panTo(start.offsetX + event.clientX - start.clientX,
            start.offsetY + event.clientY - start.clientY);
          canvas.style.cursor = "grabbing";
          return;
        }
        const point = pointInCanvas(event, canvas);
        card.currentRect = [Math.min(start.point.x, point.x), Math.min(start.point.y, point.y), Math.max(start.point.x, point.x), Math.max(start.point.y, point.y)];
        draw(card);
      });
      const stop = event => {
        if (!start) return;
        if (start.mode === "pan") {
          start = null;
          canvas.style.cursor = "grab";
          return;
        }
        const point = pointInCanvas(event, canvas);
        card.currentRect = [Math.min(start.point.x, point.x), Math.min(start.point.y, point.y), Math.max(start.point.x, point.x), Math.max(start.point.y, point.y)].map(Math.round);
        start = null;
        draw(card);
      };
      canvas.addEventListener("pointerup", stop);
      canvas.addEventListener("pointercancel", () => {
        if (start?.mode === "select") card.currentRect = null;
        start = null;
        draw(card);
      });

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
      storeSources();
    });
    root.closest("form")?.addEventListener("submit", render);
    render();
  });
})();
