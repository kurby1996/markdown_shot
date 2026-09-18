// Markdown Video Course Note Assistant - WYSIWYG Visual Editor (Youdao / Typora style)
const App = {
  state: {
    config: {},
    hotkeyStatus: {},
    targetMdPath: '',
    imageSaveDir: '',
    theme: localStorage.getItem('md_snip_theme') || 'dark',
    activeSettingsTab: 'hotkey',
    recordingAction: null,
    isSaving: false,
    autoSaveTimer: null,
    lastSavedMarkdown: '',
    zoomImageSrc: null,
    turndownService: null
  },

  init() {
    this.initTurndown();
    this.applyTheme(this.state.theme);
    this.bindDOMEvents();
    this.fetchConfig();
    this.fetchMarkdown();
    this.initSSE();
  },

  initTurndown() {
    if (window.TurndownService) {
      this.state.turndownService = new TurndownService({
        headingStyle: 'atx',
        hr: '---',
        bulletListMarker: '-',
        codeBlockStyle: 'fenced'
      });

      // Custom rule for images with data-rel-src
      this.state.turndownService.addRule('customImage', {
        filter: 'img',
        replacement: function (content, node) {
          const relSrc = node.getAttribute('data-rel-src') || node.getAttribute('src') || '';
          const alt = node.getAttribute('alt') || '';
          return `\n\n![${alt}](${relSrc})\n\n`;
        }
      });
    }
  },

  applyTheme(theme) {
    this.state.theme = theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('md_snip_theme', theme);
    const themeBtn = document.getElementById('theme-toggle-btn');
    if (themeBtn) {
      themeBtn.innerHTML = theme === 'dark' ? '☀️' : '🌙';
    }
  },

  toggleTheme() {
    this.applyTheme(this.state.theme === 'dark' ? 'light' : 'dark');
  },

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  },

  async fetchConfig() {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.config = data.config;
        this.state.hotkeyStatus = data.hotkey_status;
        this.state.targetMdPath = data.target_md_path;
        this.state.imageSaveDir = data.image_save_dir;
        this.renderHeaderInfo();
        this.renderSettingsForm();
      }
    } catch (e) {
      console.error('Fetch config failed', e);
    }
  },

  async fetchMarkdown(silent = false, scrollToBottom = false) {
    try {
      const res = await fetch('/api/markdown');
      const data = await res.json();
      if (data.status === 'ok') {
        const mdText = data.content || '';
        
        // Only re-render if content changed on disk or first load
        if (mdText !== this.state.lastSavedMarkdown || this.state.lastSavedMarkdown === '') {
          this.state.lastSavedMarkdown = mdText;
          this.renderMarkdownToVisualEditor(mdText, scrollToBottom);
        }
        
        this.updateStats();
      }
    } catch (e) {
      if (!silent) console.error('Fetch markdown failed', e);
    }
  },

  initSSE() {
    try {
      const sse = new EventSource('/api/events');
      sse.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'screenshot_added') {
            const captureData = payload.data;
            this.showToast(`📸 截图已直接插入到文档中`, 'success');
            
            // Insert image element directly into WYSIWYG editor
            this.insertScreenshotElement(captureData.rel_path, captureData.filename);
          } else if (payload.type === 'error') {
            this.showToast(`错误: ${payload.data.message}`, 'error');
          }
        } catch (err) {
          console.error('SSE parse error', err);
        }
      };
      sse.onerror = () => {};
    } catch (e) {
      console.warn('SSE not supported', e);
    }
  },

  renderHeaderInfo() {
    const filename = this.state.targetMdPath ? this.state.targetMdPath.split(/[\/\\]/).pop() : '未选择文档';
    const targetTag = document.getElementById('current-target-path');
    if (targetTag) {
      targetTag.textContent = filename;
      targetTag.title = `完整路径: ${this.state.targetMdPath}`;
    }

    const hotkeys = this.state.config.hotkeys || {};
    const hotkeyText = `选区: ${hotkeys.snip_region || 'Alt+Q'} | 全屏: ${hotkeys.snip_fullscreen || 'F9'}`;
    const hotkeyEl = document.getElementById('header-hotkeys-text');
    if (hotkeyEl) {
      hotkeyEl.textContent = hotkeyText;
    }

    // Populate recent files dropdown
    const recentSelect = document.getElementById('recent-files-select');
    if (recentSelect && this.state.config.recent_files) {
      let opts = '<option value="">🕒 快速切换最近文档...</option>';
      this.state.config.recent_files.forEach(f => {
        const fname = f.split(/[\/\\]/).pop();
        const selected = (f === this.state.targetMdPath) ? 'selected' : '';
        opts += `<option value="${f}" ${selected}>📄 ${fname}</option>`;
      });
      recentSelect.innerHTML = opts;
    }
  },

  // Markdown -> HTML into Visual ContentEditable Canvas
  renderMarkdownToVisualEditor(rawMd, scrollToBottom = false) {
    const editor = document.getElementById('wysiwyg-editor');
    if (!editor) return;

    const container = document.getElementById('wysiwyg-scroll-container');
    const prevScrollTop = container ? container.scrollTop : 0;

    let html = '';
    if (window.marked) {
      const renderer = new marked.Renderer();
      renderer.image = function (href, title, text) {
        const src = typeof href === 'object' ? href.href : href;
        const alt = typeof href === 'object' ? (href.text || '') : (text || '');
        const imgTitle = typeof href === 'object' ? (href.title || '') : (title || '');
        
        let previewSrc = src;
        if (src && !src.startsWith('http://') && !src.startsWith('https://') && !src.startsWith('data:')) {
          previewSrc = `/api/image-preview?path=${encodeURIComponent(src)}`;
        }
        return `<p><img src="${previewSrc}" data-rel-src="${src}" alt="${alt}" title="${imgTitle}" onclick="App.zoomImage('${previewSrc}')" /></p>`;
      };
      marked.setOptions({ renderer: renderer, breaks: true, gfm: true });
      html = marked.parse(rawMd);
    } else {
      html = rawMd.replace(/\n/g, '<br/>');
    }

    editor.innerHTML = html || '<p><br></p>';

    if (container) {
      if (scrollToBottom) {
        setTimeout(() => {
          container.scrollTop = container.scrollHeight;
        }, 50);
      } else if (prevScrollTop > 0) {
        container.scrollTop = prevScrollTop;
      }
    }

    this.updateStats();
  },

  // Directly insert screenshot into WYSIWYG editor
  insertScreenshotElement(relPath, filename) {
    const editor = document.getElementById('wysiwyg-editor');
    if (!editor) return;

    const previewSrc = `/api/image-preview?path=${encodeURIComponent(relPath)}`;

    // Create image element block
    const imgP = document.createElement('p');
    const img = document.createElement('img');
    img.src = previewSrc;
    img.setAttribute('data-rel-src', relPath);
    img.alt = filename;
    img.onclick = () => App.zoomImage(previewSrc);
    imgP.appendChild(img);

    // Empty paragraph after image for immediate typing
    const nextP = document.createElement('p');
    nextP.innerHTML = '<br>';

    editor.appendChild(imgP);
    editor.appendChild(nextP);

    // Smoothly scroll down
    const container = document.getElementById('wysiwyg-scroll-container');
    if (container) {
      setTimeout(() => {
        container.scrollTop = container.scrollHeight;
      }, 50);
    }

    // Set cursor to the empty paragraph right below the new image
    const selection = window.getSelection();
    const range = document.createRange();
    range.setStart(nextP, 0);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    editor.focus();

    // Auto save
    this.saveMarkdownContent(true);
    this.updateStats();
  },

  // Convert HTML from ContentEditable back to standard clean Markdown
  htmlToMarkdown(html) {
    if (this.state.turndownService) {
      try {
        return this.state.turndownService.turndown(html);
      } catch (e) {
        console.warn('Turndown error, using fallback:', e);
      }
    }

    // Robust Fallback Converter
    const div = document.createElement('div');
    div.innerHTML = html;

    let md = '';
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return '';

      const tag = node.tagName.toLowerCase();
      let children = '';
      node.childNodes.forEach(child => {
        children += walk(child);
      });

      switch (tag) {
        case 'h1': return `\n# ${children.trim()}\n\n`;
        case 'h2': return `\n## ${children.trim()}\n\n`;
        case 'h3': return `\n### ${children.trim()}\n\n`;
        case 'h4': return `\n#### ${children.trim()}\n\n`;
        case 'p': return `${children.trim()}\n\n`;
        case 'strong': case 'b': return `**${children}**`;
        case 'em': case 'i': return `*${children}*`;
        case 'strike': case 's': case 'del': return `~~${children}~~`;
        case 'code': return `\`${children}\``;
        case 'pre': return `\n\`\`\`\n${children.trim()}\n\`\`\`\n\n`;
        case 'blockquote': return `\n> ${children.trim()}\n\n`;
        case 'li': return `- ${children.trim()}\n`;
        case 'ul': case 'ol': return `\n${children}\n`;
        case 'hr': return `\n---\n\n`;
        case 'br': return `\n`;
        case 'img': {
          const rel = node.getAttribute('data-rel-src') || node.getAttribute('src') || '';
          const alt = node.getAttribute('alt') || '';
          return `\n\n![${alt}](${rel})\n\n`;
        }
        default: return children;
      }
    };

    return walk(div).trim() + '\n';
  },

  onEditorInput() {
    this.updateStats();

    // Mark as saving in progress
    const toolbarSave = document.getElementById('toolbar-auto-save');
    const toolbarText = document.getElementById('toolbar-save-text');
    if (toolbarSave && toolbarText) {
      toolbarSave.className = 'auto-save-indicator saving';
      toolbarText.textContent = '正在保存...';
    }

    const statusEl = document.getElementById('stat-save-status');
    if (statusEl) {
      statusEl.className = 'save-status-saving';
      statusEl.textContent = '● 正在保存...';
    }

    // Debounced Auto-save (600ms of typing inactivity)
    clearTimeout(this.state.autoSaveTimer);
    this.state.autoSaveTimer = setTimeout(() => {
      this.saveMarkdownContent(true);
    }, 600);
  },

  async saveMarkdownContent(isAutoSave = false) {
    const editor = document.getElementById('wysiwyg-editor');
    if (!editor) return;

    const html = editor.innerHTML;
    const mdContent = this.htmlToMarkdown(html);

    if (isAutoSave && mdContent === this.state.lastSavedMarkdown) {
      // Content unchanged
      this.updateAutoSaveStatusSaved();
      return;
    }

    try {
      const res = await fetch('/api/markdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: mdContent })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.lastSavedMarkdown = mdContent;
        this.updateAutoSaveStatusSaved();
        if (!isAutoSave) {
          this.showToast('文档已同步保存到 Markdown 文件', 'success');
        }
        this.updateStats();
      } else {
        if (!isAutoSave) this.showToast(data.message || '保存失败', 'error');
      }
    } catch (e) {
      if (!isAutoSave) this.showToast('保存出错: ' + e, 'error');
    }
  },

  updateAutoSaveStatusSaved() {
    const toolbarSave = document.getElementById('toolbar-auto-save');
    const toolbarText = document.getElementById('toolbar-save-text');
    if (toolbarSave && toolbarText) {
      toolbarSave.className = 'auto-save-indicator saved';
      toolbarText.textContent = '实时已自动保存';
    }

    const statusEl = document.getElementById('stat-save-status');
    if (statusEl) {
      statusEl.className = 'save-status-saved';
      statusEl.textContent = '● 实时已自动保存';
    }
  },

  updateStats() {
    const editor = document.getElementById('wysiwyg-editor');
    if (!editor) return;

    const text = editor.innerText || '';
    const charCount = text.replace(/\s/g, '').length;
    const imgCount = editor.querySelectorAll('img').length;

    const statWords = document.getElementById('stat-words');
    if (statWords) statWords.textContent = `字符: ${charCount}`;

    const statScreenshots = document.getElementById('stat-screenshots');
    if (statScreenshots) statScreenshots.textContent = `📸 截图: ${imgCount} 张`;
  },

  scrollToStart() {
    this.scrollToEdge(true);
  },

  scrollToEnd() {
    this.scrollToEdge(false);
  },

  scrollToEdge(toStart) {
    const container = document.getElementById('wysiwyg-scroll-container');
    const editor = document.getElementById('wysiwyg-editor');

    if (editor) {
      try {
        editor.focus({ preventScroll: true });
      } catch (e) {
        editor.focus();
      }
      const selection = window.getSelection();
      if (selection) {
        const range = document.createRange();
        range.selectNodeContents(editor);
        range.collapse(toStart);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }

    if (!container) return;

    const applyScroll = () => {
      const top = toStart ? 0 : container.scrollHeight;
      container.style.scrollBehavior = 'auto';
      container.scrollTop = top;
      container.style.scrollBehavior = '';
    };

    applyScroll();
    requestAnimationFrame(applyScroll);
    setTimeout(applyScroll, 0);
  },

  async triggerCapture(type) {
    try {
      this.showToast(`正在启动${type === 'region' ? '选区截图 (Alt+Q)' : '全屏秒截 (F9)'}...`, 'info');
      const res = await fetch(`/api/capture/${type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: '' })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        if (type !== 'region') {
          this.showToast('截图已完成并插入文档', 'success');
        }
      } else {
        this.showToast(data.message || '截图失败', 'error');
      }
    } catch (e) {
      this.showToast('截图请求失败: ' + e, 'error');
    }
  },

  async pickTargetFile() {
    try {
      this.showToast('正在打开系统文件选择弹窗...', 'info');
      const res = await fetch('/api/file/pick', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.targetMdPath = data.path;
        this.state.lastSavedMarkdown = '';
        this.fetchConfig();
        this.fetchMarkdown();
        this.showToast(`已切换目标文档: ${data.filename}`, 'success');
      }
    } catch (e) {
      this.showToast('选择文件出错: ' + e, 'error');
    }
  },

  async pickImageDir() {
    try {
      this.showToast('正在打开系统目录选择弹窗...', 'info');
      const res = await fetch('/api/file/pick-dir', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.imageSaveDir = data.path;
        const customField = document.getElementById('cfg-custom-img-folder');
        if (customField) customField.value = data.path;
        this.showToast(`已设置图片存放目录: ${data.path}`, 'success');
      }
    } catch (e) {
      this.showToast('选择目录出错: ' + e, 'error');
    }
  },

  async selectRecentFile(path) {
    if (!path) return;
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_md_path: path })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.targetMdPath = path;
        this.state.lastSavedMarkdown = '';
        this.state.config = data.config;
        this.renderHeaderInfo();
        this.fetchMarkdown();
        this.showToast(`已切换至: ${path.split(/[\/\\]/).pop()}`, 'success');
      } else {
        this.showToast(data.message || '切换失败', 'error');
      }
    } catch (e) {
      this.showToast('切换文件出错: ' + e, 'error');
    }
  },

  async openInFolder(target = 'md', path = '') {
    try {
      const res = await fetch('/api/file/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target, path })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.showToast('已在 Windows 文件资源管理器中定位', 'info');
      } else {
        this.showToast(data.message || '打开失败', 'error');
      }
    } catch (e) {
      this.showToast('打开失败: ' + e, 'error');
    }
  },

  async openInEditor() {
    try {
      const res = await fetch('/api/file/open-editor', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        this.showToast('已在系统默认编辑器中打开文档', 'success');
      } else {
        this.showToast(data.message || '打开失败', 'error');
      }
    } catch (e) {
      this.showToast('打开失败: ' + e, 'error');
    }
  },

  zoomImage(src) {
    this.state.zoomImageSrc = src;
    const modal = document.getElementById('zoom-modal');
    const img = document.getElementById('zoom-modal-img');
    if (modal && img) {
      img.src = src;
      modal.style.display = 'flex';
    }
  },

  closeZoomModal() {
    const modal = document.getElementById('zoom-modal');
    if (modal) modal.style.display = 'none';
  },

  // Settings
  openSettings() {
    this.renderSettingsForm();
    document.getElementById('settings-modal').style.display = 'flex';
  },

  closeSettings() {
    this.stopRecordingKey();
    document.getElementById('settings-modal').style.display = 'none';
  },

  switchSettingsTab(tab) {
    this.state.activeSettingsTab = tab;
    document.querySelectorAll('.settings-tab-btn').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    document.querySelectorAll('.settings-tab-pane').forEach(p => {
      p.style.display = p.id === `tab-pane-${tab}` ? 'flex' : 'none';
    });
  },

  renderSettingsForm() {
    const cfg = this.state.config;
    if (!cfg) return;

    const inputMd = document.getElementById('cfg-target-md');
    if (inputMd) inputMd.value = cfg.target_md_path || '';

    const modeSelect = document.getElementById('cfg-img-mode');
    if (modeSelect) modeSelect.value = cfg.image_folder_mode || 'relative';

    const customFolderRow = document.getElementById('custom-img-folder-row');
    if (customFolderRow) {
      customFolderRow.style.display = (cfg.image_folder_mode === 'custom') ? 'flex' : 'none';
    }
    const customFolderInput = document.getElementById('cfg-custom-img-folder');
    if (customFolderInput) customFolderInput.value = cfg.custom_image_folder || '';

    const imgNameInput = document.getElementById('cfg-img-folder-name');
    if (imgNameInput) imgNameInput.value = cfg.image_folder_name || 'assets';

    const imgPrefixInput = document.getElementById('cfg-img-prefix');
    if (imgPrefixInput) imgPrefixInput.value = cfg.image_prefix || 'course_';

    const imgFormatSelect = document.getElementById('cfg-img-format');
    if (imgFormatSelect) imgFormatSelect.value = cfg.image_format || 'png';

    const hotkeys = cfg.hotkeys || {};
    document.getElementById('key-badge-region').textContent = hotkeys.snip_region || '未设置';
    document.getElementById('key-badge-fullscreen').textContent = hotkeys.snip_fullscreen || '未设置';
    document.getElementById('key-badge-window').textContent = hotkeys.snip_active_window || '未设置';

    const chkClipboard = document.getElementById('cfg-auto-clipboard');
    if (chkClipboard) chkClipboard.checked = !!cfg.auto_clipboard_watch;

    const chkSound = document.getElementById('cfg-play-sound');
    if (chkSound) chkSound.checked = !!cfg.play_sound;

    const chkNotify = document.getElementById('cfg-notify');
    if (chkNotify) chkNotify.checked = !!cfg.desktop_notification;
  },

  async saveSettings() {
    const updated = {
      target_md_path: document.getElementById('cfg-target-md').value.trim(),
      image_folder_mode: document.getElementById('cfg-img-mode').value,
      image_folder_name: document.getElementById('cfg-img-folder-name').value.trim(),
      custom_image_folder: document.getElementById('cfg-custom-img-folder').value.trim(),
      image_prefix: document.getElementById('cfg-img-prefix').value.trim(),
      image_format: document.getElementById('cfg-img-format').value,
      auto_clipboard_watch: document.getElementById('cfg-auto-clipboard').checked,
      play_sound: document.getElementById('cfg-play-sound').checked,
      desktop_notification: document.getElementById('cfg-notify').checked,
      hotkeys: {
        snip_region: document.getElementById('key-badge-region').textContent.trim(),
        snip_fullscreen: document.getElementById('key-badge-fullscreen').textContent.trim(),
        snip_active_window: document.getElementById('key-badge-window').textContent.trim()
      }
    };

    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated)
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.config = data.config;
        this.state.hotkeyStatus = data.hotkey_status;
        this.state.targetMdPath = data.target_md_path;
        this.renderHeaderInfo();
        this.showToast('配置已保存并生效', 'success');
        this.closeSettings();
        this.fetchMarkdown();
      } else {
        this.showToast(data.message || '保存配置失败', 'error');
      }
    } catch (e) {
      this.showToast('保存配置出错: ' + e, 'error');
    }
  },

  startRecordingKey(action) {
    this.state.recordingAction = action;
    const badgeMap = {
      'snip_region': 'key-badge-region',
      'snip_fullscreen': 'key-badge-fullscreen',
      'snip_active_window': 'key-badge-window'
    };
    const badge = document.getElementById(badgeMap[action]);
    if (badge) {
      badge.textContent = '请按下快捷键...';
      badge.classList.add('recording');
    }
  },

  stopRecordingKey() {
    this.state.recordingAction = null;
    document.querySelectorAll('.key-badge').forEach(b => b.classList.remove('recording'));
  },

  openNewFileModal() {
    document.getElementById('new-file-modal').style.display = 'flex';
    document.getElementById('new-file-title').value = '';
    document.getElementById('new-file-title').focus();
  },

  closeNewFileModal() {
    document.getElementById('new-file-modal').style.display = 'none';
  },

  async createNewFile() {
    const title = document.getElementById('new-file-title').value.trim();
    if (!title) {
      this.showToast('请输入笔记标题', 'error');
      return;
    }
    try {
      const res = await fetch('/api/file/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.closeNewFileModal();
        this.state.targetMdPath = data.path;
        this.state.lastSavedMarkdown = '';
        this.fetchConfig();
        this.fetchMarkdown();
        this.showToast(`新课程笔记创建成功: ${data.filename}`, 'success');
      } else {
        this.showToast(data.message || '创建失败', 'error');
      }
    } catch (e) {
      this.showToast('创建失败: ' + e, 'error');
    }
  },

  // =========================================================
  // WYSIWYG VISUAL FORMATTING ACTIONS (YOUDAO NOTE STYLE)
  // =========================================================
  wysiwyg: {
    getEditor() {
      return document.getElementById('wysiwyg-editor');
    },

    exec(command, value = null) {
      document.execCommand(command, false, value);
      App.onEditorInput();
    },

    formatHeading(tag) {
      const editor = this.getEditor();
      if (!editor) return;

      if (tag === 'p') {
        document.execCommand('formatBlock', false, '<p>');
      } else {
        document.execCommand('formatBlock', false, `<${tag}>`);
      }

      // Sync select dropdown
      const select = document.getElementById('block-format-select');
      if (select) select.value = tag;

      App.onEditorInput();
    },

    insertBlockquote() {
      document.execCommand('formatBlock', false, '<blockquote>');
      App.onEditorInput();
    },

    insertInlineCode() {
      const selection = window.getSelection();
      if (!selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      const selectedText = range.toString() || 'code';

      const codeEl = document.createElement('code');
      codeEl.textContent = selectedText;

      range.deleteContents();
      range.insertNode(codeEl);

      // Move cursor after code element
      range.setStartAfter(codeEl);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);

      App.onEditorInput();
    },

    insertCodeBlock() {
      const selection = window.getSelection();
      if (!selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      const selectedText = range.toString() || '// 在此输入代码';

      const pre = document.createElement('pre');
      const code = document.createElement('code');
      code.textContent = selectedText;
      pre.appendChild(code);

      range.deleteContents();
      range.insertNode(pre);

      const p = document.createElement('p');
      p.innerHTML = '<br>';
      pre.parentNode.insertBefore(p, pre.nextSibling);

      App.onEditorInput();
    },

    insertTable() {
      const tableHtml = `
        <table>
          <thead>
            <tr><th>列标题 1</th><th>列标题 2</th><th>列标题 3</th></tr>
          </thead>
          <tbody>
            <tr><td>内容 1</td><td>内容 2</td><td>内容 3</td></tr>
            <tr><td>内容 4</td><td>内容 5</td><td>内容 6</td></tr>
          </tbody>
        </table>
        <p><br></p>
      `;
      document.execCommand('insertHTML', false, tableHtml);
      App.onEditorInput();
    },

    insertLink() {
      const selection = window.getSelection();
      const selectedText = selection ? selection.toString() : '';
      const url = prompt('请输入超链接 URL 地址:', 'https://');
      if (url) {
        if (selectedText) {
          document.execCommand('createLink', false, url);
        } else {
          document.execCommand('insertHTML', false, `<a href="${url}" target="_blank">${url}</a>`);
        }
        App.onEditorInput();
      }
    }
  },

  bindDOMEvents() {
    const editor = document.getElementById('wysiwyg-editor');
    if (editor) {
      editor.addEventListener('input', () => this.onEditorInput());
      editor.addEventListener('blur', () => this.saveMarkdownContent(true));
      window.addEventListener('beforeunload', () => this.saveMarkdownContent(true));
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
          this.saveMarkdownContent(true);
        }
      });

      // Rich Keyboard Shortcuts (Ctrl+1~4, Ctrl+B, Ctrl+I, Ctrl+S)
      editor.addEventListener('keydown', (e) => {
        const isCmdOrCtrl = e.ctrlKey || e.metaKey;

        if (isCmdOrCtrl) {
          // Ctrl + 1 (H1)
          if (e.key === '1') {
            e.preventDefault();
            this.wysiwyg.formatHeading('h1');
            return;
          }
          // Ctrl + 2 (H2)
          if (e.key === '2') {
            e.preventDefault();
            this.wysiwyg.formatHeading('h2');
            return;
          }
          // Ctrl + 3 (H3)
          if (e.key === '3') {
            e.preventDefault();
            this.wysiwyg.formatHeading('h3');
            return;
          }
          // Ctrl + 4 (H4)
          if (e.key === '4') {
            e.preventDefault();
            this.wysiwyg.formatHeading('h4');
            return;
          }
          // Ctrl + 0 (Paragraph)
          if (e.key === '0') {
            e.preventDefault();
            this.wysiwyg.formatHeading('p');
            return;
          }

          // Ctrl + B (Bold)
          if (e.key === 'b' || e.key === 'B') {
            e.preventDefault();
            this.wysiwyg.exec('bold');
            return;
          }

          // Ctrl + I (Italic)
          if (e.key === 'i' || e.key === 'I') {
            e.preventDefault();
            this.wysiwyg.exec('italic');
            return;
          }

          // Ctrl + K (Link)
          if (e.key === 'k' || e.key === 'K') {
            e.preventDefault();
            this.wysiwyg.insertLink();
            return;
          }

          // Ctrl + Q (Blockquote)
          if (e.key === 'q' || e.key === 'Q') {
            e.preventDefault();
            this.wysiwyg.insertBlockquote();
            return;
          }

          // Ctrl + E (Inline Code)
          if (e.key === 'e' || e.key === 'E') {
            e.preventDefault();
            this.wysiwyg.insertInlineCode();
            return;
          }

          // Ctrl + U (Bullet List)
          if (e.key === 'u' || e.key === 'U') {
            e.preventDefault();
            this.wysiwyg.exec('insertUnorderedList');
            return;
          }

          // Ctrl + O (Ordered List)
          if (e.key === 'o' || e.key === 'O') {
            e.preventDefault();
            this.wysiwyg.exec('insertOrderedList');
            return;
          }

          // Ctrl + Shift + C (Code block)
          if (e.shiftKey && (e.key === 'c' || e.key === 'C')) {
            e.preventDefault();
            this.wysiwyg.insertCodeBlock();
            return;
          }

          // Ctrl + Shift + T (Table)
          if (e.shiftKey && (e.key === 't' || e.key === 'T')) {
            e.preventDefault();
            this.wysiwyg.insertTable();
            return;
          }

          // Ctrl + Shift + X (Strikethrough)
          if (e.shiftKey && (e.key === 'x' || e.key === 'X')) {
            e.preventDefault();
            this.wysiwyg.exec('strikeThrough');
            return;
          }

          // Ctrl + S (Save)
          if (e.key === 's' || e.key === 'S') {
            e.preventDefault();
            this.saveMarkdownContent(false);
            return;
          }

          // Ctrl + Home (Jump to document start)
          if (e.key === 'Home') {
            e.preventDefault();
            this.scrollToStart();
            return;
          }

          // Ctrl + End (Jump to document end)
          if (e.key === 'End') {
            e.preventDefault();
            this.scrollToEnd();
            return;
          }
        }

        // Tab indentation
        if (e.key === 'Tab') {
          e.preventDefault();
          document.execCommand('insertText', false, '  ');
          this.onEditorInput();
        }
      });
    }

    // Global Key Listener for Hotkey Recording in Settings
    window.addEventListener('keydown', (e) => {
      if (!this.state.recordingAction) {
        if ((e.ctrlKey || e.metaKey) && (e.key === 'End' || e.key === 'Home')) {
          const tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
          if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') {
            e.preventDefault();
            if (e.key === 'Home') this.scrollToStart();
            else this.scrollToEnd();
          }
        }
        return;
      }

      e.preventDefault();
      e.stopPropagation();

      if (e.key === 'Escape') {
        this.stopRecordingKey();
        this.renderSettingsForm();
        return;
      }

      const keys = [];
      if (e.ctrlKey) keys.push('Ctrl');
      if (e.altKey) keys.push('Alt');
      if (e.shiftKey) keys.push('Shift');
      if (e.metaKey) keys.push('Win');

      let mainKey = e.key;
      if (['Control', 'Alt', 'Shift', 'Meta'].includes(mainKey)) return;

      if (mainKey.startsWith('Key')) mainKey = mainKey.slice(3);
      if (mainKey.startsWith('Digit')) mainKey = mainKey.slice(5);

      keys.push(mainKey.toUpperCase());
      const hotkeyStr = keys.join('+');

      const badgeMap = {
        'snip_region': 'key-badge-region',
        'snip_fullscreen': 'key-badge-fullscreen',
        'snip_active_window': 'key-badge-window'
      };

      const badge = document.getElementById(badgeMap[this.state.recordingAction]);
      if (badge) {
        badge.textContent = hotkeyStr;
        badge.classList.remove('recording');
      }

      this.state.recordingAction = null;
    });

    const modeSelect = document.getElementById('cfg-img-mode');
    if (modeSelect) {
      modeSelect.addEventListener('change', (e) => {
        const row = document.getElementById('custom-img-folder-row');
        if (row) row.style.display = (e.target.value === 'custom') ? 'flex' : 'none';
      });
    }
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
