(function () {
  "use strict";

  var state = {
    payload: {},
    playback: {},
    bridge: null,
    activeId: null,
    timelineRenderGeneration: 0,
    lastScrollAtTop: true,
    editMode: false,
    editSaveTimer: null,
    pendingEditCommand: null,
    suppressEditorEvent: false,
    search: { query: "", index: 0, matches: [] }
  };

  var DETAIL_SCROLL_OVERFLOW_THRESHOLD = 24;

  var headerIds = [new Set(), new Set()];
  var renderer = window.markdownit ? window.markdownit({
    html: true,
    breaks: false,
    linkify: true,
    typographer: false,
    langPrefix: "lang-",
    quotes: ""
  }) : null;

  if (renderer) {
    var defaultValidateLink = renderer.validateLink;
    renderer.validateLink = function (url) {
      var normalized = String(url || "").trim().toLowerCase();
      return /^file:/.test(normalized) ? true : defaultValidateLink.call(renderer, url);
    };
  }

  function useMarkdownPlugin(plugin, options) {
    if (renderer && plugin) {
      renderer.use(plugin, options);
    }
  }

  function resetHeaderIds() {
    headerIds[0].clear();
    headerIds[1].clear();
  }

  function headingSequenceRegExp() {
    return /^(\s*\d+(\.\d+)*\.?\s+)/;
  }

  function generateHeaderId(index, value) {
    var text = String(value || "")
      .replace(headingSequenceRegExp(), "")
      .toLowerCase()
      .replace(/[^\p{L}\p{M}\p{N}\p{Pc}\u002D\u0020]/gu, "")
      .replace(/ /g, "-");
    var ids = headerIds[index];
    var id = text || "section";
    var next = 1;
    while (ids.has(id)) {
      id = text + "-" + next;
      next += 1;
    }
    ids.add(id);
    return id;
  }

  useMarkdownPlugin(window.markdownitContainer, "alert", {
    validate: function (params) {
      return params.trim().match(/^alert-\S+$/);
    },
    render: function (tokens, index) {
      var type = tokens[index].info.trim().match(/^(alert-\S+)$/);
      if (tokens[index].nesting === 1) {
        return "<div class=\"vx-alert " + type[1] + "\" role=\"alert\">";
      }
      return "</div>\n";
    }
  });
  useMarkdownPlugin(window.markdownitTaskLists);
  useMarkdownPlugin(window.markdownitSub);
  useMarkdownPlugin(window.markdownitSup);
  useMarkdownPlugin(window.markdownitEmoji);
  if (renderer && renderer.renderer && renderer.renderer.rules) {
    renderer.renderer.rules.emoji = function (tokens, index) {
      return "<span class=\"emoji emoji_" + tokens[index].markup + "\">" + tokens[index].content + "</span>";
    };
  }
  useMarkdownPlugin(window.markdownitFootnote);
  useMarkdownPlugin(window["markdown-it-imsize.js"]);
  useMarkdownPlugin(window.markdownitInjectLinenumbers);
  useMarkdownPlugin(window.markdownItAnchor, {
    slugify: function (value) {
      return generateHeaderId(0, value);
    },
    permalink: true,
    permalinkBefore: false,
    permalinkClass: "vx-header-anchor",
    permalinkSpace: false,
    permalinkSymbol: "",
    permalinkAttrs: function () {
      return { "vx-data-anchor-icon": "¶" };
    }
  });
  useMarkdownPlugin(window.markdownItTocDoneRight, {
    slugify: function (value) {
      return generateHeaderId(1, value);
    },
    containerClass: "vx-table-of-contents"
  });
  useMarkdownPlugin(window.markdownitImplicitFigure, { figcaption: true });
  useMarkdownPlugin(window.markdownitMark);
  useMarkdownPlugin(window.markdownitFrontMatter, function (metadata) {
    state.frontMatter = metadata || "";
  });

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

  function sanitizeRenderedHtml(html) {
    var template = document.createElement("template");
    template.innerHTML = html;
    template.content.querySelectorAll("style").forEach(function (node) {
      node.remove();
    });
    template.content.querySelectorAll("[style]").forEach(function (node) {
      node.removeAttribute("style");
    });
    return template.innerHTML;
  }

  function renderMarkdown(value) {
    var text = String(value || "");
    if (!text) {
      return "";
    }
    if (renderer && typeof renderer.render === "function") {
      resetHeaderIds();
      state.frontMatter = "";
      var html = renderer.render(text);
      if (state.frontMatter) {
        html = "<details class=\"vx-frontmatter\"><summary>Metadata</summary><pre>"
          + escapeHtml(state.frontMatter)
          + "</pre></details>" + html;
      }
      return sanitizeRenderedHtml(html);
    }
    return text.split(/\n{2,}/).map(function (part) {
      return "<p>" + escapeHtml(part).replace(/\n/g, "<br>") + "</p>";
    }).join("");
  }

  function clearSearchHighlights() {
    document.querySelectorAll(".vx-search-match, .vx-current-search-match").forEach(function (node) {
      var parent = node.parentNode;
      if (!parent) {
        return;
      }
      parent.replaceChild(document.createTextNode(node.textContent || ""), node);
      parent.normalize();
    });
    state.search.matches = [];
  }

  function searchRoot() {
    var mode = state.payload && state.payload.mode === "timeline" ? "timeline" : "body";
    return mode === "timeline" ? $("timelinePanel") : $("vx-content");
  }

  function highlightTextNode(node, query, matches) {
    var text = node.nodeValue || "";
    var lowerText = text.toLowerCase();
    var lowerQuery = query.toLowerCase();
    var start = 0;
    var index = lowerText.indexOf(lowerQuery, start);
    if (index < 0) {
      return;
    }
    var fragment = document.createDocumentFragment();
    while (index >= 0) {
      if (index > start) {
        fragment.appendChild(document.createTextNode(text.slice(start, index)));
      }
      var span = document.createElement("span");
      span.className = "vx-search-match";
      span.textContent = text.slice(index, index + query.length);
      fragment.appendChild(span);
      matches.push(span);
      start = index + query.length;
      index = lowerText.indexOf(lowerQuery, start);
    }
    if (start < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(start)));
    }
    node.parentNode.replaceChild(fragment, node);
  }

  function applySearchState() {
    clearSearchHighlights();
    if (state.editMode && selectedMode() !== "timeline") {
      emitSearchChanged(0, 0);
      return;
    }
    var query = String(state.search.query || "");
    if (!query) {
      emitSearchChanged(0, 0);
      return;
    }
    var root = searchRoot();
    if (!root) {
      return;
    }
    var nodes = [];
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var node = walker.nextNode();
    while (node) {
      if ((node.nodeValue || "").trim()) {
        nodes.push(node);
      }
      node = walker.nextNode();
    }
    var matches = [];
    nodes.forEach(function (textNode) {
      highlightTextNode(textNode, query, matches);
    });
    state.search.matches = matches;
    if (!matches.length) {
      emitSearchChanged(0, 0);
      return;
    }
    state.search.index = Math.max(0, Math.min(Number(state.search.index || 0), matches.length - 1));
    var current = matches[state.search.index];
    current.classList.add("vx-current-search-match");
    current.scrollIntoView({ block: "center", behavior: "smooth" });
    emitSearchChanged(matches.length, state.search.index);
  }

  function setSearchState(payload) {
    payload = payload && typeof payload === "object" ? payload : {};
    state.search.query = String(payload.query || "");
    state.search.index = Math.max(0, Number(payload.index || 0));
    applySearchState();
  }

  function selectedMode() {
    return state.payload && state.payload.mode === "timeline"
      ? "timeline"
      : state.payload && state.payload.mode === "summary" ? "summary" : "transcript";
  }

  function activeSourceText() {
    return String(state.payload && state.payload.content ? state.payload.content : "");
  }

  function syncEditorText() {
    var editor = $("editorPanel");
    if (!editor) {
      return;
    }
    state.suppressEditorEvent = true;
    editor.value = activeSourceText();
    state.suppressEditorEvent = false;
  }

  function timelineDisplayText(items) {
    return (Array.isArray(items) ? items : []).map(function (item) {
      item = item || {};
      return secondsLabel(item.start) + " - " + secondsLabel(item.end) + "  " + String(item.text || "");
    }).join("\n");
  }

  function timelineTextParts(text) {
    return String(text || "").match(/\s+|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]|[^\s]/gu) || [];
  }

  function tokenizeTimelineText(text, start, end) {
    var parts = timelineTextParts(text);
    var visibleParts = parts.filter(function (part) {
      return String(part || "").trim();
    });
    if (!visibleParts.length) {
      return [];
    }
    var safeStart = Number(start || 0);
    var safeEnd = Number(end || safeStart);
    if (!Number.isFinite(safeStart) || safeStart < 0) {
      safeStart = 0;
    }
    if (!Number.isFinite(safeEnd) || safeEnd < safeStart) {
      safeEnd = safeStart;
    }
    var duration = safeEnd - safeStart;
    var visibleIndex = 0;
    var cursor = safeStart;
    return parts.map(function (part) {
      var textPart = String(part || "");
      if (!textPart.trim()) {
        return { start: cursor, end: cursor, text: textPart };
      }
      visibleIndex += 1;
      var next = safeStart + duration * visibleIndex / visibleParts.length;
      var token = { start: cursor, end: next, text: textPart };
      cursor = next;
      return token;
    });
  }

  function renderTimelineText(node, item) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
    node.appendChild(renderTimelineTokens(item));
  }

  function syncTimelineEditMode() {
    document.querySelectorAll(".timeline-text").forEach(function (node) {
      node.setAttribute("contenteditable", state.editMode ? "true" : "false");
      node.setAttribute("spellcheck", "false");
    });
  }

  function emitTimelineChange(event) {
    if (!state.editMode) {
      return;
    }
    var target = event && event.currentTarget ? event.currentTarget : null;
    var row = target && target.closest ? target.closest(".timeline-entry") : null;
    if (!target || !row || !state.payload || !Array.isArray(state.payload.timeline)) {
      return;
    }
    var index = Number(row.dataset.itemIndex);
    if (!Number.isInteger(index) || index < 0 || index >= state.payload.timeline.length) {
      return;
    }
    var item = state.payload.timeline[index] || {};
    var text = String(target.textContent || "");
    item.text = text;
    item.tokens = tokenizeTimelineText(text, item.start || 0, item.end || item.start || 0);
    state.payload.timeline[index] = item;
    state.payload.content = timelineDisplayText(state.payload.timeline);
    scheduleContentChanged({
      command: "contentChanged",
      mode: "timeline",
      text: state.payload.content,
      timeline: state.payload.timeline
    });
  }

  function emitEditorChange() {
    if (state.suppressEditorEvent || !state.editMode) {
      return;
    }
    var editor = $("editorPanel");
    if (!editor) {
      return;
    }
    if (!state.payload || typeof state.payload !== "object") {
      state.payload = {};
    }
    state.payload.content = editor.value;
    scheduleContentChanged({
      command: "contentChanged",
      mode: selectedMode(),
      text: editor.value
    });
  }

  function setEditMode(payload) {
    payload = payload && typeof payload === "object" ? payload : { enabled: payload };
    var wasEditing = state.editMode;
    if (!payload.enabled && wasEditing) {
      flushPendingEditCommand();
    }
    state.editMode = Boolean(payload.enabled);
    if (state.editMode) {
      clearSearchHighlights();
      if (selectedMode() !== "timeline") {
        syncEditorText();
      }
    } else if (wasEditing) {
      renderCurrentPayloadBody();
    }
    setMode(selectedMode());
    syncTimelineEditMode();
    applySearchState();
  }

  function postBridgeMessage(command) {
    if (state.bridge && state.bridge.postMessage) {
      state.bridge.postMessage(JSON.stringify(command || {}));
    }
  }

  function prepareCommand(command) {
    command = Object.assign({}, command || {});
    if (state.payload.recordKey && command.recordKey == null) {
      command.recordKey = state.payload.recordKey;
    }
    if (state.payload.revision != null && command.revision == null) {
      command.revision = state.payload.revision;
    }
    return command;
  }

  function sendCommand(command) {
    try {
      postBridgeMessage(prepareCommand(command));
    } catch (error) {
      showError(error);
    }
  }

  function flushPendingEditCommand() {
    if (state.editSaveTimer) {
      window.clearTimeout(state.editSaveTimer);
      state.editSaveTimer = null;
    }
    if (!state.pendingEditCommand) {
      return;
    }
    var command = state.pendingEditCommand;
    state.pendingEditCommand = null;
    postBridgeMessage(command);
  }

  function scheduleContentChanged(command) {
    state.pendingEditCommand = prepareCommand(command);
    if (state.editSaveTimer) {
      window.clearTimeout(state.editSaveTimer);
    }
    state.editSaveTimer = window.setTimeout(flushPendingEditCommand, 500);
  }

  function emitSearchChanged(matchCount, index) {
    sendCommand({
      command: "searchChanged",
      matchCount: Math.max(0, Number(matchCount || 0)),
      index: Math.max(0, Number(index || 0))
    });
  }

  function scrollNode() {
    return document.scrollingElement || document.documentElement || document.body;
  }

  function isScrolledToTop() {
    var node = scrollNode();
    return !node || Number(node.scrollTop || 0) <= 1;
  }

  function isPageMeaningfullyScrollable() {
    var node = scrollNode();
    if (!node) {
      return false;
    }
    var overflow = Number(node.scrollHeight || 0) - Number(node.clientHeight || 0);
    return overflow > DETAIL_SCROLL_OVERFLOW_THRESHOLD;
  }

  function syncScrollState(force) {
    var node = scrollNode();
    if (!isPageMeaningfullyScrollable()) {
      if (node && Number(node.scrollTop || 0) > 0) {
        node.scrollTop = 0;
      }
      emitScrollState(true, Boolean(force));
      return;
    }
    emitScrollState(isScrolledToTop(), Boolean(force));
  }

  function emitScrollState(atTop, force) {
    var next = Boolean(atTop);
    if (!force && next === state.lastScrollAtTop) {
      return;
    }
    state.lastScrollAtTop = next;
    sendCommand({ command: "scrollState", atTop: next });
  }

  function handleScrollState() {
    if (!isPageMeaningfullyScrollable()) {
      var node = scrollNode();
      if (node && Number(node.scrollTop || 0) > 0) {
        node.scrollTop = 0;
      }
      emitScrollState(true, false);
      return;
    }
    emitScrollState(isScrolledToTop(), false);
  }

  function showError(error) {
    var panel = $("errorState");
    if (panel) {
      panel.hidden = false;
      panel.textContent = "详情渲染失败：" + (error && error.message ? error.message : String(error));
    }
    postBridgeMessage({ command: "renderError", message: panel ? panel.textContent : String(error) });
  }

  function setMode(mode) {
    var selected = mode === "timeline" || mode === "summary" ? mode : "transcript";
    var editing = Boolean(state.editMode) && selected !== "timeline";
    $("body-container").hidden = editing || selected === "timeline";
    $("timelinePanel").hidden = selected !== "timeline";
    $("editorPanel").hidden = !editing;
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

  function renderTimelineTokens(item) {
    var fragment = document.createDocumentFragment();
    var tokens = Array.isArray(item.tokens) ? item.tokens : [];
    if (!tokens.length) {
      fragment.appendChild(document.createTextNode(String(item.text || "")));
      return fragment;
    }
    tokens.forEach(function (token, tokenIndex) {
      token = token || {};
      var text = String(token.text || "");
      if (!text.trim()) {
        fragment.appendChild(document.createTextNode(text));
        return;
      }
      var span = document.createElement("span");
      span.className = "timeline-token";
      span.dataset.tokenIndex = String(tokenIndex);
      span.setAttribute("data-token-index", String(tokenIndex));
      span.dataset.start = String(token.start != null ? token.start : item.start || 0);
      span.dataset.end = String(token.end != null ? token.end : token.start || item.end || item.start || 0);
      span.textContent = text;
      fragment.appendChild(span);
    });
    return fragment;
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
      row.className = "timeline-entry";
      row.tabIndex = 0;
      row.dataset.itemIndex = String(i);
      row.dataset.segmentId = String(item.id != null ? item.id : i);
      row.dataset.start = String(item.start || 0);
      row.dataset.end = String(item.end || item.start || 0);

      var time = document.createElement("span");
      time.className = "timeline-range";
      time.textContent = secondsLabel(item.start) + " - " + secondsLabel(item.end);

      var text = document.createElement("span");
      text.className = "timeline-text";
      text.setAttribute("contenteditable", state.editMode ? "true" : "false");
      text.setAttribute("spellcheck", "false");
      renderTimelineText(text, item);
      text.addEventListener("input", emitTimelineChange);

      row.appendChild(time);
      row.appendChild(text);
      row.addEventListener("click", function (event) {
        if (state.editMode) {
          return;
        }
        var current = event.currentTarget;
        var target = event.target && event.target.closest ? event.target.closest(".timeline-token") : null;
        var seekSeconds = target && target.dataset
          ? Number(target.dataset.start || current.dataset.start || 0)
          : Number(current.dataset.start || 0);
        sendCommand({
          command: "seek",
          seconds: seekSeconds,
          segmentId: Number(current.dataset.segmentId)
        });
      });
      fragment.appendChild(row);
    }
    if (generation !== state.timelineRenderGeneration) {
      return;
    }
    list.appendChild(fragment);
    syncTimelineEditMode();
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
      return;
    }
    renderTimelineChunk(items, 0, generation);
  }

  function renderCurrentPayloadBody() {
    var mode = selectedMode();
    $("vx-content").innerHTML = mode === "timeline" ? "" : renderMarkdown(state.payload.content || "");
    if (mode === "timeline") {
      renderTimeline(state.payload.timeline || []);
    } else {
      state.timelineRenderGeneration += 1;
      clearTimeline();
    }
    bindLinks();
  }

  function setContent(payload) {
    try {
      flushPendingEditCommand();
      state.payload = payload && typeof payload === "object" ? payload : {};
      state.playback = state.payload.playback || state.playback || {};
      var selectedMode = state.payload.mode === "timeline" ? "timeline" : state.payload.mode === "summary" ? "summary" : "transcript";
      $("errorState").hidden = true;
      $("emptyState").hidden = true;
      $("contentPanel").hidden = false;
      renderCurrentPayloadBody();
      setMode(selectedMode);
      setEditMode({ enabled: state.editMode });
      if (state.editMode) {
        syncEditorText();
      }
      applySearchState();
      window.requestAnimationFrame(function () {
        syncScrollState(true);
      });
    } catch (error) {
      showError(error);
    }
  }

  function findActiveTimeline(position) {
    var rows = Array.prototype.slice.call(document.querySelectorAll(".timeline-entry[data-start]"));
    var current = null;
    var activeToken = null;
    rows.some(function (row) {
      var start = Number(row.dataset.start || 0);
      var end = Number(row.dataset.end || start);
      if (position >= start && position <= end) {
        current = row;
        var tokens = Array.prototype.slice.call(row.querySelectorAll(".timeline-token[data-start]"));
        tokens.some(function (token) {
          var tokenStart = Number(token.dataset.start || start);
          var tokenEnd = Number(token.dataset.end || tokenStart);
          if (position >= tokenStart && position <= Math.max(tokenStart, tokenEnd)) {
            activeToken = token;
            return true;
          }
          if (position >= tokenStart) {
            activeToken = token;
          }
          return false;
        });
        return true;
      }
      if (position >= start) {
        current = row;
      }
      return false;
    });
    return { row: current, activeToken: activeToken };
  }

  function currentViewportBottom() {
    return window.innerHeight || document.documentElement.clientHeight || 0;
  }

  var TIMELINE_PAGE_TOLERANCE = 2;

  function currentTimelineVisibleBottom() {
    return currentViewportBottom();
  }

  function timelineTextLineRects(text) {
    if (!text || typeof document.createRange !== "function") {
      return [];
    }
    var range = document.createRange();
    try {
      range.selectNodeContents(text);
      return Array.prototype.slice.call(range.getClientRects()).filter(function (rect) {
        return rect && rect.width > 0 && rect.height > 0;
      });
    } finally {
      if (typeof range.detach === "function") {
        range.detach();
      }
    }
  }

  function timelineContentRect(row) {
    if (!row || typeof row.querySelector !== "function") {
      return null;
    }
    var range = row.querySelector(".timeline-range");
    var text = row.querySelector(".timeline-text");
    var rects = [];
    if (range && typeof range.getBoundingClientRect === "function") {
      rects.push(range.getBoundingClientRect());
    }
    if (text) {
      var textRects = timelineTextLineRects(text);
      if (textRects.length) {
        rects = rects.concat(textRects);
      } else if (typeof text.getBoundingClientRect === "function") {
        rects.push(text.getBoundingClientRect());
      }
    }
    if (!rects.length) {
      return null;
    }
    return {
      top: Math.min.apply(null, rects.map(function (rect) { return rect.top; })),
      bottom: Math.max.apply(null, rects.map(function (rect) { return rect.bottom; }))
    };
  }

  function isAboveCurrentPage(row) {
    if (!row || typeof row.getBoundingClientRect !== "function") {
      return false;
    }
    var rect = timelineContentRect(row) || row.getBoundingClientRect();
    return rect.top < -TIMELINE_PAGE_TOLERANCE;
  }

  function isBelowCurrentPage(row) {
    if (!row || typeof row.getBoundingClientRect !== "function") {
      return false;
    }
    var rect = timelineContentRect(row) || row.getBoundingClientRect();
    return rect.bottom > currentTimelineVisibleBottom() + TIMELINE_PAGE_TOLERANCE;
  }

  function isFullyVisible(row) {
    if (!row || typeof row.getBoundingClientRect !== "function") {
      return false;
    }
    var rect = timelineContentRect(row) || row.getBoundingClientRect();
    return rect.top >= -TIMELINE_PAGE_TOLERANCE && rect.bottom <= currentTimelineVisibleBottom() + TIMELINE_PAGE_TOLERANCE;
  }

  function isOutsideCurrentPage(row) {
    return isAboveCurrentPage(row) || isBelowCurrentPage(row);
  }

  function scrollTimelinePage(target) {
    if (!target) {
      return;
    }
    target.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function updatePlayback(payload) {
    try {
      state.playback = payload && typeof payload === "object" ? payload : {};
      var position = Number(state.playback.positionSeconds || 0);
      var active = findActiveTimeline(Number.isFinite(position) ? position : 0);
      var row = active.row;
      var nextActiveId = row ? row.dataset.segmentId : null;
      var nextTokenIndex = active.activeToken ? active.activeToken.dataset.tokenIndex : "";
      var activeKey = nextActiveId + ":" + nextTokenIndex;
      if (activeKey === state.activeId) {
        return;
      }
      document.querySelectorAll(".timeline-entry.active").forEach(function (node) {
        node.classList.remove("active");
      });
      document.querySelectorAll(".timeline-token.active").forEach(function (node) {
        node.classList.remove("active");
      });
      state.activeId = activeKey;
      if (!row) {
        return;
      }
      row.classList.add("active");
      row.querySelectorAll(".timeline-token.active").forEach(function (node) {
        node.classList.remove("active");
      });
      if (active.activeToken) {
        active.activeToken.classList.add("active");
      }
      var scrollTarget = row;
      if (!isFullyVisible(scrollTarget) && isOutsideCurrentPage(scrollTarget)) {
        scrollTimelinePage(scrollTarget);
      }
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

  function initEditor() {
    var editor = $("editorPanel");
    if (editor) {
      editor.addEventListener("input", emitEditorChange);
    }
  }

  window.NoisNoteDetail = {
    setContent: setContent,
    setEditMode: setEditMode,
    setSearchState: setSearchState,
    updatePlayback: updatePlayback,
    sendCommand: sendCommand
  };

  window.addEventListener("scroll", handleScrollState, { passive: true });
  document.addEventListener("DOMContentLoaded", function () {
    initEditor();
    initBridge();
  });
}());
