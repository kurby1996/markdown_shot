// App State & Core Logic
const App = {
  state: {
    config: {},
    hotkeyStatus: {},
    targetMdPath: '',
    imageSaveDir: '',
    captures: [],
    markdownContent: '',
    activeDocTab: 'preview', // 'preview' or 'source'
    theme: localStorage.getItem('md_snip_theme') || 'dark',
    activeSettingsTab: 'target',
    recordingAction: null,
    recordedKeys: [],
    isSavingDoc: false,
    autoScrollBottom: true,
    zoomImageSrc: null,
    showSettingsModal: false,
    showNewFileModal: false,
    newFileTitle: '',
    newFilePath: ''
  },

  init() {
    this.applyTheme(this.state.theme);
    this.bindDOMEvents();
    this.fetchConfig();
    this.fetchMarkdown();
    this.fetchCaptures();
    this.initSSE();
    
    // Auto sync markdown periodically
    setInterval(() => {
      if (this.state.activeDocTab === 'preview') {
        this.fetchMarkdown(true);
      }
    }, 4000);
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

  async fetchMarkdown(silent = false) {
    try {
      const res = await fetch('/api/markdown');
      const data = await res.json();
      if (data.status === 'ok') {
        // Only update if source tab is not dirty or in preview mode
        if (this.state.activeDocTab === 'preview' || this.state.markdownContent === '') {
          this.state.markdownContent = data.content;
          this.renderMarkdownView();
        }
        document.getElementById('doc-screenshot-count').textContent = `${data.screenshot_count} 张截图`;
      }
    } catch (e) {
      if (!silent) console.error('Fetch markdown failed', e);
    }
  },

  async fetchCaptures() {
    try {
      const res = await fetch('/api/captures?limit=30');
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.captures = data.captures;
        this.renderCaptureFeed();
      }
    } catch (e) {
      console.error('Fetch captures failed', e);
    }
  },

  initSSE() {
    try {
      const sse = new EventSource('/api/events');
      sse.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'screenshot_added') {
            this.showToast(`📸 截图已成功追加到 MD 文档`, 'success');
            this.fetchCaptures();
            this.fetchMarkdown();
          } else if (payload.type === 'error') {
            this.showToast(`错误: ${payload.data.message}`, 'error');
          }
        } catch (err) {
          console.error('SSE parse error', err);
        }
      };
      sse.onerror = () => {
        // SSE will reconnect automatically
      };
    } catch (e) {
      console.warn('SSE not supported or failed', e);
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
    const hotkeyText = `选区: ${hotkeys.snip_region || '无'} | 全屏: ${hotkeys.snip_fullscreen || '无'} | 窗口: ${hotkeys.snip_active_window || '无'}`;
    const hotkeyEl = document.getElementById('header-hotkeys-text');
    if (hotkeyEl) {
      hotkeyEl.textContent = hotkeyText;
    }

    // Populate recent files dropdown on top bar
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

  renderCaptureFeed() {
    const feed = document.getElementById('capture-feed');
    if (!feed) return;

    if (!this.state.captures || this.state.captures.length === 0) {
      feed.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">🖼️</div>
          <p style="font-weight: 600;">暂无截图记录</p>
          <p style="font-size: 13px;">按下快捷键 <span class="key-badge">${this.state.config.hotkeys?.snip_region || 'Alt+Q'}</span> 即可开始截取视频画面并自动追加到 Markdown！</p>
        </div>
      `;
      return;
    }

    feed.innerHTML = this.state.captures.map((item, idx) => {
      const previewUrl = `/api/image-preview?path=${encodeURIComponent(item.rel_path)}`;
      return `
        <div class="capture-card" data-filename="${item.filename}">
          <div class="card-img-wrapper" onclick="App.zoomImage('${previewUrl}')">
            <img src="${previewUrl}" alt="${item.filename}" loading="lazy" />
            <div class="img-badge-info">${item.dimensions || ''} · ${item.size || ''}</div>
          </div>
          <div class="card-body">
            <div class="card-meta">
              <span style="font-weight: 600; color: var(--accent-light);">#${this.state.captures.length - idx} ${item.filename}</span>
              <span>🕒 ${item.timestamp}</span>
            </div>
            <div class="card-note-box">
              <input type="text" class="card-note-input" placeholder="输入备注并回车更新..." value="${item.note || ''}" onkeydown="if(event.key==='Enter') App.updateNote('${item.filename}', this.value)" />
              <button class="btn btn-secondary btn-sm" onclick="App.updateNote('${item.filename}', this.previousElementSibling.value)">💾 备注</button>
            </div>
            <div class="card-actions">
              <button class="btn btn-secondary btn-sm" onclick="App.copyMarkdownLink('${item.rel_path}', '${item.filename}')" title="复制 Markdown 引用链接">📋 复制链接</button>
              <button class="btn btn-secondary btn-sm" onclick="App.openInFolder('image', '${item.abs_path}')" title="在文件夹中显示图片">📂 文件夹</button>
            </div>
          </div>
        </div>
      `;
    }).join('');
  },

  renderMarkdownView() {
    const previewContainer = document.getElementById('markdown-preview');
    const editorTextarea = document.getElementById('markdown-editor');

    if (editorTextarea) {
      editorTextarea.value = this.state.markdownContent;
    }

    if (previewContainer) {
      // Process custom image preview urls in markdown
      let rawMd = this.state.markdownContent;
      
      // Parse markdown with marked
      let html = '';
      if (window.marked) {
        // Custom image renderer for marked
        const renderer = new marked.Renderer();
        renderer.image = function(href, title, text) {
          // Check if marked passed an object (marked v4+) or string
          const src = typeof href === 'object' ? href.href : href;
          const alt = typeof href === 'object' ? (href.text || '') : (text || '');
          const imgTitle = typeof href === 'object' ? (href.title || '') : (title || '');
          
          let previewSrc = src;
          if (src && !src.startsWith('http://') && !src.startsWith('https://') && !src.startsWith('data:')) {
            previewSrc = `/api/image-preview?path=${encodeURIComponent(src)}`;
          }
          return `<div class="img-render-container"><img src="${previewSrc}" alt="${alt}" title="${imgTitle}" onclick="App.zoomImage('${previewSrc}')" loading="lazy" /></div>`;
        };
        marked.setOptions({ renderer: renderer, breaks: true, gfm: true });
        html = marked.parse(rawMd);
      } else {
        // Simple fallback parser
        html = rawMd.replace(/\n/g, '<br/>');
      }

      previewContainer.innerHTML = html;

      if (this.state.autoScrollBottom && this.state.activeDocTab === 'preview') {
        const docView = document.getElementById('doc-view-container');
        if (docView) {
          docView.scrollTop = docView.scrollHeight;
        }
      }
    }
  },

  switchDocTab(tab) {
    this.state.activeDocTab = tab;
    document.getElementById('tab-preview-btn').classList.toggle('active', tab === 'preview');
    document.getElementById('tab-source-btn').classList.toggle('active', tab === 'source');
    
    document.getElementById('markdown-preview').style.display = tab === 'preview' ? 'block' : 'none';
    document.getElementById('markdown-editor-wrapper').style.display = tab === 'source' ? 'block' : 'none';

    if (tab === 'preview') {
      this.state.markdownContent = document.getElementById('markdown-editor').value;
      this.renderMarkdownView();
    }
  },

  async saveMarkdownContent() {
    const editor = document.getElementById('markdown-editor');
    const content = editor.value;
    try {
      const res = await fetch('/api/markdown', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.markdownContent = content;
        this.showToast('Markdown 文档已保存', 'success');
        this.renderMarkdownView();
      } else {
        this.showToast(data.message || '保存失败', 'error');
      }
    } catch (e) {
      this.showToast('保存失败: ' + e, 'error');
    }
  },

  async triggerCapture(type) {
    try {
      const note = document.getElementById('quick-note-text')?.value || '';
      let url = `/api/capture/${type}`;
      this.showToast(`正在启动${type === 'region' ? '选区截图' : type === 'fullscreen' ? '全屏截图' : '窗口截图'}...`, 'info');
      
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        if (type !== 'region') {
          this.showToast('截图已完成并存入 Markdown', 'success');
          if (document.getElementById('quick-note-text')) {
            document.getElementById('quick-note-text').value = '';
          }
          this.fetchCaptures();
          this.fetchMarkdown();
        }
      } else {
        this.showToast(data.message || '截图失败', 'error');
      }
    } catch (e) {
      this.showToast('截图请求失败: ' + e, 'error');
    }
  },

  async updateNote(filename, note) {
    try {
      const res = await fetch('/api/capture/update-note', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, note })
      });
      const data = await res.json();
      if (data.status === 'ok') {
        this.showToast('备注已同步更新到 Markdown 文档', 'success');
        this.fetchMarkdown();
        this.fetchCaptures();
      } else {
        this.showToast(data.message || '更新备注失败', 'error');
      }
    } catch (e) {
      this.showToast('网络错误: ' + e, 'error');
    }
  },

  async pickTargetFile() {
    try {
      this.showToast('正在打开系统文件选择窗口...', 'info');
      const res = await fetch('/api/file/pick', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.targetMdPath = data.path;
        this.fetchConfig();
        this.fetchMarkdown();
        this.fetchCaptures();
        this.showToast(`已切换目标文档: ${data.filename}`, 'success');
      }
    } catch (e) {
      this.showToast('选择文件出错: ' + e, 'error');
    }
  },

  async pickImageDir() {
    try {
      this.showToast('正在打开系统目录选择窗口...', 'info');
      const res = await fetch('/api/file/pick-dir', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') {
        this.state.imageSaveDir = data.path;
        document.getElementById('cfg-custom-img-folder').value = data.path;
        this.showToast(`已设置图片目录: ${data.path}`, 'success');
      }
    } catch (e) {
      this.showToast('选择目录出错: ' + e, 'error');
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
        this.showToast('已在文件管理器中定位', 'info');
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

  copyMarkdownLink(relPath, alt = '截图') {
    const text = `![${alt}](${relPath})`;
    navigator.clipboard.writeText(text).then(() => {
      this.showToast('已复制 Markdown 图片链接到剪贴板', 'success');
    }).catch(() => {
      this.showToast('复制失败，请手动复制', 'error');
    });
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

  // Settings Logic
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

    // Target MD
    const inputMd = document.getElementById('cfg-target-md');
    if (inputMd) inputMd.value = cfg.target_md_path || '';

    // Image save mode
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

    // Hotkeys
    const hotkeys = cfg.hotkeys || {};
    document.getElementById('key-badge-region').textContent = hotkeys.snip_region || '未设置';
    document.getElementById('key-badge-fullscreen').textContent = hotkeys.snip_fullscreen || '未设置';
    document.getElementById('key-badge-window').textContent = hotkeys.snip_active_window || '未设置';

    // Toggles
    const chkClipboard = document.getElementById('cfg-auto-clipboard');
    if (chkClipboard) chkClipboard.checked = !!cfg.auto_clipboard_watch;

    const chkSound = document.getElementById('cfg-play-sound');
    if (chkSound) chkSound.checked = !!cfg.play_sound;

    const chkNotify = document.getElementById('cfg-notify');
    if (chkNotify) chkNotify.checked = !!cfg.desktop_notification;

    // Template
    const tplTextarea = document.getElementById('cfg-template');
    if (tplTextarea) tplTextarea.value = cfg.markdown_template || '';

    // Recent files
    const recentList = document.getElementById('recent-files-list');
    if (recentList && cfg.recent_files) {
      recentList.innerHTML = cfg.recent_files.map(f => `
        <div class="recent-file-item" onclick="App.selectRecentFile('${f}')" style="display:flex; justify-content:space-between; padding:6px 10px; background:var(--bg-primary); border:1px solid var(--border-color); border-radius:6px; font-size:12px; cursor:pointer;">
          <span style="color:var(--accent-light); font-weight:600;">${f.split(/[\/\\]/).pop()}</span>
          <span style="color:var(--text-muted); max-width:280px; overflow:hidden; text-overflow:ellipsis;">${f}</span>
        </div>
      `).join('');
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
        this.state.config = data.config;
        this.renderHeaderInfo();
        this.fetchMarkdown();
        this.fetchCaptures();
        this.showToast(`已切换至文档: ${path.split(/[\/\\]/).pop()}`, 'success');
      } else {
        this.showToast(data.message || '切换失败', 'error');
      }
    } catch (e) {
      this.showToast('切换文件出错: ' + e, 'error');
    }
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
      markdown_template: document.getElementById('cfg-template').value,
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
        this.fetchCaptures();
      } else {
        this.showToast(data.message || '保存配置失败', 'error');
      }
    } catch (e) {
      this.showToast('保存配置出错: ' + e, 'error');
    }
  },

  // Interactive Hotkey Recording
  startRecordingKey(action) {
    this.state.recordingAction = action;
    this.state.recordedKeys = [];

    const badgeMap = {
      'snip_region': 'key-badge-region',
      'snip_fullscreen': 'key-badge-fullscreen',
      'snip_active_window': 'key-badge-window'
    };

    const badge = document.getElementById(badgeMap[action]);
    if (badge) {
      badge.textContent = '请按下快捷键组合...';
      badge.classList.add('recording');
    }
  },

  stopRecordingKey() {
    this.state.recordingAction = null;
    document.querySelectorAll('.key-badge').forEach(b => b.classList.remove('recording'));
  },

  insertTemplateVar(variable) {
    const textarea = document.getElementById('cfg-template');
    if (!textarea) return;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = textarea.value;
    textarea.value = text.substring(0, start) + variable + text.substring(end);
    textarea.focus();
    textarea.selectionStart = textarea.selectionEnd = start + variable.length;
  },

  // New Note Modal
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
        this.fetchConfig();
        this.fetchMarkdown();
        this.fetchCaptures();
        this.showToast(`新笔记创建成功: ${data.filename}`, 'success');
      } else {
        this.showToast(data.message || '创建失败', 'error');
      }
    } catch (e) {
      this.showToast('创建失败: ' + e, 'error');
    }
  },

  bindDOMEvents() {
    // Global Keyboard Listener for Hotkey Recording
    window.addEventListener('keydown', (e) => {
      if (!this.state.recordingAction) return;

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
      if (['Control', 'Alt', 'Shift', 'Meta'].includes(mainKey)) {
        // Just modifier key pressed so far
        return;
      }

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

    // Image save mode change
    const modeSelect = document.getElementById('cfg-img-mode');
    if (modeSelect) {
      modeSelect.addEventListener('change', (e) => {
        const row = document.getElementById('custom-img-folder-row');
        if (row) row.style.display = (e.target.value === 'custom') ? 'flex' : 'none';
      });
    }

    // Hotkey for Ctrl+S in editor
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        if (this.state.activeDocTab === 'source') {
          e.preventDefault();
          this.saveMarkdownContent();
        }
      }
    });
  }
};

document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
