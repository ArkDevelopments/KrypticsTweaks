'use strict';
const shareButton = document.querySelector('#share');
const status = document.querySelector('#share-status');
shareButton.addEventListener('click', async () => {
  const local = location.protocol === 'file:' || ['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname);
  const text = "Kryptic's Tweaks — Tune. Measure. Play. A Windows performance workspace with Roblox-focused guidance and reversible controls.";
  const data = {title: "Kryptic's Tweaks", text};
  if (!local) data.url = location.href.split('#')[0];
  try {
    if (navigator.share && !local) {
      await navigator.share(data);
      status.textContent = 'Thanks for sharing Kryptic.';
    } else if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text + (data.url ? '\n' + data.url : ''));
      status.textContent = local ? 'Launch text copied. Publish the website to share a public download link.' : 'Kryptic link copied.';
    } else {
      status.textContent = text + (data.url ? ' ' + data.url : ' Publish this site to get a public download link.');
    }
  } catch (error) {
    status.textContent = error.name === 'AbortError' ? 'Sharing cancelled.' : 'Could not open sharing. You can copy the page address instead.';
  }
});
