// background.js -- thin service worker. Remembers the last run's count and, for
// unattended runs only, closes the tab it opened so a scheduled job leaves
// nothing behind. Manual runs never touch your tabs.

let lastDone = null;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "SB_DONE") {
    lastDone = { total: msg.total, at: Date.now() };
    if (msg.auto && sender.tab && sender.tab.id != null) {
      setTimeout(() => chrome.tabs.remove(sender.tab.id).catch(() => {}), 4000);
    }
  } else if (msg.type === "SB_GET_LAST") {
    sendResponse(lastDone);
  }
  return true;
});
