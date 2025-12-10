// Utility
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);

// Upload Page Logic
if ($("#upload-form")) {
    const dropzone = $("#dropzone");
    const fileInput = $("#file-input");
    const form = $("#upload-form");
    const progressContainer = $("#ocr-progress");
    const progressFill = $("#progress-fill");

    // Drag & Drop
    dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("drag-over");
    });

    dropzone.addEventListener("dragleave", () => {
        dropzone.classList.remove("drag-over");
    });

    // Use a DataTransfer to hold files (simulating cumulative selection)
    const dataTransfer = new DataTransfer();

    function updateFileList() {
        // Update input files
        fileInput.files = dataTransfer.files;

        // Update UI
        const listContainer = $("#file-list");
        listContainer.innerHTML = "";

        if (dataTransfer.files.length === 0) {
            $("#file-name").textContent = "";
            return;
        }

        const ul = document.createElement("ul");
        ul.style.listStyle = "none";
        ul.style.padding = "0";

        Array.from(dataTransfer.files).forEach((file, index) => {
            const li = document.createElement("li");
            li.style.background = "#f8f9fa";
            li.style.margin = "5px 0";
            li.style.padding = "10px";
            li.style.borderRadius = "4px";
            li.style.display = "flex";
            li.style.justifyContent = "space-between";
            li.style.alignItems = "center";

            li.innerHTML = `
                <span>📄 ${file.name} <small style='color:#666'>(${Math.round(file.size / 1024)}KB)</small></span>
                <button type="button" class="btn btn-sm" style="color:red; padding:2px 5px;" onclick="removeFile(${index})">✕</button>
            `;
            ul.appendChild(li);
        });

        listContainer.appendChild(ul);
        $("#file-name").textContent = `${dataTransfer.files.length} file selezionati`;
    }

    // Global function to remove file
    window.removeFile = (index) => {
        const dt = new DataTransfer();
        const files = dataTransfer.files;
        for (let i = 0; i < files.length; i++) {
            if (i !== index) dt.items.add(files[i]);
        }
        dataTransfer.items.clear();
        Array.from(dt.files).forEach(f => dataTransfer.items.add(f));
        updateFileList();
    };

    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("drag-over");
        if (e.dataTransfer.files.length) {
            Array.from(e.dataTransfer.files).forEach(file => {
                if (file.type === "application/pdf" || file.type.startsWith("image/")) {
                    dataTransfer.items.add(file);
                }
            });
            updateFileList();
        }
    });

    // Handle standard input change
    fileInput.addEventListener("change", () => {
        if (fileInput.files.length) {
            Array.from(fileInput.files).forEach(file => {
                // Check duplicates? For now just add.
                dataTransfer.items.add(file);
            });
            updateFileList();
        }
    });

    dropzone.addEventListener("click", () => fileInput.click());

    // Form Submit
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!fileInput.files.length) return alert("Seleziona un file");

        const formData = new FormData(form);
        const btn = form.querySelector("button[type=submit]");
        btn.disabled = true;
        btn.textContent = "Conversione in corso...";
        progressContainer.style.display = "block";

        // Simulated progress
        let width = 0;
        const interval = setInterval(() => {
            if (width >= 90) clearInterval(interval);
            width += 5;
            progressFill.style.width = width + "%";
        }, 500);

        try {
            const response = await fetch("/upload", {
                method: "POST",
                body: formData
            });

            if (response.ok) {
                const data = await response.json();
                console.log("Upload Success:", data);

                let target = "/masking";

                if (data.document_ids && Array.isArray(data.document_ids) && data.document_ids.length > 0) {
                    const ids = data.document_ids.join(",");
                    target = `/masking?ids=${ids}`;
                } else if (data.document_id) {
                    target = `/masking?ids=${data.document_id}`;
                } else {
                    alert("Errore: Nessun ID documento restituito dal server.");
                    console.error("Missing IDs in response:", data);
                    btn.disabled = false;
                    btn.textContent = "Converti in TXT";
                    clearInterval(interval);
                    return;
                }

                window.location.href = target;
            } else {
                const errData = await response.json().catch(() => ({ detail: "Unknown Error" }));
                throw new Error(errData.detail || "Upload failed");
            }
        } catch (err) {
            console.error("Upload Error:", err);
            alert("Errore durante l'upload: " + err.message);
            btn.disabled = false;
            btn.textContent = "Converti in TXT";
            clearInterval(interval);
        }
    });
}

// Masking Page Logic - Multi Tab Support
if ($("#masking-form")) {
    const skipBtn = $("#skip-masking-btn");
    const modal = $("#confirm-skip-modal");
    const confirmSkipBtn = $("#confirm-skip");
    const cancelSkipBtn = $("#cancel-skip");
    const maskCheckbox = $("#confirm-masking");
    const applyBtn = $("#apply-masking-btn");

    // Tab Switching Logic
    window.switchTab = (docId) => {
        // Update active tab style
        $$('.file-tab').forEach(btn => {
            if (btn.dataset.id == docId) {
                btn.classList.add('active');
                btn.style.background = 'var(--primary)';
                btn.style.color = 'white';
            } else {
                btn.classList.remove('active');
                btn.style.background = '#f8fafc';
                btn.style.color = 'var(--text)';
            }
        });

        // Update current doc ID
        const inputMap = $("#current-doc-id");
        if (inputMap) inputMap.value = docId;

        updatePreview();
    };

    function updatePreview() {
        // Get current active doc ID
        const docId = $("#current-doc-id")?.value;

        let rawText = "";
        let originalText = "";

        // Use optional chaining for safety if element not found
        if (docId) {
            const rawEl = document.getElementById(`raw-text-${docId}`);
            rawText = rawEl ? rawEl.value : "";
            originalText = rawText;
        } else {
            // Fallback
            const rawEl = $("#original-text");
            rawText = rawEl ? rawEl.value : "";
            originalText = rawText;
        }

        let text = rawText;
        let count = 0;

        // Simple search replace logic matching python
        const replaceMap = [
            { id: "polizza", mask: "[POLIZZA_XXX]" },
            { id: "contraente", mask: "[CONTRAENTE_XXX]" },
            { id: "piva", mask: "[PIVA_XXX]" },
            { id: "cf", mask: "[CF_XXX]" },
            { id: "assicurato", mask: "[ASSICURATO_XXX]" }
        ];

        replaceMap.forEach(item => {
            const el = document.getElementById(item.id);
            const val = el ? el.value.trim() : "";
            if (val) {
                const escaped = val.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const re = new RegExp(escaped, 'gi');

                if (text.match(re)) {
                    text = text.replace(re, `<span class="highlight">${item.mask}</span>`);
                    const matches = originalText.match(re);
                    if (matches) count += matches.length;
                }
            }
        });

        const altriTextarea = $("textarea[name='altri']");
        if (altriTextarea) {
            const lines = altriTextarea.value.split('\n');
            lines.forEach((line, idx) => {
                const val = line.trim();
                if (val) {
                    const escaped = val.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                    const re = new RegExp(escaped, 'gi');

                    if (text.match(re)) {
                        text = text.replace(re, `<span class="highlight">[DATO_OSCURATO_${idx + 1}]</span>`);
                        const matches = originalText.match(re);
                        if (matches) count += matches.length;
                    }
                }
            });
        }

        const previewContainer = $("#masked-preview");
        if (previewContainer) previewContainer.innerHTML = text;

        const countSpan = $("#replace-count");
        if (countSpan) countSpan.textContent = count + " (in questo doc)";
    }

    const inputs = $$("input, textarea");
    inputs.forEach(input => input.addEventListener("input", updatePreview));

    if (maskCheckbox) {
        maskCheckbox.addEventListener("change", (e) => {
            if (applyBtn) applyBtn.disabled = !e.target.checked;
        });
    }

    if (skipBtn) {
        skipBtn.addEventListener("click", (e) => {
            e.preventDefault();
            if (modal) modal.style.display = "flex";
        });
    }

    if (cancelSkipBtn) {
        cancelSkipBtn.addEventListener("click", () => {
            if (modal) modal.style.display = "none";
        });
    }

    if (confirmSkipBtn) {
        confirmSkipBtn.addEventListener("click", () => {
            const form = $("#masking-form");
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = "skip_masking";
            hidden.value = "true";
            form.appendChild(hidden);
            form.submit();
        });
    }

    // Init first tab
    setTimeout(() => {
        const firstDocId = $("#current-doc-id")?.value;
        if (firstDocId && window.switchTab) {
            window.switchTab(firstDocId);
        } else {
            updatePreview();
        }
    }, 100);
}

// Analysis Page
if ($("#analysis-form")) {
    const form = $("#analysis-form");
    const progress = $("#analysis-progress");

    form.addEventListener("submit", () => {
        form.querySelector("button").disabled = true;
        progress.style.display = "block";
    });
}
