({ page, style, icon }) => {
  // 保留编辑控件的右键操作，页面其余位置不显示浏览器菜单。
  document.addEventListener("contextmenu", (event) => {
    const target = event.composedPath()[0];
    const textInput = target instanceof HTMLInputElement &&
      ["text", "search", "tel", "url", "email", "password", "number"].includes(target.type);
    if (!textInput && !(target instanceof HTMLTextAreaElement) && !target?.isContentEditable) {
      event.preventDefault();
    }
  }, { capture: true });

  if (location.protocol !== "http:" || location.hostname !== "127.0.0.1") {
    return;
  }

  let cover;
  let status;
  let englishStatus;
  const observer = new MutationObserver(update);
  const timeout = setTimeout(showRetry, 45_000);
  observer.observe(document, { childList: true, subtree: true });
  update();

  function update() {
    if (!document.body) {
      return;
    }
    if (!cover) {
      const template = document.createElement("template");
      template.innerHTML = page;
      const content = template.content.querySelector("main");
      content.querySelector("img").src = icon;
      status = content.querySelector("#status");
      status.textContent = "正在加载工作台…";
      englishStatus = content.querySelector("#status-en");
      englishStatus.textContent = "Loading your workspace…";

      cover = document.createElement("div");
      const shadow = cover.attachShadow({ mode: "open" });
      const stylesheet = document.createElement("style");
      stylesheet.textContent = style;
      shadow.append(stylesheet, content);
      document.body.append(cover);
    }
    if (document.querySelector('#mpt-desktop-ready, [data-testid="stException"]')) {
      observer.disconnect();
      // 给底下的界面一次绘制机会，再移除遮罩。
      requestAnimationFrame(() => requestAnimationFrame(finish));
    }
  }

  function showRetry() {
    if (!status) {
      return;
    }
    status.textContent = "工作台加载时间较长，可以继续等待或重试。";
    englishStatus.textContent = "Loading is taking longer than expected. You can wait or reload.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "重新加载 / Reload";
    retry.addEventListener("click", () => location.reload());
    status.parentElement.after(retry);
  }

  function finish() {
    clearTimeout(timeout);
    observer.disconnect();
    cover?.remove();
  }
}
