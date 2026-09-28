// Folder upload for the Runs page: pick a folder, upload its images in batches, then run the pipeline.
// Batches stay under the server's request size limit (PIC_MAX_UPLOAD_SIZE_MB).
(function () {
  "use strict";

  const BATCH_MAX_FILES = 50;
  const BATCH_OVERHEAD = 64 * 1024; // multipart boundaries and headers

  function init() {
    const root = document.getElementById("folder-upload");
    if (!root) return;
    const input = document.getElementById("folder-input");
    const summary = document.getElementById("folder-summary");
    const start = document.getElementById("folder-start");
    const progress = document.getElementById("folder-progress");
    const status = document.getElementById("folder-status");
    const maxBytes = Number(root.dataset.maxBytes);
    const extensions = new Set(root.dataset.extensions.split(","));
    let picked = { images: [], tooLarge: [], other: 0 };

    function extensionOf(name) {
      const dot = name.lastIndexOf(".");
      return dot === -1 ? "" : name.slice(dot).toLowerCase();
    }

    function sizeLabel(bytes) {
      if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + " KB";
      return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }

    input.addEventListener("change", function () {
      picked = { images: [], tooLarge: [], other: 0 };
      for (const file of input.files) {
        if (!extensions.has(extensionOf(file.name))) picked.other += 1;
        else if (file.size + BATCH_OVERHEAD > maxBytes) picked.tooLarge.push(file.webkitRelativePath || file.name);
        else picked.images.push(file);
      }
      const total = picked.images.reduce((sum, f) => sum + f.size, 0);
      const parts = [picked.images.length + " image" + (picked.images.length === 1 ? "" : "s") + " (" + sizeLabel(total) + ")"];
      if (picked.other) parts.push(picked.other + " other file" + (picked.other === 1 ? "" : "s") + " ignored");
      if (picked.tooLarge.length) parts.push(picked.tooLarge.length + " too large to upload");
      summary.textContent = input.files.length ? parts.join(", ") + "." : "No folder chosen yet.";
      start.disabled = picked.images.length === 0;
      status.textContent = "";
      progress.hidden = true;
    });

    function batches(files) {
      const result = [];
      let current = [];
      let bytes = 0;
      for (const file of files) {
        if (current.length && (current.length >= BATCH_MAX_FILES || bytes + file.size + BATCH_OVERHEAD > maxBytes)) {
          result.push(current);
          current = [];
          bytes = 0;
        }
        current.push(file);
        bytes += file.size;
      }
      if (current.length) result.push(current);
      return result;
    }

    function send(batch, onProgress) {
      return new Promise(function (resolve, reject) {
        const form = new FormData();
        for (const file of batch) form.append("files", file, file.webkitRelativePath || file.name);
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/ui/upload");
        xhr.setRequestHeader("HX-Request", "true");
        xhr.responseType = "json";
        xhr.upload.onprogress = function (event) {
          if (event.lengthComputable) onProgress(event.loaded / event.total);
        };
        xhr.onload = function () {
          if (xhr.status === 401) {
            window.location.href = "/ui/login?next=/ui/jobs";
            return;
          }
          if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
          else reject(new Error((xhr.response && xhr.response.detail) || "Upload failed (HTTP " + xhr.status + ")"));
        };
        xhr.onerror = function () { reject(new Error("Network error while uploading")); };
        xhr.send(form);
      });
    }

    start.addEventListener("click", async function () {
      const all = batches(picked.images);
      const totalBytes = picked.images.reduce((sum, f) => sum + f.size, 0) || 1;
      let doneBytes = 0;
      let stored = 0;
      let skipped = picked.tooLarge.length;
      start.disabled = true;
      input.disabled = true;
      progress.hidden = false;
      progress.value = 0;
      try {
        for (let i = 0; i < all.length; i += 1) {
          const batchBytes = all[i].reduce((sum, f) => sum + f.size, 0);
          status.textContent = "Uploading batch " + (i + 1) + " of " + all.length + "…";
          const response = await send(all[i], function (fraction) {
            progress.value = Math.round(((doneBytes + fraction * batchBytes) / totalBytes) * 100);
          });
          doneBytes += batchBytes;
          stored += response.stored;
          skipped += response.skipped.length;
        }
        progress.value = 100;
        status.textContent = "Uploaded " + stored + " image" + (stored === 1 ? "" : "s") + (skipped ? " (" + skipped + " skipped)" : "") + (stored > 0 ? ". Pipeline started; follow it under Recent runs." : ".");
        if (stored > 0) {
          window.htmx.ajax("POST", "/ui/jobs/run/pipeline", { target: "#jobs", swap: "outerHTML" });
        }
      } catch (error) {
        status.textContent = error.message + ". " + stored + " image(s) were uploaded before the error; run the pipeline from “Already in storage” to ingest them.";
      } finally {
        input.disabled = false;
        start.disabled = picked.images.length === 0;
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
