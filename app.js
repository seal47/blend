// web/app.js
(() => {
  // Editable links (header icons)
  const TWITTER_URL = "https://x.com";
  const DEXSCREENER_URL =
    "https://dexscreener.com/";

  const MIN_FILES = 2;
  const MAX_FILES = 15; // keep 15 max
  const MAX_MB = 4;
  const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];
  const API_URL = "/api/server";

  const qs = (sel) => document.querySelector(sel);

  // Apply links to header icons only
  const twitterIcon = qs("#twitter-icon");
  const dexIcon = qs("#dex-icon");
  if (twitterIcon) twitterIcon.href = TWITTER_URL;
  if (dexIcon) dexIcon.href = DEXSCREENER_URL;

  const dropZone = qs("#drop-zone");
  const fileInput = qs("#file-input");
  const pickBtn = qs("#pick-btn");
  const downloadBtn = qs("#download-btn");
  const statusEl = qs("#status");
  const previewWrap = qs("#preview-wrap");
  const previewImg = qs("#preview");
  const footerCopy = qs("#footer-copy");
  const toast = qs("#toast");

  let blendedURL = null;

  function showStatus(msg, isError = false) {
    statusEl.textContent = msg || "";
    statusEl.style.color = isError ? "#ef4444" : "";
  }

  function showToast(text) {
    toast.textContent = text;
    toast.classList.add("show");
    setTimeout(() => {
      toast.classList.remove("show");
    }, 1400);
  }

  function resetPreview() {
    if (blendedURL) {
      URL.revokeObjectURL(blendedURL);
      blendedURL = null;
    }
    previewImg.removeAttribute("src");
    previewWrap.hidden = true;
    downloadBtn.disabled = true;
  }

  function validateFiles(files) {
    const list = Array.from(files);
    if (list.length < MIN_FILES || list.length > MAX_FILES) {
      return `Please select between ${MIN_FILES} and ${MAX_FILES} images.`;
    }
    for (const f of list) {
      const typeOk =
        ACCEPTED.includes(f.type) ||
        /\.(png|jpe?g|webp)$/i.test(f.name || "");
      const sizeOk = f.size <= MAX_MB * 1024 * 1024;
      if (!typeOk) return "Only PNG, JPEG, or WebP images are allowed.";
      if (!sizeOk)
        return `Each file must be ≤ ${MAX_MB} MB. File "${f.name}" is too large.`;
    }
    return null;
  }

  async function upload(files) {
    resetPreview();
    const err = validateFiles(files);
    if (err) {
      showStatus(err, true);
      return;
    }

    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f, f.name));

    pickBtn.disabled = true;
    dropZone.classList.add("dragover");
    showStatus("Blending…");

    try {
      const res = await fetch(API_URL, { method: "POST", body: form });

      if (!res.ok) {
        let msg = "Failed to blend images. Please try again.";
        try {
          const data = await res.json();
          if (data && (data.detail || data.message)) {
            msg = data.detail || data.message;
          }
        } catch {}
        throw new Error(msg);
      }

      const blob = await res.blob();
      blendedURL = URL.createObjectURL(blob);

      previewImg.src = blendedURL;
      previewWrap.hidden = false;
      downloadBtn.disabled = false;
      showStatus("Done.");
    } catch (e) {
      showStatus(e.message || "Something went wrong.", true);
    } finally {
      pickBtn.disabled = false;
      dropZone.classList.remove("dragover");
    }
  }

  // Open native picker
  pickBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length) {
      upload(e.target.files);
      fileInput.value = "";
    }
  });

  // Drag & drop
  ["dragenter", "dragover"].forEach((evtName) => {
    dropZone.addEventListener(evtName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((evtName) => {
    dropZone.addEventListener(evtName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (evtName === "drop") {
        const files = e.dataTransfer?.files;
        if (files && files.length) upload(files);
      }
      dropZone.classList.remove("dragover");
    });
  });
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  // Download action
  downloadBtn.addEventListener("click", () => {
    if (!blendedURL) return;
    const a = document.createElement("a");
    a.href = blendedURL;
    a.download = "blended.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
  });

  // Footer copy-to-clipboard
  footerCopy.addEventListener("click", async () => {
    const text = footerCopy.textContent?.trim() || "";
    try {
      await navigator.clipboard.writeText(text);
      showToast("Copied");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      showToast("Copied");
    }
  });
})();
