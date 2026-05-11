chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "CAPTURE_VISIBLE_TAB") {
    return false;
  }

  chrome.tabs.captureVisibleTab(
    undefined,
    { format: "jpeg", quality: 72 },
    (dataUrl) => {
      if (chrome.runtime.lastError) {
        sendResponse({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      sendResponse({ ok: true, dataUrl });
    }
  );

  return true;
});
