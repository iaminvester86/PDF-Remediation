// Progressive enhancement. Every feature here also works without JavaScript:
// the form posts normally and the job page has a "Refresh status" link.
(function () {
  "use strict";

  var STATUS_LABELS = {
    "ready-for-review": "Ready for human review",
    "needs-attention": "Needs attention",
    "failed": "Failed",
    "queued": "Queued",
    "processing": "Processing",
    "fetching": "Fetching"
  };

  function isPdfOrZip(name) {
    return /\.(pdf|zip)$/i.test(name || "");
  }

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  // ---------------------------------------------------------------- upload form
  function initForm() {
    var form = document.getElementById("job-form");
    if (!form) return;
    var files = document.getElementById("files");
    var folder = document.getElementById("folder");
    var filesCount = document.getElementById("files-count");
    var folderCount = document.getElementById("folder-count");
    var drop = document.getElementById("drop-zone");
    var status = document.getElementById("upload-status");
    var progress = document.getElementById("upload-progress");
    var button = document.getElementById("submit-btn");
    var dropped = [];

    function describeFiles() {
      var n = files.files.length + dropped.length;
      filesCount.textContent = n ? plural(n, "file") + " selected." : "";
    }
    function describeFolder() {
      var all = folder.files.length, usable = 0;
      for (var i = 0; i < all; i++) if (isPdfOrZip(folder.files[i].name)) usable++;
      folderCount.textContent = all ? plural(usable, "PDF or zip file") + " found in the folder" +
        (all > usable ? " (" + plural(all - usable, "other file") + " will be ignored)." : ".") : "";
    }
    files.addEventListener("change", describeFiles);
    folder.addEventListener("change", describeFolder);

    if (drop && window.FormData) {
      drop.hidden = false;
      ["dragenter", "dragover"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("dragover"); });
      });
      ["dragleave", "drop"].forEach(function (ev) {
        drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("dragover"); });
      });
      drop.addEventListener("drop", function (e) {
        var list = e.dataTransfer.files;
        for (var i = 0; i < list.length; i++) if (isPdfOrZip(list[i].name)) dropped.push(list[i]);
        describeFiles();
      });
    }

    var errorSummary = document.getElementById("error-summary");
    if (errorSummary) errorSummary.focus();

    if (!window.FormData || !window.XMLHttpRequest) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var data = new FormData();
      var i;
      for (i = 0; i < files.files.length; i++) data.append("files", files.files[i], files.files[i].name);
      for (i = 0; i < dropped.length; i++) data.append("files", dropped[i], dropped[i].name);
      for (i = 0; i < folder.files.length; i++) {
        var f = folder.files[i];
        if (!isPdfOrZip(f.name)) continue;  // do not upload unrelated files
        data.append("folder", f, f.name);
        data.append("folder_relpaths", f.webkitRelativePath || f.name);
      }
      ["urls", "lang", "engine", "existing_tags", "ocr"].forEach(function (name) {
        var el = form.elements[name];
        if (el) data.append(name, el.value);
      });
      ["ai", "accept_ai_alt"].forEach(function (name) {
        var el = form.elements[name];
        if (el && el.checked) data.append(name, "on");
      });

      var xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.setRequestHeader("Accept", "application/json");
      button.disabled = true;
      progress.hidden = false;
      status.textContent = "Uploading...";
      var lastAnnounced = -1;
      xhr.upload.addEventListener("progress", function (ev) {
        if (!ev.lengthComputable) return;
        var pct = Math.round((ev.loaded / ev.total) * 100);
        progress.value = pct;
        var step = Math.floor(pct / 25);  // announce at most every 25%
        if (step !== lastAnnounced) {
          lastAnnounced = step;
          status.textContent = "Uploading: " + pct + "%";
        }
      });
      xhr.addEventListener("load", function () {
        var body = {};
        try { body = JSON.parse(xhr.responseText); } catch (err) { body = {}; }
        if (xhr.status === 201 && body.url) {
          status.textContent = "Upload complete. Opening the job...";
          window.location.href = body.url;
          return;
        }
        button.disabled = false;
        progress.hidden = true;
        showErrors(form, body.errors || ["The upload failed (HTTP " + xhr.status + ")."], body.messages || []);
        status.textContent = "";
      });
      xhr.addEventListener("error", function () {
        button.disabled = false;
        progress.hidden = true;
        showErrors(form, ["The upload failed. Check your connection and try again."], []);
      });
      xhr.send(data);
    });
  }

  function showErrors(form, errors, messages) {
    var box = document.getElementById("error-summary");
    if (!box) {
      box = document.createElement("div");
      box.id = "error-summary";
      box.className = "alert alert-error";
      box.setAttribute("role", "alert");
      box.tabIndex = -1;
      form.parentNode.insertBefore(box, form);
    }
    box.innerHTML = "";
    var h = document.createElement("h2");
    h.textContent = "There is a problem";
    box.appendChild(h);
    var ul = document.createElement("ul");
    errors.concat(messages).forEach(function (t) {
      var li = document.createElement("li");
      li.textContent = t;
      ul.appendChild(li);
    });
    box.appendChild(ul);
    document.title = "Error: " + document.title.replace(/^Error: /, "");
    box.focus();
  }

  // ---------------------------------------------------------------- job page
  function initJob() {
    var root = document.getElementById("job-root");
    if (!root || root.getAttribute("data-status") === "complete") return;
    var jobId = root.getAttribute("data-job");
    var text = document.getElementById("job-progress-text");
    var bar = document.getElementById("job-progress");
    var zip = document.getElementById("zip-link");
    var refresh = document.getElementById("refresh-link");
    var tbody = document.getElementById("files-body");
    var lastDone = -1;

    function cell(row, col, value) {
      var td = row.querySelector('[data-col="' + col + '"]');
      if (td && td.textContent !== String(value)) td.textContent = value;
    }
    function ensureTable() {
      if (tbody) return tbody;
      var heading = document.getElementById("files-h");
      var wrap = document.createElement("div");
      wrap.className = "table-wrap";
      wrap.innerHTML = '<table aria-labelledby="files-h"><thead><tr><th scope="col">File</th><th scope="col">Status</th>' +
        '<th scope="col">PDF/UA-1 machine checks</th><th scope="col">Errors</th><th scope="col">Warnings</th>' +
        '<th scope="col">Figures needing alt text</th></tr></thead><tbody id="files-body"></tbody></table>';
      heading.parentNode.insertBefore(wrap, heading.nextSibling);
      tbody = document.getElementById("files-body");
      return tbody;
    }
    function row(f) {
      var tr = document.getElementById("row-" + f.id);
      if (tr) return tr;
      tr = document.createElement("tr");
      tr.id = "row-" + f.id;
      var th = document.createElement("th");
      th.scope = "row";
      var a = document.createElement("a");
      a.href = "/jobs/" + jobId + "/files/" + f.id;
      a.textContent = f.name;
      th.appendChild(a);
      tr.appendChild(th);
      ["status", "machine", "errors", "warnings", "figs"].forEach(function (c) {
        var td = document.createElement("td");
        td.setAttribute("data-col", c);
        tr.appendChild(td);
      });
      ensureTable().appendChild(tr);
      return tr;
    }
    function capital(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }

    function poll() {
      fetch("/api/jobs/" + jobId, { headers: { "Accept": "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (job) {
          job.files.forEach(function (f) {
            var tr = row(f);
            var td = tr.querySelector('[data-col="status"]');
            var label = STATUS_LABELS[f.status] || f.status;
            if (td.getAttribute("data-status") !== f.status) {
              td.setAttribute("data-status", f.status);
              td.innerHTML = "";
              var span = document.createElement("span");
              span.className = "badge badge-" + f.status;
              span.textContent = label;
              td.appendChild(span);
              if (f.error) {
                td.appendChild(document.createElement("br"));
                var hint = document.createElement("span");
                hint.className = "hint";
                hint.textContent = f.error;
                td.appendChild(hint);
              }
            }
            var s = f.summary || {};
            cell(tr, "machine", capital(s.machine_validation || ""));
            cell(tr, "errors", s.errors !== undefined ? s.errors : "");
            cell(tr, "warnings", s.warnings !== undefined ? s.warnings : "");
            cell(tr, "figs", f.figures_without_alt !== undefined && f.figures_without_alt !== null ? f.figures_without_alt : "");
          });
          var p = job.progress || { done: 0, total: 0 };
          bar.max = p.total || 1;
          bar.value = p.done;
          if (job.status === "fetching") {
            if (lastDone !== -2) { text.textContent = "Fetching links..."; lastDone = -2; }
          } else if (p.done !== lastDone || job.status === "complete") {
            lastDone = p.done;
            text.textContent = job.status === "complete"
              ? "All " + plural(p.total, "file") + " finished."
              : p.done + " of " + plural(p.total, "file") + " finished.";
          }
          if (job.status === "complete") {
            zip.hidden = false;
            refresh.hidden = true;
            return;
          }
          window.setTimeout(poll, 2000);
        })
        .catch(function () { window.setTimeout(poll, 5000); });
    }
    poll();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initForm();
    initJob();
  });
})();
