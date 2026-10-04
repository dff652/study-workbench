(() => {
  const banner = document.getElementById("pwa-network-status");
  const updateNetwork = () => { if (banner) banner.hidden = navigator.onLine; };
  window.addEventListener("online", updateNetwork);
  window.addEventListener("offline", updateNetwork);
  updateNetwork();

  if (window.isSecureContext && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", {scope: "/", updateViaCache: "none"})
      .catch(() => { console.warn("工作台离线提示暂未就绪。"); });
  }

  const button = document.getElementById("pwa-install");
  if (!button) return;
  let installPrompt = null;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    button.hidden = false;
  });
  button.addEventListener("click", async () => {
    if (!installPrompt) return;
    const prompt = installPrompt;
    installPrompt = null;
    button.hidden = true;
    try { await prompt.prompt(); } catch (error) { /* The browser's menu remains available. */ }
  });
  window.addEventListener("appinstalled", () => { button.hidden = true; installPrompt = null; });
})();
