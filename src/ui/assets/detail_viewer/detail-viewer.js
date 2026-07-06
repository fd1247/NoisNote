(function () {
  "use strict";

  var state = {
    payload: {},
    playback: {},
    bridge: null,
    activeId: null,
    scrollTimer: 0,
    timelineRenderGeneration: 0
  };

  var renderer = window.markdownit ? window.markdownit({
    html: true,
    breaks: true,
    linkify: true,
    typographer: false,
    langPrefix: "lang-"
  }) : null;

  function useMarkdownPlugin(plugin) {
    if (renderer && plugin) {
      renderer.use(plugin);
    }
  }

  useMarkdownPlugin(window.markdownitTaskLists);
  useMarkdownPlugin(window.markdownitSub);
  useMarkdownPlugin(window.markdownitSup);
  useMarkdownPlugin(window.markdownitEmoji);
  useMarkdownPlugin(window.markdownitFootnote);
  useMarkdownPlugin(window.markdownitMark);

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderMarkdown(value) {
    var text = String(value || "");
    if (!text) {
      return "<p class=\"muted\">暂无内容。</p>";
    }
    if (renderer && typeof renderer.render === "function") {
      return renderer.render(text);
    }
    return text.split(/\n{2,}/).map(function (part) {
      return "<p>" + escapeHtml(part).replace(/\n/g, "<br>") + "</p>";
    }).join("");
  }

  function sendCommand(command) {
    try {
      command = command || {};
      if (state.payload.recordKey && command.recordKey == null) {
        command.recordKey = state.payload.recordKey;
      }
      if (state.payload.revision != null && command.revision == null) {
        command.revision = state.payload.revision;
      }
      if (state.bridge && state.bridge.postMessage) {
        state.bridge.postMessage(command);
      }
    } catch (error) {
      showError(error);
    }
  }

  function showError(error) {
    var panel = $("errorState");
    if (panel) {
      panel.hidden = false;
      panel.textContent = "详情渲染失败：" + (error && error.message ? error.message : String(error));
    }
    if (state.bridge && state.bridge.postMessage) {
      state.bridge.postMessage({ command: "renderError", message: panel ? panel.textContent : String(error) });
    }
  }

  function setMode(mode) {
    var selected = mode === "timeline" || mode === "summary" ? mode : "transcript";
    $("body-container").hidden = selected === "timeline";
    $("timelinePanel").hidden = selected !== "timeline";
  }

  function secondsLabel(value) {
    var seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds < 0) {
      seconds = 0;
    }
    var minutes = Math.floor(seconds / 60);
    var rest = Math.floor(seconds % 60);
    var ms = Math.floor((seconds - Math.floor(seconds)) * 1000);
    return String(minutes).padStart(2, "0") + ":" + String(rest).padStart(2, "0") + "." + String(ms).padStart(3, "0");
  }

  function clearTimeline() {
    var list = $("timelinePanel");
    state.activeId = null;
    while (list.firstChild) {
      list.removeChild(list.firstChild);
    }
  }

  function renderTimelineChunk(items, index, generation) {
    if (generation !== state.timelineRenderGeneration) {
      return;
    }
    var list = $("timelinePanel");
    var fragment = document.createDocumentFragment();
    var limit = Math.min(index + 120, items.length);
    for (var i = index; i < limit; i += 1) {
      var item = items[i] || {};
      var row = document.createElement("li");
      row.className = "timeline-row";
      row.tabIndex = 0;
      row.dataset.segmentId = String(item.id != null ? item.id : i);
      row.dataset.start = String(item.start || 0);
      row.dataset.end = String(item.end || item.start || 0);

      var time = document.createElement("span");
      time.className = "timeline-time";
      time.textContent = secondsLabel(item.start) + " - " + secondsLabel(item.end);

      var text = document.createElement("span");
      text.className = "timeline-text";
      text.textContent = String(item.text || "");

      row.appendChild(time);
      row.appendChild(text);
      row.addEventListener("click", function (event) {
        var current = event.currentTarget;
        sendCommand({
          command: "seek",
          seconds: Number(current.dataset.start || 0),
          segmentId: Number(current.dataset.segmentId)
        });
      });
      fragment.appendChild(row);
    }
    if (generation !== state.timelineRenderGeneration) {
      return;
    }
    list.appendChild(fragment);
    if (limit < items.length) {
      window.requestAnimationFrame(function () {
        renderTimelineChunk(items, limit, generation);
      });
    } else if (generation === state.timelineRenderGeneration && state.playback) {
      updatePlayback(state.playback);
    }
  }

  function renderTimeline(items) {
    state.timelineRenderGeneration += 1;
    var generation = state.timelineRenderGeneration;
    clearTimeline();
    if (!Array.isArray(items) || !items.length) {
      var row = document.createElement("li");
      row.className = "timeline-row";
      row.textContent = "暂无时间轴。";
      $("timelinePanel").appendChild(row);
      return;
    }
    renderTimelineChunk(items, 0, generation);
  }

  function setContent(payload) {
    try {
      state.payload = payload && typeof payload === "object" ? payload : {};
      state.playback = state.payload.playback || state.playback || {};
      $("errorState").hidden = true;
      $("emptyState").hidden = true;
      $("contentPanel").hidden = false;
      $("vx-content").innerHTML = state.payload.mode === "timeline" ? "" : renderMarkdown(state.payload.content || "");
      renderTimeline(state.payload.timeline || []);
      setMode(state.payload.mode);
      bindLinks();
    } catch (error) {
      showError(error);
    }
  }

  function findActiveRow(position) {
    var rows = Array.prototype.slice.call(document.querySelectorAll(".timeline-row[data-start]"));
    var current = null;
    rows.some(function (row) {
      var start = Number(row.dataset.start || 0);
      var end = Number(row.dataset.end || start);
      if (position >= start && position <= end) {
        current = row;
        return true;
      }
      if (position >= start) {
        current = row;
      }
      return false;
    });
    return current;
  }

  function updatePlayback(payload) {
    try {
      state.playback = payload && typeof payload === "object" ? payload : {};
      var position = Number(state.playback.positionSeconds || 0);
      var row = findActiveRow(Number.isFinite(position) ? position : 0);
      var nextActiveId = row ? row.dataset.segmentId : null;
      if (nextActiveId === state.activeId) {
        return;
      }
      document.querySelectorAll(".timeline-row.active").forEach(function (node) {
        node.classList.remove("active");
      });
      state.activeId = nextActiveId;
      if (!row) {
        return;
      }
      row.classList.add("active");
      window.clearTimeout(state.scrollTimer);
      state.scrollTimer = window.setTimeout(function () {
        row.scrollIntoView({ block: "center", behavior: "smooth" });
      }, 180);
    } catch (error) {
      showError(error);
    }
  }

  function bindLinks() {
    document.querySelectorAll("#vx-content a[href]").forEach(function (link) {
      link.addEventListener("click", function (event) {
        event.preventDefault();
        sendCommand({ command: "openExternalUrl", url: link.href });
      });
    });
  }

  function initBridge() {
    if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, function (channel) {
        state.bridge = channel.objects.detailBridge;
        sendCommand({ command: "ready" });
      });
    }
  }

  window.NoisNoteDetail = {
    setContent: setContent,
    updatePlayback: updatePlayback,
    sendCommand: sendCommand
  };

  document.addEventListener("DOMContentLoaded", initBridge);
}());
