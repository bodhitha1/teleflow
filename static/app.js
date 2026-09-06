document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const panels = {
        connect: document.getElementById("panel-connect"),
        verify: document.getElementById("panel-verify"),
        scraper: document.getElementById("panel-scraper")
    };

    const forms = {
        connect: document.getElementById("connect-form"),
        verify: document.getElementById("verify-form"),
        scraper: document.getElementById("scraper-form")
    };

    const statusDot = document.getElementById("global-status-dot");
    const statusText = document.getElementById("global-status-text");

    const statFields = {
        scanned: document.getElementById("stat-scanned"),
        found: document.getElementById("stat-found"),
        downloaded: document.getElementById("stat-downloaded"),
        failed: document.getElementById("stat-failed"),
        images: document.getElementById("stat-images"),
        urls: document.getElementById("stat-urls"),
        dbDl: document.getElementById("db-stat-dl"),
        dbFail: document.getElementById("db-stat-fail")
    };

    const alertBox = document.getElementById("status-alert");
    const alertMsg = document.getElementById("alert-message");

    const progressContainer = document.getElementById("progress-container");
    const progressFile = document.getElementById("progress-file");
    const progressPercent = document.getElementById("progress-percent");
    const progressBarFill = document.getElementById("progress-bar-fill");

    const valProgressContainer = document.getElementById("validation-progress-container");
    const valProgressText = document.getElementById("validation-progress-text");
    const valTimeEst = document.getElementById("validation-time-est");
    const valBarFill = document.getElementById("validation-bar-fill");

    const scraperStartBtn = document.getElementById("scraper-start-btn");
    const scraperStopBtn = document.getElementById("scraper-stop-btn");
    const disconnectBtn = document.getElementById("disconnect-btn");
    const verifyBackBtn = document.getElementById("verify-back-btn");
    const passwordContainer = document.querySelector(".id-password-container");

    const scraperTargetSelect = document.getElementById("scraper-target-select");
    const scraperTargetManual = document.getElementById("scraper-target");
    const toggleManualTargetBtn = document.getElementById("toggle-manual-target");
    const selectTargetContainer = document.getElementById("select-target-container");
    const manualTargetContainer = document.getElementById("manual-target-container");
    
    let isManualTarget = false;
    let dialogsLoaded = false;
    let statusPollInterval = null;

    // Auto-load credentials from localStorage
    const savedPhone = localStorage.getItem("teleflow_phone") || localStorage.getItem("telegrab_phone");
    
    // Clear old deprecated localStorage keys to prevent bugs
    localStorage.removeItem("teleflow_api_id");
    localStorage.removeItem("telegrab_api_id");
    localStorage.removeItem("telegrab_api_hash");
    localStorage.removeItem("telegrab_dashboard_key");
    if (savedPhone) document.getElementById("phone-number").value = savedPhone;

    // Terminal WebSocket logic
    const terminalView = document.getElementById("terminal-view");
    const terminalStatus = document.getElementById("terminal-status");
    let terminalWs = null;
    let terminalReconnectAttempts = 0;

    function connectTerminal() {
        if (terminalWs) return;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        terminalWs = new WebSocket(`${protocol}//${window.location.host}/api/logs/ws`);
        
        terminalWs.onopen = () => {
            if(terminalStatus) terminalStatus.style.background = 'var(--status-active)';
            terminalReconnectAttempts = 0;
        };
        
        terminalWs.onmessage = (event) => {
            if(terminalView) {
                if (terminalView.childNodes.length > 0 && terminalView.firstChild.nodeType === Node.TEXT_NODE) {
                    terminalView.innerHTML = '';
                }
                
                const lines = event.data.split('\n');
                lines.forEach(line => {
                    if(!line.trim()) return;
                    
                    const el = document.createElement('div');
                    el.style.marginBottom = '2px';
                    el.style.lineHeight = '1.4';
                    
                    const match = line.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+\[(.*?)\]\s+(.*)$/);
                    if (match) {
                        const time = match[1].split(' ')[1].split(',')[0];
                        const level = match[2];
                        let msg = match[3];
                        
                        let color = '#34d399'; // INFO
                        if (level === 'ERROR' || level === 'CRITICAL') color = '#ef4444';
                        else if (level === 'WARNING') color = '#f59e0b';
                        else if (level === 'DEBUG') color = '#9ca3af';
                        
                        // User-friendly translations
                        if(msg.includes("Connection to") && msg.includes("TcpFull complete!")) {
                            msg = "Connected to Telegram servers securely.";
                            color = '#3b82f6';
                        } else if(msg.includes("Connecting to")) {
                            msg = "Establishing secure connection to Telegram...";
                            color = '#6b7280';
                        } else if(msg.includes("Got difference for channel") || msg.includes("Got difference for account updates")) {
                            msg = "Checking for new messages from Telegram...";
                            color = '#8b5cf6';
                        } else if(msg.includes("Invalid or expired link skipped")) {
                            msg = msg.replace("Invalid or expired link skipped:", "Skipped invalid or expired invite link:");
                            color = '#f59e0b';
                        } else if(msg.includes("Rate limit hit during validation")) {
                            msg = msg.replace("Rate limit hit during validation.", "Telegram rate limit reached!");
                            color = '#ef4444';
                        } else if(msg.includes("Starting direct file download in chunks")) {
                            msg = "Downloading media file from Telegram...";
                            color = '#3b82f6';
                        } else if(msg.includes("Disconnecting borrowed sender") || msg.includes("Disconnecting from") || msg.includes("Disconnection from") || msg.includes("Not disconnecting")) {
                            return; // Hide networking spam
                        } else if(msg.includes("Server closed the connection") || msg.includes("Connection closed while receiving data")) {
                            msg = "Network glitch detected. Reconnecting...";
                            color = '#f59e0b';
                        } else if(msg.includes("Closing current connection to begin reconnect")) {
                            msg = "Reconnecting to Telegram servers...";
                            color = '#6b7280';
                        } else if(msg.includes("Connected to entity:")) {
                            msg = msg.replace("Connected to entity:", "Successfully joined and connected to:");
                            color = '#10b981';
                        } else if(msg.includes("Scraping entity")) {
                            msg = msg.replace("Scraping entity", "Currently scraping:");
                            color = '#3b82f6';
                        }
                        
                        const timeEl = document.createElement("span");
                        timeEl.style.color = '#6b7280';
                        timeEl.style.marginRight = '8px';
                        timeEl.textContent = `[${time}]`;

                        const levelEl = document.createElement("span");
                        levelEl.style.color = color;
                        levelEl.style.fontWeight = 'bold';
                        levelEl.style.width = '50px';
                        levelEl.style.display = 'inline-block';
                        levelEl.textContent = level;

                        const msgEl = document.createElement("span");
                        msgEl.style.color = '#e5e7eb';
                        msgEl.style.wordBreak = 'break-word';
                        msgEl.textContent = msg;

                        el.appendChild(timeEl);
                        el.appendChild(levelEl);
                        el.appendChild(msgEl);
                    } else {
                        el.textContent = line;
                        el.style.color = '#ef4444';
                    }
                    
                    terminalView.appendChild(el);
                });
                
                while(terminalView.childNodes.length > 200) {
                    terminalView.removeChild(terminalView.firstChild);
                }
                
                terminalView.scrollTop = terminalView.scrollHeight;
            }
        };
        
        terminalWs.onclose = () => {
            if(terminalStatus) terminalStatus.style.background = 'var(--danger-color)';
            terminalWs = null;
            const delay = Math.min(1000 * Math.pow(2, terminalReconnectAttempts), 30000);
            terminalReconnectAttempts++;
            setTimeout(connectTerminal, delay);
        };
    }
    connectTerminal();

    // Proxy Toggle
    const toggleProxyBtn = document.getElementById("toggle-proxy");
    const proxySettings = document.getElementById("proxy-settings");
    if (toggleProxyBtn && proxySettings) {
        toggleProxyBtn.addEventListener("click", (e) => {
            e.preventDefault();
            if (proxySettings.style.display === "none") {
                proxySettings.style.display = "block";
                toggleProxyBtn.textContent = "Hide Proxy Settings";
            } else {
                proxySettings.style.display = "none";
                toggleProxyBtn.textContent = "Advanced: Proxy Settings";
            }
        });
    }

    // Helper: Show specific panel
    function showPanel(panelName) {
        Object.keys(panels).forEach(key => {
            if (key === panelName) {
                panels[key].classList.remove("hidden");
                panels[key].classList.add("active");
                panels[key].style.display = "block";
                
                // If opening scraper panel, load dialogs
                if (panelName === "scraper" && !dialogsLoaded) {
                    loadDialogs();
                }
            } else {
                panels[key].classList.add("hidden");
                panels[key].classList.remove("active");
                panels[key].style.display = "none";
            }
        });
    }

    // Configure SweetAlert2 Toast with safe fallback
    const Toast = (typeof Swal !== "undefined") ? Swal.mixin({
        toast: true,
        position: 'top-end',
        showConfirmButton: false,
        timer: 5000,
        timerProgressBar: true,
        background: 'rgba(20, 20, 28, 0.95)',
        color: '#f8fafc',
        didOpen: (toast) => {
            toast.addEventListener('mouseenter', Swal.stopTimer);
            toast.addEventListener('mouseleave', Swal.resumeTimer);
        }
    }) : {
        fire: (opts) => console.log("Toast:", opts)
    };

    // Helper: Display Alert messages
    function showAlert(message, type = "info") {
        let iconType = "info";
        if (type === "error") iconType = "error";
        if (type === "success") iconType = "success";
        
        if (typeof Swal !== "undefined") {
            if (type === "error") {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: message,
                    background: 'rgba(20, 20, 28, 0.95)',
                    color: '#f8fafc',
                    confirmButtonColor: '#9333ea',
                    customClass: {
                        popup: 'glass-card'
                    }
                });
            } else {
                Toast.fire({
                    icon: iconType,
                    title: message
                });
            }
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
            if (alertBox) {
                alertBox.textContent = message;
                alertBox.className = `alert alert-${type}`;
                alertBox.style.display = "block";
            }
            return;
        }
        
        // Hide standard alert box if it exists
        if (alertBox) alertBox.style.display = "none";
    }

    // Helper: Hide Alert
    function hideAlert() {
        if (alertBox) alertBox.style.display = "none";
    }

    let lastVideosFound = 0;

    // Update Telemetry Panel
    function updateTelemetry(data) {
        if (statFields.scanned) statFields.scanned.textContent = data.scanned ?? 0;
        if (statFields.found) {
            const currentVideosFound = data.videos_found ?? 0;
            statFields.found.textContent = currentVideosFound;
            
            if (currentVideosFound > lastVideosFound) {
                const videoStatBox = document.getElementById("video-stat-box");
                if (videoStatBox) {
                    videoStatBox.classList.remove("video-found-pulse");
                    void videoStatBox.offsetWidth; // Trigger reflow
                    videoStatBox.classList.add("video-found-pulse");
                }
                lastVideosFound = currentVideosFound;
            }
            
            // Reset counter when scraping stops
            if (data.status !== "scraping" && currentVideosFound === 0) {
                lastVideosFound = 0;
            }
        }
        if (statFields.downloaded) statFields.downloaded.textContent = data.downloaded ?? 0;
        if (statFields.failed) statFields.failed.textContent = data.failed ?? 0;
        if (statFields.images) statFields.images.textContent = data.images_found ?? 0;
        
        if (statFields.urls) {
            if (data.status === "validating") {
                statFields.urls.textContent = "";
                const spanValid = document.createElement("span");
                spanValid.style.color = "var(--status-active)";
                spanValid.textContent = data.urls_valid || 0;
                
                const spanTotal = document.createElement("span");
                spanTotal.style.fontSize = "0.5em";
                spanTotal.style.color = "var(--text-secondary)";
                spanTotal.textContent = ` / ${data.urls_found || 0} Valid`;
                
                statFields.urls.appendChild(spanValid);
                statFields.urls.appendChild(spanTotal);
            } else {
                statFields.urls.textContent = data.urls_found || 0;
            }
        }
        if (statFields.dbDl) statFields.dbDl.textContent = data.db_total ?? 0;
        if (statFields.dbFail) statFields.dbFail.textContent = data.db_failed ?? 0;

        // Global status indicator
        if (statusDot) statusDot.className = `dot ${data.status}`;
        if (statusText) {
            if (data.status === "validating" && data.validation_total > 0) {
                statusText.textContent = `Validating (${data.validation_current}/${data.validation_total})`;
            } else {
                const statusStr = data.status || "unknown";
                statusText.textContent = statusStr.charAt(0).toUpperCase() + statusStr.slice(1);
            }
        }

        // Progress indicators
        if (data.status === "scraping" && data.current_file) {
            progressContainer.style.display = "block";
            progressFile.textContent = data.current_file;
            progressPercent.textContent = `${data.current_progress}%`;
            progressBarFill.style.width = `${data.current_progress}%`;
        } else {
            progressContainer.style.display = "none";
        }

        if (data.status === "validating" && data.validation_total > 0) {
            valProgressContainer.style.display = "block";
            const current = data.validation_current;
            const total = data.validation_total;
            const remaining = total - current;
            const percent = Math.floor((current / total) * 100);
            
            valProgressText.textContent = `Validating Links (${current}/${total})`;
            valBarFill.style.width = `${percent}%`;
            
            if (data.validation_status_msg) {
                valTimeEst.textContent = data.validation_status_msg;
                valTimeEst.style.color = "var(--danger-color)";
                valBarFill.style.background = "var(--danger-color)";
            } else if (remaining > 0) {
                const secondsRemaining = Math.floor(remaining * 3.5);
                const mins = Math.floor(secondsRemaining / 60);
                const secs = secondsRemaining % 60;
                valTimeEst.textContent = `~${mins}m ${secs}s left`;
                valTimeEst.style.color = "var(--text-muted)";
                valBarFill.style.background = "linear-gradient(90deg, var(--accent-cyan), var(--accent-blue))";
            } else {
                valTimeEst.textContent = "Finishing up...";
                valTimeEst.style.color = "var(--text-muted)";
                valBarFill.style.background = "linear-gradient(90deg, var(--accent-cyan), var(--accent-blue))";
            }
        } else {
            valProgressContainer.style.display = "none";
        }

        // Adjust UI controls according to active running state
        if (data.status === "scraping" || data.status === "validating") {
            if (scraperStartBtn) scraperStartBtn.style.display = "none";
            if (scraperStopBtn) scraperStopBtn.style.display = "inline-block";
            const scraperTargetInput = document.getElementById("scraper-target");
            if (scraperTargetInput) scraperTargetInput.disabled = true;
            if (disconnectBtn) disconnectBtn.disabled = true;
        } else {
            if (scraperStartBtn) scraperStartBtn.style.display = "inline-block";
            if (scraperStopBtn) scraperStopBtn.style.display = "none";
            const scraperTargetInput = document.getElementById("scraper-target");
            if (scraperTargetInput) scraperTargetInput.disabled = false;
            if (disconnectBtn) disconnectBtn.disabled = false;
        }

        // Sync Live Watcher indicator & modal buttons
        const daemonBadge = document.getElementById("daemon-nav-badge");
        const daemonStart = document.getElementById("daemon-start-btn");
        const daemonStop = document.getElementById("daemon-stop-btn");
        if (daemonBadge) {
            if (data.is_watching) {
                daemonBadge.textContent = "Watching";
                daemonBadge.className = "watcher-badge active";
                if (daemonStart) daemonStart.classList.add("hidden");
                if (daemonStop) daemonStop.classList.remove("hidden");
                if (!watchWs || watchWs.readyState === WebSocket.CLOSED) {
                    connectDaemonWebSocket();
                }
            } else {
                daemonBadge.textContent = "Idle";
                daemonBadge.className = "watcher-badge idle";
                if (daemonStart) daemonStart.classList.remove("hidden");
                if (daemonStop) daemonStop.classList.add("hidden");
            }
        }

        // Panel router based on server state
        if (data.status === "idle" && !panels.connect.classList.contains("active") && !panels.verify.classList.contains("active")) {
            showPanel("connect");
        } else if (data.status === "authenticating" && !panels.verify.classList.contains("active")) {
            showPanel("verify");
        } else if (data.status === "connected" && !panels.scraper.classList.contains("active")) {
            showPanel("scraper");
        } else if ((data.status === "scraping" || data.status === "validating") && !panels.scraper.classList.contains("active")) {
            showPanel("scraper");
        }
    }

    let telemetryWs = null;
    let telemetryReconnectDelay = 1000;
    let telemetryShouldReconnect = true;

    function connectTelemetry() {
        if (telemetryWs) {
            telemetryWs.onclose = null;
            telemetryWs.onerror = null;
            telemetryWs.close();
        }
        telemetryShouldReconnect = true;
        
        const outputEl = document.getElementById("scraper-output");
        const targetOutput = outputEl?.value?.trim() || "./downloads";
        const savedToken = localStorage.getItem("teleflow_token") || localStorage.getItem("telegrab_token");
        const tokenQuery = savedToken ? `&token=${encodeURIComponent(savedToken)}` : "";
        
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        telemetryWs = new WebSocket(`${protocol}//${window.location.host}/api/status/ws?output=${encodeURIComponent(targetOutput)}${tokenQuery}`);
        
        telemetryWs.onopen = () => {
            console.log("Telemetry WebSocket connected");
            telemetryReconnectDelay = 1000;
        };
        
        telemetryWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                updateTelemetry(data);
            } catch (err) {
                console.error("Failed to parse telemetry data:", err);
            }
        };
        
        telemetryWs.onclose = (event) => {
            console.log("Telemetry WebSocket closed", event.code);
            if (telemetryShouldReconnect) {
                setTimeout(() => {
                    console.log(`Reconnecting telemetry in ${telemetryReconnectDelay}ms...`);
                    connectTelemetry();
                    telemetryReconnectDelay = Math.min(telemetryReconnectDelay * 2, 30000);
                }, telemetryReconnectDelay);
            }
        };
        
        telemetryWs.onerror = (err) => {
            console.error("Telemetry WebSocket error:", err);
        };
    }

    // 3-Mode Channel Selector Setup
    let currentTargetMode = "single";
    const selectedMultipleChannels = new Set();
    const modeTabs = {
        single: document.getElementById("mode-btn-single"),
        multiple: document.getElementById("mode-btn-multiple"),
        all: document.getElementById("mode-btn-all")
    };
    const modeContents = {
        single: document.getElementById("target-mode-single"),
        multiple: document.getElementById("target-mode-multiple"),
        all: document.getElementById("target-mode-all")
    };

    function setTargetMode(mode) {
        currentTargetMode = mode;
        Object.keys(modeTabs).forEach(k => {
            if (modeTabs[k]) {
                if (k === mode) {
                    modeTabs[k].classList.add("active");
                } else {
                    modeTabs[k].classList.remove("active");
                }
            }
            if (modeContents[k]) {
                if (k === mode) {
                    modeContents[k].classList.remove("hidden");
                    modeContents[k].classList.add("active");
                } else {
                    modeContents[k].classList.add("hidden");
                    modeContents[k].classList.remove("active");
                }
            }
        });
    }

    Object.keys(modeTabs).forEach(mode => {
        if (modeTabs[mode]) {
            modeTabs[mode].addEventListener("click", () => setTargetMode(mode));
        }
    });

    function updateMultiBadge() {
        const badge = document.getElementById("multi-selected-badge");
        if (badge) {
            if (selectedMultipleChannels.size > 0) {
                badge.textContent = selectedMultipleChannels.size;
                badge.classList.remove("hidden");
            } else {
                badge.classList.add("hidden");
            }
        }
    }

    // 3-Mode Daemon Channel Selector Setup
    let currentDaemonTargetMode = "single";
    let isDaemonManualTarget = false;
    const selectedDaemonMultipleChannels = new Set();
    const daemonModeTabs = {
        single: document.getElementById("daemon-mode-btn-single"),
        multiple: document.getElementById("daemon-mode-btn-multiple"),
        all: document.getElementById("daemon-mode-btn-all")
    };
    const daemonModeContents = {
        single: document.getElementById("daemon-target-mode-single"),
        multiple: document.getElementById("daemon-target-mode-multiple"),
        all: document.getElementById("daemon-target-mode-all")
    };

    function setDaemonTargetMode(mode) {
        currentDaemonTargetMode = mode;
        Object.keys(daemonModeTabs).forEach(k => {
            if (daemonModeTabs[k]) {
                if (k === mode) {
                    daemonModeTabs[k].classList.add("active");
                } else {
                    daemonModeTabs[k].classList.remove("active");
                }
            }
            if (daemonModeContents[k]) {
                if (k === mode) {
                    daemonModeContents[k].classList.remove("hidden");
                    daemonModeContents[k].classList.add("active");
                } else {
                    daemonModeContents[k].classList.add("hidden");
                    daemonModeContents[k].classList.remove("active");
                }
            }
        });
    }

    Object.keys(daemonModeTabs).forEach(mode => {
        if (daemonModeTabs[mode]) {
            daemonModeTabs[mode].addEventListener("click", () => setDaemonTargetMode(mode));
        }
    });

    function updateDaemonMultiBadge() {
        const badge = document.getElementById("daemon-multi-selected-badge");
        if (badge) {
            if (selectedDaemonMultipleChannels.size > 0) {
                badge.textContent = selectedDaemonMultipleChannels.size;
                badge.classList.remove("hidden");
            } else {
                badge.classList.add("hidden");
            }
        }
    }

    const daemonToggleManualBtn = document.getElementById("daemon-toggle-manual-target");
    const daemonSelectTargetContainer = document.getElementById("daemon-select-target-container");
    const daemonManualTargetContainer = document.getElementById("daemon-manual-target-container");
    const daemonTargetSelect = document.getElementById("daemon-target-select");
    const daemonTargetManual = document.getElementById("daemon-target-manual");

    if (daemonToggleManualBtn) {
        daemonToggleManualBtn.addEventListener("click", (e) => {
            e.preventDefault();
            isDaemonManualTarget = !isDaemonManualTarget;
            if (isDaemonManualTarget) {
                if (daemonSelectTargetContainer) daemonSelectTargetContainer.style.display = "none";
                if (daemonManualTargetContainer) daemonManualTargetContainer.style.display = "flex";
                daemonToggleManualBtn.textContent = "Back to selection list";
            } else {
                if (daemonSelectTargetContainer) daemonSelectTargetContainer.style.display = "flex";
                if (daemonManualTargetContainer) daemonManualTargetContainer.style.display = "none";
                daemonToggleManualBtn.textContent = "Or enter username/link manually";
            }
        });
    }

    // Load user dialogs (channels/groups)
    async function loadDialogs() {
        try {
            scraperTargetSelect.innerHTML = '<option value="">Loading your channels...</option>';
            if (daemonTargetSelect) daemonTargetSelect.innerHTML = '<option value="">Loading your channels...</option>';

            const multiListContainer = document.getElementById("multi-channels-list");
            if (multiListContainer) {
                multiListContainer.innerHTML = '<div class="multi-loading-state"><i class="ph-bold ph-spinner" style="animation: spin 1s linear infinite;"></i><span>Loading channels...</span></div>';
            }
            const daemonMultiListContainer = document.getElementById("daemon-multi-channels-list");
            if (daemonMultiListContainer) {
                daemonMultiListContainer.innerHTML = '<div class="multi-loading-state"><i class="ph-bold ph-spinner" style="animation: spin 1s linear infinite;"></i><span>Loading channels...</span></div>';
            }

            const res = await fetch("/api/dialogs");
            if (res.ok) {
                const data = await res.json();
                if (data.dialogs && data.dialogs.length > 0) {
                    scraperTargetSelect.innerHTML = '<option value="" disabled selected>Select a channel or group</option>';
                    if (daemonTargetSelect) daemonTargetSelect.innerHTML = '<option value="" disabled selected>Select a channel or group</option>';
                    
                    // Single Select options
                    data.dialogs.forEach(dialog => {
                        const opt = document.createElement("option");
                        opt.value = dialog.id;
                        opt.textContent = `${dialog.name} (${dialog.type})`;
                        scraperTargetSelect.appendChild(opt);

                        if (daemonTargetSelect) {
                            const dOpt = document.createElement("option");
                            dOpt.value = dialog.id;
                            dOpt.textContent = `${dialog.name} (${dialog.type})`;
                            daemonTargetSelect.appendChild(dOpt);
                        }
                    });

                    // Scraper Multiple Checklist
                    if (multiListContainer) {
                        multiListContainer.innerHTML = "";
                        data.dialogs.forEach(dialog => {
                            const row = document.createElement("label");
                            row.className = "channel-check-row";
                            row.dataset.name = (dialog.name || "").toLowerCase();
                            row.innerHTML = `
                                <input type="checkbox" value="${dialog.id}">
                                <div class="channel-check-info">
                                    <span class="channel-check-name">${dialog.name}</span>
                                    <span class="channel-check-type">${dialog.type}</span>
                                </div>
                            `;
                            const cb = row.querySelector("input");
                            cb.addEventListener("change", () => {
                                if (cb.checked) {
                                    selectedMultipleChannels.add(dialog.id);
                                    row.classList.add("selected");
                                } else {
                                    selectedMultipleChannels.delete(dialog.id);
                                    row.classList.remove("selected");
                                }
                                updateMultiBadge();
                            });
                            multiListContainer.appendChild(row);
                        });
                    }

                    // Daemon Multiple Checklist
                    if (daemonMultiListContainer) {
                        daemonMultiListContainer.innerHTML = "";
                        data.dialogs.forEach(dialog => {
                            const row = document.createElement("label");
                            row.className = "channel-check-row";
                            row.dataset.name = (dialog.name || "").toLowerCase();
                            row.innerHTML = `
                                <input type="checkbox" value="${dialog.id}">
                                <div class="channel-check-info">
                                    <span class="channel-check-name">${dialog.name}</span>
                                    <span class="channel-check-type">${dialog.type}</span>
                                </div>
                            `;
                            const cb = row.querySelector("input");
                            cb.addEventListener("change", () => {
                                if (cb.checked) {
                                    selectedDaemonMultipleChannels.add(dialog.id);
                                    row.classList.add("selected");
                                } else {
                                    selectedDaemonMultipleChannels.delete(dialog.id);
                                    row.classList.remove("selected");
                                }
                                updateDaemonMultiBadge();
                            });
                            daemonMultiListContainer.appendChild(row);
                        });
                    }

                    // Scraper Multi search filter
                    const searchInput = document.getElementById("multi-search-input");
                    if (searchInput && multiListContainer) {
                        searchInput.oninput = () => {
                            const query = searchInput.value.trim().toLowerCase();
                            const rows = multiListContainer.querySelectorAll(".channel-check-row");
                            rows.forEach(r => {
                                r.style.display = r.dataset.name.includes(query) ? "flex" : "none";
                            });
                        };
                    }

                    // Daemon Multi search filter
                    const daemonSearchInput = document.getElementById("daemon-multi-search-input");
                    if (daemonSearchInput && daemonMultiListContainer) {
                        daemonSearchInput.oninput = () => {
                            const query = daemonSearchInput.value.trim().toLowerCase();
                            const rows = daemonMultiListContainer.querySelectorAll(".channel-check-row");
                            rows.forEach(r => {
                                r.style.display = r.dataset.name.includes(query) ? "flex" : "none";
                            });
                        };
                    }

                    // Scraper Multi Select All / Clear
                    const selectAllBtn = document.getElementById("multi-select-all-btn");
                    const clearBtn = document.getElementById("multi-clear-btn");
                    if (selectAllBtn && multiListContainer) {
                        selectAllBtn.onclick = () => {
                            const visibleRows = multiListContainer.querySelectorAll('.channel-check-row:not([style*="display: none"])');
                            visibleRows.forEach(r => {
                                const cb = r.querySelector('input[type="checkbox"]');
                                cb.checked = true;
                                selectedMultipleChannels.add(cb.value);
                                r.classList.add("selected");
                            });
                            updateMultiBadge();
                        };
                    }
                    if (clearBtn && multiListContainer) {
                        clearBtn.onclick = () => {
                            multiListContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                                cb.checked = false;
                                cb.closest(".channel-check-row").classList.remove("selected");
                            });
                            selectedMultipleChannels.clear();
                            updateMultiBadge();
                        };
                    }

                    // Daemon Multi Select All / Clear
                    const daemonSelectAllBtn = document.getElementById("daemon-multi-select-all-btn");
                    const daemonClearBtn = document.getElementById("daemon-multi-clear-btn");
                    if (daemonSelectAllBtn && daemonMultiListContainer) {
                        daemonSelectAllBtn.onclick = () => {
                            const visibleRows = daemonMultiListContainer.querySelectorAll('.channel-check-row:not([style*="display: none"])');
                            visibleRows.forEach(r => {
                                const cb = r.querySelector('input[type="checkbox"]');
                                cb.checked = true;
                                selectedDaemonMultipleChannels.add(cb.value);
                                r.classList.add("selected");
                            });
                            updateDaemonMultiBadge();
                        };
                    }
                    if (daemonClearBtn && daemonMultiListContainer) {
                        daemonClearBtn.onclick = () => {
                            daemonMultiListContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                                cb.checked = false;
                                cb.closest(".channel-check-row").classList.remove("selected");
                            });
                            selectedDaemonMultipleChannels.clear();
                            updateDaemonMultiBadge();
                        };
                    }

                    // Also populate daemon target datalist if present
                    const daemonDatalist = document.getElementById("dialogs-datalist");
                    if (daemonDatalist) {
                        daemonDatalist.innerHTML = '<option value="ALL">All Joined Channels & Groups</option>' + 
                            data.dialogs.map(d => `<option value="${d.id}">${d.name} (${d.type})</option>`).join("");
                    }
                } else {
                    scraperTargetSelect.innerHTML = '<option value="">No channels/groups found</option>';
                    if (daemonTargetSelect) daemonTargetSelect.innerHTML = '<option value="">No channels/groups found</option>';
                    if (multiListContainer) {
                        multiListContainer.innerHTML = '<div class="multi-empty-state">No channels found</div>';
                    }
                    if (daemonMultiListContainer) {
                        daemonMultiListContainer.innerHTML = '<div class="multi-empty-state">No channels found</div>';
                    }
                }
                dialogsLoaded = true;
            } else {
                scraperTargetSelect.innerHTML = '<option value="">Failed to load channels</option>';
                if (daemonTargetSelect) daemonTargetSelect.innerHTML = '<option value="">Failed to load channels</option>';
                if (res.status === 400 || res.status === 401) {
                    showPanel("connect");
                    showAlert("Client session not active. Please connect with your phone number and password.", "info");
                }
            }
        } catch (err) {
            console.error("Error loading dialogs:", err);
            scraperTargetSelect.innerHTML = '<option value="">Error loading channels</option>';
            if (daemonTargetSelect) daemonTargetSelect.innerHTML = '<option value="">Error loading channels</option>';
        }
    }

    // Toggle manual/dropdown target
    toggleManualTargetBtn.addEventListener("click", (e) => {
        e.preventDefault();
        isManualTarget = !isManualTarget;
        if (isManualTarget) {
            selectTargetContainer.style.display = "none";
            manualTargetContainer.style.display = "flex";
            toggleManualTargetBtn.textContent = "Back to selection list";
        } else {
            selectTargetContainer.style.display = "flex";
            manualTargetContainer.style.display = "none";
            toggleManualTargetBtn.textContent = "Or enter username/link manually";
        }
    });

    // Update Logo when target changes
    scraperTargetSelect.addEventListener("change", (e) => {
        const dialogId = e.target.value;
        const logoContainer = document.getElementById("channel-logo-container");
        if (dialogId && dialogId !== "ALL") {
            logoContainer.innerHTML = `<img src="/api/avatar/${dialogId}" alt="Logo" style="width:100%; height:100%; object-fit:cover; border-radius:inherit;" onerror="this.onerror=null; this.parentNode.innerHTML='<i class=\\'ph-duotone ph-target\\' id=\\'channel-logo-icon\\'></i>';">`;
        } else {
            logoContainer.innerHTML = `<i class="ph-duotone ph-target" id="channel-logo-icon"></i>`;
        }
    });

    // Reset Session Button Handler
    const resetSessionBtn = document.getElementById("reset-session-btn");
    if (resetSessionBtn) {
        resetSessionBtn.addEventListener("click", async () => {
            let phone = document.getElementById("phone-number").value.trim().replace(/[\s\-\(\)]/g, "");
            if (phone.startsWith("0") && phone.length === 10) {
                phone = "+94" + phone.slice(1);
            } else if (phone && !phone.startsWith("+")) {
                phone = "+" + phone;
            }
            if (!phone) {
                showAlert("Please enter your phone number first to reset its saved session.", "info");
                return;
            }

            const confirmed = window.confirm(`Are you sure you want to reset the saved session for ${phone}?\n\nThis will clear any cached session files and allow you to log in fresh with a new Telegram code.`);
            if (!confirmed) return;

            resetSessionBtn.disabled = true;
            try {
                const res = await fetch("/api/session/reset", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ phone: phone })
                });
                const data = await res.json();
                if (res.ok) {
                    localStorage.removeItem("teleflow_token");
                    localStorage.removeItem("telegrab_token");
                    showAlert(data.message || "Saved session was reset successfully. You can now connect fresh.", "success");
                } else {
                    showAlert(data.detail || "Failed to reset session.", "error");
                }
            } catch (err) {
                showAlert("Network error resetting session.", "error");
            } finally {
                resetSessionBtn.disabled = false;
            }
        });
    }

    // Submit Connect details
    forms.connect.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideAlert();
        
        const apiIdVal = document.getElementById("api-id").value;
        const apiId = apiIdVal ? parseInt(apiIdVal) : null;
        const apiHash = document.getElementById("api-hash").value.trim() || null;
        let phone = document.getElementById("phone-number").value.trim().replace(/[\s\-\(\)]/g, "");
        if (phone.startsWith("0") && phone.length === 10) {
            phone = "+94" + phone.slice(1);
        } else if (phone && !phone.startsWith("+")) {
            phone = "+" + phone;
        }
        const proxyType = document.getElementById("proxy-type") ? document.getElementById("proxy-type").value : "";
        const proxyAddr = document.getElementById("proxy-addr") ? document.getElementById("proxy-addr").value.trim() : "";
        const proxyPort = document.getElementById("proxy-port") && document.getElementById("proxy-port").value ? parseInt(document.getElementById("proxy-port").value) : null;

        const masterPassword = document.getElementById("master-password").value;

        // Save credentials to localStorage
        if (phone) {
            localStorage.setItem("teleflow_phone", phone);
            localStorage.setItem("telegrab_phone", phone);
        }

        const btn = document.getElementById("connect-btn");
        const btnText = document.getElementById("connect-btn-text") || (btn ? btn.querySelector("span") : null);
        const btnIcon = document.getElementById("connect-btn-icon") || (btn ? btn.querySelector("i") : null);

        if (btn) btn.disabled = true;
        if (btnText) btnText.textContent = "Connecting to Telegram...";
        if (btnIcon) btnIcon.className = "ph ph-spinner-gap ph-spin";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 35000);

        try {
            const res = await fetch("/api/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    api_id: apiId, 
                    api_hash: apiHash, 
                    phone: phone,
                    master_password: masterPassword,
                    proxy_type: proxyType || null,
                    proxy_addr: proxyAddr || null,
                    proxy_port: proxyPort || null
                }),
                signal: controller.signal
            });

            clearTimeout(timeoutId);
            const data = await res.json().catch(() => ({ detail: "Invalid server response." }));
            if (res.ok) {
                if (data.status === "connected") {
                    if (data.token) {
                        localStorage.setItem("teleflow_token", data.token);
                        localStorage.setItem("telegrab_token", data.token);
                    }
                    showAlert(data.message || "Connected successfully!", "success");
                    showPanel("scraper");
                } else if (data.status === "needs_code") {
                    showAlert(data.message || "Verification code sent to your Telegram account.", "info");
                    showPanel("verify");
                }
            } else {
                const errMessage = data.detail || data.error || data.message || `Connection failed (Status ${res.status})`;
                showAlert(errMessage, "error");
            }
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === "AbortError") {
                showAlert("Connection timed out (35s). Telegram servers may be unreachable or responding slowly. Please check your internet or retry.", "error");
            } else {
                showAlert(err.message || "Network error connecting to client.", "error");
            }
        } finally {
            if (btn) btn.disabled = false;
            if (btnText) btnText.textContent = "Connect Client";
            if (btnIcon) btnIcon.className = "ph-bold ph-arrow-right";
            connectTelemetry();
        }
    });

    // Submit Verification Code
    forms.verify.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideAlert();

        let phone = (localStorage.getItem("teleflow_phone") || localStorage.getItem("telegrab_phone") || document.getElementById("phone-number").value || "").trim().replace(/[\s\-\(\)]/g, "");
        if (phone.startsWith("0") && phone.length === 10) {
            phone = "+94" + phone.slice(1);
        } else if (phone && !phone.startsWith("+")) {
            phone = "+" + phone;
        }
        const code = document.getElementById("verify-code").value.trim().replace(/[\s\-]/g, "");
        const password = document.getElementById("verify-password").value.trim();

        const btn = document.getElementById("verify-btn");
        const btnText = btn ? btn.querySelector("span") : null;
        const btnIcon = btn ? btn.querySelector("i") : null;

        if (btn) btn.disabled = true;
        if (btnText) btnText.textContent = "Verifying Code...";
        if (btnIcon) btnIcon.className = "ph ph-spinner-gap ph-spin";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        try {
            const res = await fetch("/api/verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    phone: phone,
                    code: code, 
                    password: password || null 
                }),
                signal: controller.signal
            });

            clearTimeout(timeoutId);
            const data = await res.json().catch(() => ({ detail: "Invalid response from server." }));
            if (res.ok) {
                if (data.status === "connected") {
                    if (data.token) {
                        localStorage.setItem("teleflow_token", data.token);
                        localStorage.setItem("telegrab_token", data.token);
                    }
                    showAlert(data.message, "success");
                    showPanel("scraper");
                    if (passwordContainer) passwordContainer.style.display = "none";
                } else if (data.status === "needs_password") {
                    showAlert(data.message, "info");
                    if (passwordContainer) passwordContainer.style.display = "block";
                }
            } else {
                const errMessage = data.detail || data.error || data.message || "Verification failed.";
                showAlert(errMessage, "error");
            }
        } catch (err) {
            clearTimeout(timeoutId);
            if (err.name === "AbortError") {
                showAlert("Verification request timed out. Please try again.", "error");
            } else {
                showAlert(err.message || "Network error verifying code.", "error");
            }
        } finally {
            if (btn) btn.disabled = false;
            if (btnText) btnText.textContent = "Verify";
            if (btnIcon) btnIcon.className = "ph-bold ph-shield-check";
            connectTelemetry();
        }
    });

    // Go back from verification screen
    verifyBackBtn.addEventListener("click", async () => {
        try {
            await fetch("/api/disconnect", { method: "POST" });
            showPanel("connect");
            hideAlert();
        } catch (err) {}
        connectTelemetry();
    });

    // Disconnect click
    disconnectBtn.addEventListener("click", async () => {
        if (!confirm("Are you sure you want to disconnect?")) {
            return;
        }

        try {
            const res = await fetch("/api/disconnect", { method: "POST" });
            const data = await res.json();
            
            if (!res.ok) {
                throw new Error(data.detail || data.message || "Disconnect failed");
            }
            
            localStorage.removeItem("teleflow_token");
            localStorage.removeItem("telegrab_token");
            dialogsLoaded = false;
            showPanel("connect");
            showAlert(data.message || "Disconnected successfully.", "info");
        } catch (err) {
            showAlert(err.message || "Error disconnecting client.", "error");
        }
        connectTelemetry();
    });

    // Start Scraper click
    forms.scraper.addEventListener("submit", async (e) => {
        e.preventDefault();
        hideAlert();

        let target = "";
        if (currentTargetMode === "all") {
            target = "ALL";
        } else if (currentTargetMode === "multiple") {
            if (selectedMultipleChannels.size === 0) {
                showAlert("Please select at least one channel from the checklist.", "error");
                return;
            }
            target = Array.from(selectedMultipleChannels).join(",");
        } else {
            if (isManualTarget) {
                target = scraperTargetManual.value.trim();
            } else {
                target = scraperTargetSelect.value;
            }
            if (!target) {
                showAlert("Please select or enter a target channel.", "error");
                return;
            }
        }

        const outputEl = document.getElementById("scraper-output");
        const output = outputEl ? outputEl.value.trim() : "./downloads";
        const startDate = document.getElementById("scraper-start-date").value || null;
        const endDate = document.getElementById("scraper-end-date").value || null;
        const scrapeVideos = document.getElementById("scrape-videos") ? document.getElementById("scrape-videos").checked : true;
        const scrapeImages = document.getElementById("scrape-images") ? document.getElementById("scrape-images").checked : true;
        const scrapeMessages = document.getElementById("scrape-messages") ? document.getElementById("scrape-messages").checked : true;
        const scrapeOthers = document.getElementById("scrape-others") ? document.getElementById("scrape-others").checked : true;
        const scrapeUrls = document.getElementById("scrape-urls") ? document.getElementById("scrape-urls").checked : true;
        const forwardTarget = document.getElementById("forward-target").value.trim();
        const mirrorTarget = document.getElementById("mirror-target") ? document.getElementById("mirror-target").value.trim() : "";
        const webhookUrl = document.getElementById("webhook-url") ? document.getElementById("webhook-url").value.trim() : "";
        
        localStorage.setItem("teleflow_target", target);
        localStorage.setItem("teleflow_output", output);
        localStorage.setItem("telegrab_target", target);
        localStorage.setItem("telegrab_output", output);

        // Send request
        try {
            const res = await fetch("/api/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 
                    target: target, 
                    output_dir: output,
                    start_date: startDate,
                    end_date: endDate,
                    scrape_videos: scrapeVideos,
                    scrape_images: scrapeImages,
                    scrape_messages: scrapeMessages,
                    scrape_others: scrapeOthers,
                    scrape_urls: scrapeUrls,
                    forward_target: forwardTarget || "me",
                    mirror_target: mirrorTarget || null,
                    webhook_url: webhookUrl || null
                })
            });
            const data = await res.json();
            if (res.ok) {
                showAlert("Connected! Starting scraper...", "success");
                showPanel("scraper");
            } else {
                let errMsg = data.detail || data.message || "Failed to start scraping";
                if (typeof errMsg !== 'string') {
                    errMsg = JSON.stringify(errMsg);
                }
                showAlert(errMsg, "error");
            }
        } catch (err) {
            showAlert("Failed to start scraper: " + err, "error");
        }
        connectTelemetry();
    });

    const dashboardCleanJunkBtn = document.getElementById("dashboard-clean-junk-btn");
    if (dashboardCleanJunkBtn) {
        dashboardCleanJunkBtn.addEventListener("click", async () => {
            dashboardCleanJunkBtn.disabled = true;
            try {
                const res = await fetch("/api/system/clean_cache", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert(data.message || "Temporary junk files cleaned!", "success");
                } else {
                    showAlert(data.detail || "Clean failed.", "error");
                }
            } catch (err) {
                showAlert("Network error cleaning cache.", "error");
            } finally {
                dashboardCleanJunkBtn.disabled = false;
            }
        });
    }

    // Stop Scraper click
    scraperStopBtn.addEventListener("click", async () => {
        try {
            const res = await fetch("/api/stop", { method: "POST" });
            const data = await res.json();
            showAlert(data.message, "info");
        } catch (err) {
            showAlert("Error stopping scraper.", "error");
        }
        connectTelemetry();
    });

    // Initialize Telemetry WebSocket
    connectTelemetry();

    // URL Stat Box click handler
    const urlStatBox = document.getElementById("url-stat-box");
    if (urlStatBox) {
        urlStatBox.addEventListener("click", () => {
            window.open('/links.html', '_blank');
        });
    }

    // Videos/Media Stat Box click handler
    const videoStatBox = document.getElementById("video-stat-box");
    if (videoStatBox) {
        videoStatBox.addEventListener("click", () => {
            window.open('/media.html', '_blank');
        });
    }

    // Image Stat Box click handler
    const imageStatBox = document.getElementById("image-stat-box");
    if (imageStatBox) {
        imageStatBox.addEventListener("click", () => {
            window.open('/media.html', '_blank');
        });
    }

    // Register PWA Service Worker with auto-update
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.getRegistrations().then(registrations => {
                for (let reg of registrations) {
                    reg.update();
                }
            });
            navigator.serviceWorker.register('/sw.js?v=5.0').catch(error => {
                console.error('ServiceWorker registration failed: ', error);
            });
        });
    }

    // --- DAEMON MODE UI LOGIC ---
    const daemonModal = document.getElementById("daemon-modal");
    const daemonOpenBtn = document.getElementById("daemon-open-btn");
    const daemonCloseBtn = document.getElementById("daemon-close-btn");
    const daemonForm = document.getElementById("daemon-form");
    const daemonStartBtn = document.getElementById("daemon-start-btn");
    const daemonStopBtn = document.getElementById("daemon-stop-btn");
    const flashCardContainer = document.getElementById("flash-card-container");
    let watchWs = null;

    if (daemonOpenBtn) {
        daemonOpenBtn.addEventListener("click", () => {
            daemonModal.classList.remove("hidden");
            if (!dialogsLoaded) {
                loadDialogs();
            }
        });
        daemonCloseBtn.addEventListener("click", () => {
            daemonModal.classList.add("hidden");
        });
        
        // Close modal on click outside
        daemonModal.addEventListener("click", (e) => {
            if (e.target === daemonModal) {
                daemonModal.classList.add("hidden");
            }
        });
    }

    if (daemonForm) {
        daemonForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            let target = "";
            if (currentDaemonTargetMode === "all") {
                target = "ALL";
            } else if (currentDaemonTargetMode === "multiple") {
                if (selectedDaemonMultipleChannels.size === 0) {
                    showAlert("Please select at least one channel from the checklist to watch.", "error");
                    return;
                }
                target = Array.from(selectedDaemonMultipleChannels).join(",");
            } else {
                if (isDaemonManualTarget) {
                    target = daemonTargetManual ? daemonTargetManual.value.trim() : "";
                } else {
                    target = daemonTargetSelect ? daemonTargetSelect.value : "";
                }
                if (!target) {
                    showAlert("Please select or enter a target channel to watch.", "error");
                    return;
                }
            }

            const output_dir = (document.getElementById("daemon-output") ? document.getElementById("daemon-output").value.trim() : "") || "./downloads";
            
            const scrape_videos = document.getElementById("daemon-watch-videos") ? document.getElementById("daemon-watch-videos").checked : true;
            const scrape_images = document.getElementById("daemon-watch-images") ? document.getElementById("daemon-watch-images").checked : true;
            const scrape_messages = document.getElementById("daemon-watch-messages") ? document.getElementById("daemon-watch-messages").checked : true;
            const scrape_others = document.getElementById("daemon-watch-others") ? document.getElementById("daemon-watch-others").checked : true;

            if(daemonStartBtn.querySelector("span")) {
                daemonStartBtn.querySelector("span").textContent = "Starting...";
            } else {
                daemonStartBtn.textContent = "Starting...";
            }

            try {
                const res = await fetch("/api/watch/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ 
                        target, 
                        output_dir,
                        scrape_videos,
                        scrape_images,
                        scrape_messages,
                        scrape_others
                    })
                });
                const data = await res.json();
                if (res.ok) {
                    showAlert(data.message, "success");
                    daemonStartBtn.classList.add("hidden");
                    daemonStopBtn.classList.remove("hidden");
                    connectDaemonWebSocket();
                    daemonModal.classList.add("hidden");
                } else {
                    showAlert(data.detail || "Error", "error");
                    daemonStartBtn.textContent = "Start Daemon";
                }
            } catch (err) {
                showAlert(err.message, "error");
                daemonStartBtn.textContent = "Start Daemon";
            }
        });
    }

    if (daemonStopBtn) {
        daemonStopBtn.addEventListener("click", async () => {
            try {
                const res = await fetch("/api/watch/stop", { method: "POST" });
                const data = await res.json();
                if (res.ok) {
                    showAlert(data.message, "info");
                    daemonStartBtn.classList.remove("hidden");
                    daemonStopBtn.classList.add("hidden");
                    daemonStartBtn.textContent = "Start Daemon";
                    if (watchWs) watchWs.close();
                }
            } catch (err) {
                showAlert("Error stopping daemon.", "error");
            }
        });
    }

    function playNotificationChime() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.setValueAtTime(587.33, now); // D5
            osc.frequency.setValueAtTime(880, now + 0.12); // A5
            gain.gain.setValueAtTime(0.08, now);
            gain.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now);
            osc.stop(now + 0.35);
        } catch (e) { }
    }

    function connectDaemonWebSocket() {
        if (watchWs && watchWs.readyState === WebSocket.OPEN) {
            return;
        }
        if (watchWs) {
            try { watchWs.close(); } catch (e) {}
        }
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/watch/ws`;
        watchWs = new WebSocket(wsUrl);

        watchWs.onopen = () => {
            console.log("Daemon Watcher WebSocket connected");
        };

        watchWs.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === "DAEMON_NEW_MEDIA") {
                    createFlashCard(data);
                }
            } catch (e) { }
        };

        watchWs.onclose = () => {
            console.log("Daemon Watcher WebSocket closed");
        };
    }

    function createFlashCard(data) {
        if (!flashCardContainer) return;
        playNotificationChime();

        const card = document.createElement("div");
        card.className = "flash-card";
        
        let icon = "ph-file";
        let mediaBadge = "Media";
        const mType = (data.media_type || "").toLowerCase();
        if (mType === "video") {
            icon = "ph-video-camera";
            mediaBadge = "Video";
        } else if (mType === "photo" || mType === "image") {
            icon = "ph-image";
            mediaBadge = "Image";
        } else if (mType === "msg" || mType === "text") {
            icon = "ph-chat-circle-text";
            mediaBadge = "Message (MSG)";
        } else {
            icon = "ph-file-arrow-down";
            mediaBadge = "File / Document";
        }

        let sizeFormatted = "";
        if (data.file_size && data.file_size > 0) {
            sizeFormatted = `(${(data.file_size / (1024 * 1024)).toFixed(1)} MB)`;
        }

        const dateStr = data.date ? new Date(data.date).toLocaleTimeString() : new Date().toLocaleTimeString();
        const channelName = data.channel_name || "Channel";

        card.innerHTML = `
            <div class="flash-card-header" style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.4rem;">
                <div>
                    <div style="font-size: 0.72rem; color: #a5b4fc; background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 6px; padding: 2px 8px; display: inline-flex; align-items: center; gap: 4px; font-weight: 600; margin-bottom: 4px;">
                        <i class="ph-bold ph-broadcast"></i> <span id="fc-channel-${data.message_id}"></span>
                    </div>
                    <div class="flash-card-title" style="display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 0.9rem;">
                        <i class="ph-duotone ${icon}"></i>
                        <span>New ${mediaBadge} Detected</span>
                    </div>
                </div>
                <div style="font-size: 0.72rem; color: var(--text-muted);">${dateStr}</div>
            </div>
            <div class="flash-card-body" style="display: flex; gap: 0.75rem; align-items: center;">
                <img src="/api/thumbnail/${data.message_id}" style="width: 44px; height: 44px; border-radius: 8px; object-fit: cover; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.08); flex-shrink: 0;" onerror="this.style.display='none'">
                <div style="min-width: 0; flex: 1;">
                    <strong style="color: #fff; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.85rem;">
                        <span id="fc-file-${data.message_id}"></span>
                    </strong>
                    <span style="font-size: 0.75rem; color: var(--accent-cyan); font-weight: 600;">${sizeFormatted}</span>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.2rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <em id="fc-text-${data.message_id}"></em>
                    </div>
                </div>
            </div>
            <div class="flash-card-actions" style="margin-top: 0.6rem; display: flex; gap: 0.5rem;">
                <button class="btn secondary-btn" style="flex:1; padding: 0.45rem;" onclick="this.closest('.flash-card').remove()">Dismiss</button>
                <button class="btn primary-btn pulse-hover" style="flex:1.2; padding: 0.45rem;" onclick="downloadFlashCardMedia(${data.message_id}, this)">
                    <i class="ph-bold ph-download-simple"></i> Download
                </button>
            </div>
        `;
        
        card.querySelector(`#fc-channel-${data.message_id}`).textContent = channelName;
        card.querySelector(`#fc-file-${data.message_id}`).textContent = data.filename || `media_${data.message_id}`;
        if (data.text) {
            card.querySelector(`#fc-text-${data.message_id}`).textContent = data.text;
        }
        
        flashCardContainer.appendChild(card);
        
        // Auto remove after 60 seconds if ignored
        setTimeout(() => {
            if (card.parentNode) card.remove();
        }, 60000);
    }

    window.downloadFlashCardMedia = async function(messageId, btnElement) {
        btnElement.disabled = true;
        const origContent = btnElement.innerHTML;
        btnElement.innerHTML = `<i class="ph-bold ph-spinner" style="animation: spin 1s linear infinite;"></i> Downloading...`;
        
        try {
            // Also queue server-side download so file is saved to daemon output_dir
            fetch(`/api/watch/download/${messageId}`, { method: "POST" }).catch(e => console.warn("Server download queue:", e));

            // Trigger browser download without navigating away
            const downloadLink = document.createElement("a");
            downloadLink.href = `/api/stream/${messageId}?download=true`;
            downloadLink.style.display = "none";
            document.body.appendChild(downloadLink);
            downloadLink.click();
            setTimeout(() => {
                if (downloadLink.parentNode) downloadLink.remove();
            }, 1000);
            
            // Update button status
            setTimeout(() => {
                btnElement.disabled = false;
                btnElement.innerHTML = `<i class="ph-bold ph-check"></i> Downloaded`;
            }, 2500);
            
        } catch (error) {
            console.error("Error downloading media:", error);
            btnElement.disabled = false;
            btnElement.innerHTML = origContent;
        }
    };

    // Auto-detect authentication from URL query (CLI login) or saved token
    const urlParams = new URLSearchParams(window.location.search);
    const queryToken = urlParams.get("token");
    const storedToken = localStorage.getItem("teleflow_token") || localStorage.getItem("telegrab_token");
    const effectiveToken = queryToken || storedToken;

    if (effectiveToken) {
        if (queryToken) {
            localStorage.setItem("teleflow_token", queryToken);
            localStorage.setItem("telegrab_token", queryToken);
        }
        document.cookie = `teleflow_jwt=${effectiveToken}; path=/; max-age=${30*24*60*60}; SameSite=Lax`;
        document.cookie = `telegrab_jwt=${effectiveToken}; path=/; max-age=${30*24*60*60}; SameSite=Lax`;
        showPanel("scraper");
    }
});
