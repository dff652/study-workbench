(() => {
  const list = document.querySelector("#page-order");
  const form = document.querySelector("#order-form");
  if (!list || !form) return;

  const updatePositions = () => {
    [...list.children].forEach((row, index) => {
      const number = row.querySelector(".page-number");
      if (number) number.textContent = String(index + 1);
      row.querySelector(".move-up").disabled = index === 0;
      row.querySelector(".move-down").disabled = index === list.children.length - 1;
    });
  };

  list.addEventListener("click", event => {
    const row = event.target.closest("li[data-page-id]");
    if (!row) return;
    if (event.target.closest(".move-up") && row.previousElementSibling) {
      list.insertBefore(row, row.previousElementSibling);
      updatePositions();
    } else if (event.target.closest(".move-down") && row.nextElementSibling) {
      list.insertBefore(row.nextElementSibling, row);
      updatePositions();
    }
  });

  form.addEventListener("submit", () => {
    form.querySelector("#id_ids").value = JSON.stringify([...list.children].map(row => row.dataset.pageId));
  });
  updatePositions();
})();
