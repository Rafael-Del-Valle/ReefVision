export function renderStartupError(
  rootElement: HTMLElement,
  message: string,
  onRetry: () => void | Promise<void>,
): void {
  rootElement.replaceChildren();

  const alert = document.createElement("section");
  alert.className = "empty-state";
  alert.setAttribute("role", "alert");

  const heading = document.createElement("h2");
  heading.textContent = "ReefVision could not start";

  const detail = document.createElement("p");
  detail.textContent = message;

  const retryButton = document.createElement("button");
  retryButton.type = "button";
  retryButton.textContent = "Retry startup";
  retryButton.addEventListener("click", () => {
    retryButton.disabled = true;
    retryButton.textContent = "Retrying...";
    void Promise.resolve(onRetry()).catch(() => {
      retryButton.disabled = false;
      retryButton.textContent = "Retry startup";
    });
  });

  alert.append(heading, detail, retryButton);
  rootElement.append(alert);
}
