(() => {
    if (window.__btRecorderInstalled) {
        return;
    }
    window.__btRecorderInstalled = true;

    const config = Object.assign({ testIdAttributes: ['data-testid'], toolbar: true }, window.__btConfig || {});
    const isTopFrame = window.top === window;
    const pageToken = Math.random().toString(36).slice(2, 10);
    const elementKeys = new WeakMap();
    let elementCounter = 0;
    let mode = 'record';
    let lastEnterTime = 0;
    let toolbarHost = null;
    let highlight = null;

    const PICK_MODES = ['assertVisible', 'assertText', 'assertValue', 'assertChecked', 'hover'];
    const INTERACTIVE = [
        'button', 'a[href]', 'input', 'select', 'textarea', 'summary', 'label', 'option',
        '[role=button]', '[role=link]', '[role=checkbox]', '[role=radio]', '[role=tab]', '[role=menuitem]',
        '[role=option]', '[role=switch]', '[role=combobox]', '[contenteditable=""]', '[contenteditable=true]',
    ].join(',');
    const TEXT_INPUT_TYPES = ['', 'text', 'email', 'password', 'search', 'tel', 'url', 'number', 'date',
        'datetime-local', 'month', 'time', 'week', 'color'];
    const RECORDED_KEYS = ['Enter', 'Escape'];
    const NAVIGATION_KEYS = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown'];

    const emit = (event) => {
        if (typeof window.__btEmit !== 'function') {
            return;
        }
        window.__btEmit(Object.assign({
            time: Date.now(),
            url: location.href,
            topFrame: isTopFrame,
            viewport: { width: window.innerWidth, height: window.innerHeight },
        }, event));
    };

    const normalize = (text) => (text || '').replace(/\s+/g, ' ').trim();

    const elementKey = (element) => {
        if (!elementKeys.has(element)) {
            elementCounter += 1;
            elementKeys.set(element, `${pageToken}:${elementCounter}`);
        }
        return elementKeys.get(element);
    };

    const isTextInput = (element) => {
        if (element instanceof HTMLTextAreaElement) {
            return true;
        }
        if (element instanceof HTMLInputElement) {
            return TEXT_INPUT_TYPES.includes((element.getAttribute('type') || '').toLowerCase());
        }
        return element.isContentEditable === true;
    };

    const isToggle = (element) => element instanceof HTMLInputElement && ['checkbox', 'radio'].includes(element.type);

    const controlOfLabel = (element) => (element instanceof HTMLLabelElement ? element.control : null);

    const isFormControl = (element) =>
        element instanceof HTMLInputElement || element instanceof HTMLSelectElement
        || element instanceof HTMLTextAreaElement || ['textbox', 'combobox', 'searchbox', 'spinbutton', 'checkbox',
            'radio', 'switch', 'slider', 'listbox'].includes(element.getAttribute('role') || '');

    const textOfIds = (ids) => normalize(ids.split(/\s+/).map((id) => {
        const node = document.getElementById(id);
        return node ? node.textContent : '';
    }).join(' '));

    const labelText = (element) => {
        if (!isFormControl(element)) {
            return '';
        }
        const labelledBy = element.getAttribute('aria-labelledby');
        if (labelledBy) {
            return textOfIds(labelledBy);
        }
        const ariaLabel = element.getAttribute('aria-label');
        if (ariaLabel) {
            return normalize(ariaLabel);
        }
        if (element.labels && element.labels.length > 0) {
            return normalize(element.labels[0].innerText || element.labels[0].textContent);
        }
        return '';
    };

    const implicitRole = (element) => {
        const tag = element.localName;
        const type = (element.getAttribute('type') || '').toLowerCase();
        if (tag === 'a' && element.hasAttribute('href')) return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'input') {
            if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
            if (type === 'checkbox') return 'checkbox';
            if (type === 'radio') return 'radio';
            if (type === 'search') return element.hasAttribute('list') ? 'combobox' : 'searchbox';
            if (type === 'number') return 'spinbutton';
            if (type === 'range') return 'slider';
            if (['', 'text', 'email', 'tel', 'url'].includes(type)) {
                return element.hasAttribute('list') ? 'combobox' : 'textbox';
            }
            return '';
        }
        if (tag === 'select') return element.multiple || element.size > 1 ? 'listbox' : 'combobox';
        if (tag === 'textarea') return 'textbox';
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'img' && element.getAttribute('alt')) return 'img';
        if (tag === 'option') return 'option';
        if (tag === 'summary') return '';
        return '';
    };

    const roleOf = (element) => {
        const explicit = (element.getAttribute('role') || '').trim().split(/\s+/)[0];
        return explicit || implicitRole(element);
    };

    const NAME_FROM_CONTENT = ['button', 'link', 'heading', 'option', 'tab', 'menuitem', 'checkbox', 'radio',
        'switch', 'cell', 'row', 'treeitem', 'listitem'];

    const accessibleName = (element, role) => {
        const labelledBy = element.getAttribute('aria-labelledby');
        if (labelledBy) return textOfIds(labelledBy);
        const ariaLabel = element.getAttribute('aria-label');
        if (ariaLabel) return normalize(ariaLabel);
        if (element.labels && element.labels.length > 0) {
            return normalize(Array.from(element.labels).map((label) => label.innerText || label.textContent).join(' '));
        }
        if (element instanceof HTMLInputElement && ['button', 'submit', 'reset'].includes(element.type)) {
            return normalize(element.value);
        }
        if (element.localName === 'img' || (element instanceof HTMLInputElement && element.type === 'image')) {
            return normalize(element.getAttribute('alt'));
        }
        if (NAME_FROM_CONTENT.includes(role)) {
            const text = normalize(element.innerText || element.textContent);
            if (text) return text;
            const image = element.querySelector('img[alt]');
            if (image) return normalize(image.getAttribute('alt'));
        }
        return normalize(element.getAttribute('title') || element.getAttribute('placeholder') || '');
    };

    const looksGenerated = (id) => /\d{3,}|:|^(wire|headlessui|radix|react|mui|ember|select2)[-_]?/i.test(id)
        || /[-_]\d+$/.test(id);

    const attributeSelector = (name, value) =>
        `[${CSS.escape(name)}="${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"]`;

    const testAttribute = (element, configured) => {
        if (element.hasAttribute(configured)) {
            return configured;
        }
        const modifiers = Array.from(element.attributes).find((attribute) => attribute.name.startsWith(`${configured}.`));
        return modifiers ? modifiers.name : null;
    };

    const testAttributes = (element) => config.testIdAttributes
        .map((configured) => testAttribute(element, configured))
        .filter((name) => name && element.getAttribute(name));

    const isUnique = (selector, element) => {
        try {
            const matches = document.querySelectorAll(selector);
            return matches.length === 1 && matches[0] === element;
        } catch (error) {
            return false;
        }
    };

    const cssPath = (element) => {
        const parts = [];
        let node = element;
        while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
            if (node !== element) {
                const anchorAttribute = testAttributes(node).find((name) => name !== 'name');
                if (anchorAttribute) {
                    parts.unshift(attributeSelector(anchorAttribute, node.getAttribute(anchorAttribute)));
                    break;
                }
                if (node.id && !looksGenerated(node.id)) {
                    parts.unshift(`#${CSS.escape(node.id)}`);
                    break;
                }
            }
            let part = CSS.escape(node.localName);
            const parent = node.parentElement;
            if (parent) {
                const siblings = Array.from(parent.children).filter((child) => child.localName === node.localName);
                if (siblings.length > 1) {
                    part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                }
            }
            parts.unshift(part);
            const selector = parts.join(' > ');
            if (isUnique(selector, element)) {
                return selector;
            }
            node = parent;
        }
        const selector = parts.join(' > ');
        return isUnique(selector, element) ? selector : '';
    };

    const candidates = (element) => {
        const list = [];
        for (const attribute of testAttributes(element)) {
            const value = element.getAttribute(attribute);
            if (value) {
                list.push({ kind: 'test_id', attribute, value, unique: isUnique(attributeSelector(attribute, value), element) });
            }
        }
        if (element.id) {
            list.push({ kind: 'id', value: element.id, unique: isUnique(attributeSelector('id', element.id), element) });
        }
        const label = labelText(element);
        if (label) {
            list.push({ kind: 'label', value: label });
        }
        const role = roleOf(element);
        if (role) {
            const name = accessibleName(element, role);
            if (name && name.length <= 80) {
                list.push({ kind: 'role', role, value: name });
            }
        }
        const placeholder = element.getAttribute('placeholder');
        if (placeholder) {
            list.push({ kind: 'placeholder', value: normalize(placeholder) });
        }
        const css = cssPath(element);
        if (css) {
            list.push({ kind: 'css', value: css, unique: true });
        }
        return list;
    };

    const describeElement = (element) => ({
        key: elementKey(element),
        tag: element.localName,
        candidates: candidates(element),
    });

    const eventElement = (event) => {
        const path = event.composedPath ? event.composedPath() : [event.target];
        if (toolbarHost && path.includes(toolbarHost)) {
            return null;
        }
        const first = path.find((node) => node instanceof Element);
        return first || null;
    };

    const retarget = (element) => element.closest(INTERACTIVE) || element;

    const modifiersOf = (event) => ['Alt', 'Control', 'Meta', 'Shift'].filter((name) => event.getModifierState(name));

    const setMode = (next) => {
        mode = next;
        renderToolbar();
        if (!PICK_MODES.includes(mode)) {
            hideHighlight();
        }
        if (typeof window.__btSetMode === 'function') {
            window.__btSetMode(next);
        }
    };

    const blockInPickMode = (event) => {
        if (!PICK_MODES.includes(mode) || !eventElement(event)) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
    };

    const pick = (element) => {
        const target = describeElement(element);
        if (mode === 'assertVisible') {
            emit({ type: 'assertVisible', target });
        }
        if (mode === 'assertText') {
            emit({ type: 'assertText', target, value: normalize(element.innerText || element.textContent).slice(0, 200) });
        }
        if (mode === 'assertValue') {
            emit({ type: 'assertValue', target, value: 'value' in element ? String(element.value) : '' });
        }
        if (mode === 'assertChecked') {
            emit({ type: 'assertChecked', target, checked: Boolean(element.checked) });
        }
        if (mode === 'hover') {
            emit({ type: 'hover', target });
        }
        setMode('record');
    };

    const onClick = (event) => {
        const raw = eventElement(event);
        if (!raw) {
            return;
        }
        if (PICK_MODES.includes(mode)) {
            blockInPickMode(event);
            pick(mode === 'hover' ? retarget(raw) : raw);
            return;
        }
        if (mode !== 'record' || event.isTrusted === false) {
            return;
        }
        const element = retarget(raw);
        if (element === document.documentElement || element === document.body) {
            return;
        }
        if (isToggle(element) || element instanceof HTMLSelectElement || element instanceof HTMLOptionElement) {
            return;
        }
        if (element instanceof HTMLInputElement && element.type === 'file') {
            return;
        }
        const control = controlOfLabel(element);
        if (control && (isToggle(control) || (control instanceof HTMLInputElement && control.type === 'file'))) {
            return;
        }
        if (event.detail > 1) {
            return;
        }
        if (event.detail === 0 && Date.now() - lastEnterTime < 500) {
            return;
        }
        emit({ type: 'click', target: describeElement(element), button: event.button, modifiers: modifiersOf(event) });
    };

    const onDoubleClick = (event) => {
        const raw = eventElement(event);
        if (!raw || mode !== 'record' || event.isTrusted === false) {
            return;
        }
        const element = retarget(raw);
        if (isTextInput(element)) {
            return;
        }
        emit({ type: 'dblclick', target: describeElement(element) });
    };

    const onInput = (event) => {
        const element = eventElement(event);
        if (!element || mode !== 'record' || !isTextInput(element)) {
            return;
        }
        const sensitive = element instanceof HTMLInputElement && element.type === 'password';
        const value = element.isContentEditable ? element.innerText : element.value;
        emit({
            type: 'fill',
            target: describeElement(element),
            value: sensitive ? '' : value,
            sensitive,
            secretValue: sensitive ? value : undefined,
        });
    };

    const onChange = (event) => {
        const element = eventElement(event);
        if (!element || mode !== 'record') {
            return;
        }
        if (element instanceof HTMLSelectElement) {
            const values = Array.from(element.selectedOptions).map((option) => option.value);
            emit({ type: 'selectOption', target: describeElement(element), value: values.join(',') });
            return;
        }
        if (isToggle(element)) {
            emit({ type: element.checked ? 'check' : 'uncheck', target: describeElement(element) });
            return;
        }
        if (element instanceof HTMLInputElement && element.type === 'file') {
            const names = Array.from(element.files || []).map((file) => file.name);
            emit({ type: 'setInputFiles', target: describeElement(element), value: names.join(',') });
        }
    };

    const onKeyDown = (event) => {
        if (PICK_MODES.includes(mode) && event.key === 'Escape') {
            setMode('record');
            return;
        }
        const element = eventElement(event);
        if (!element || mode !== 'record' || event.isTrusted === false || event.repeat) {
            return;
        }
        if (event.key === 'Enter') {
            lastEnterTime = Date.now();
        }
        const inText = isTextInput(element);
        const recorded = RECORDED_KEYS.includes(event.key) || (!inText && NAVIGATION_KEYS.includes(event.key));
        if (!recorded) {
            return;
        }
        const modifiers = modifiersOf(event).filter((name) => name !== event.key);
        emit({ type: 'press', target: describeElement(element), value: [...modifiers, event.key].join('+') });
    };

    const showHighlight = (element) => {
        if (!highlight) {
            return;
        }
        const box = element.getBoundingClientRect();
        Object.assign(highlight.style, {
            display: 'block',
            left: `${box.left}px`,
            top: `${box.top}px`,
            width: `${box.width}px`,
            height: `${box.height}px`,
        });
    };

    const hideHighlight = () => {
        if (highlight) {
            highlight.style.display = 'none';
        }
    };

    const onMouseOver = (event) => {
        if (!PICK_MODES.includes(mode)) {
            return;
        }
        const element = eventElement(event);
        if (element) {
            showHighlight(mode === 'hover' ? retarget(element) : element);
        }
    };

    const ICONS = {
        record: '<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>',
        assertVisible: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
        assertText: '<path d="M4 7V5h16v2"/><path d="M9 19h6"/><path d="M12 5v14"/>',
        assertValue: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 12h.01"/><path d="M11 12h6"/>',
        assertChecked: '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 12 3 3 5-6"/>',
        hover: '<path d="m4 4 7 17 2.5-7.5L21 11Z"/>',
    };
    const BUTTONS = [
        ['record', 'Record', 'Record clicks and typing'],
        ['assertVisible', 'Visible', 'Assert that an element is visible'],
        ['assertText', 'Text', 'Assert the text of an element'],
        ['assertValue', 'Value', 'Assert the value of a field'],
        ['assertChecked', 'Checked', 'Assert that a checkbox is checked'],
        ['hover', 'Hover', 'Record hovering over an element'],
    ];
    const iconSvg = (name) => `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;

    let toolbarRoot = null;

    const renderToolbar = () => {
        if (!toolbarRoot) {
            return;
        }
        for (const button of toolbarRoot.querySelectorAll('button[data-mode]')) {
            button.classList.toggle('active', button.dataset.mode === mode);
        }
        toolbarRoot.querySelector('.bar').classList.toggle('picking', PICK_MODES.includes(mode));
    };

    const makeDraggable = (bar, grip) => {
        grip.addEventListener('pointerdown', (event) => {
            const box = bar.getBoundingClientRect();
            const offsetX = event.clientX - box.left;
            const offsetY = event.clientY - box.top;
            const move = (moveEvent) => {
                Object.assign(bar.style, {
                    left: `${moveEvent.clientX - offsetX}px`,
                    top: `${moveEvent.clientY - offsetY}px`,
                    bottom: 'auto',
                    transform: 'none',
                });
            };
            const release = () => {
                window.removeEventListener('pointermove', move, true);
                window.removeEventListener('pointerup', release, true);
            };
            window.addEventListener('pointermove', move, true);
            window.addEventListener('pointerup', release, true);
        });
    };

    const installToolbar = () => {
        if (!isTopFrame || !config.toolbar || toolbarHost || !document.documentElement) {
            return;
        }
        toolbarHost = document.createElement('bt-recorder');
        toolbarRoot = toolbarHost.attachShadow({ mode: 'open' });
        toolbarRoot.innerHTML = `
            <style>
                :host { all: initial; }
                .bar { position: fixed; z-index: 2147483647; bottom: 10px; left: 50%; transform: translateX(-50%);
                    display: flex; align-items: center; gap: 2px; flex-wrap: nowrap; white-space: nowrap;
                    padding: 4px; border-radius: 10px; background: #1d1d26; border: 1px solid #2e2e3b;
                    box-shadow: 0 6px 20px rgba(0,0,0,.35); font: 12px/1 system-ui, sans-serif; }
                .grip { cursor: move; padding: 6px 4px; color: #6b6b7b; user-select: none; }
                button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
                    padding: 6px 8px; border-radius: 7px; color: #d7dae0; }
                button:hover { background: #2e2e3b; }
                button.active { background: #7c3aed; color: #fff; }
                button[data-mode=record] svg { color: #f87171; }
                button[data-mode=record].active svg { color: #fff; }
                .hint { display: none; color: #c4b5fd; padding: 6px 6px 6px 4px; }
                .bar.picking .hint { display: inline; }
                @media (max-width: 640px) {
                    .label { display: none; }
                    button { padding: 7px; }
                    .bar.picking .hint { display: none; }
                }
                .highlight { position: fixed; z-index: 2147483646; pointer-events: none; display: none;
                    border: 2px solid #8b5cf6; background: rgba(139,92,246,.15); border-radius: 3px; }
            </style>
            <div class="highlight"></div>
            <div class="bar">
                <span class="grip">⠿</span>
                ${BUTTONS.map(([name, label, title]) => `<button data-mode="${name}" title="${title}">${iconSvg(name)}<span class="label">${label}</span></button>`).join('')}
                <span class="hint">Click an element · Esc cancels</span>
            </div>`;
        highlight = toolbarRoot.querySelector('.highlight');
        toolbarRoot.addEventListener('click', (event) => {
            const button = event.target.closest('button[data-mode]');
            if (button) {
                setMode(button.dataset.mode);
            }
        });
        makeDraggable(toolbarRoot.querySelector('.bar'), toolbarRoot.querySelector('.grip'));
        document.documentElement.appendChild(toolbarHost);
        renderToolbar();
    };

    const listen = (type, handler) => window.addEventListener(type, handler, { capture: true });
    listen('click', onClick);
    listen('dblclick', onDoubleClick);
    listen('input', onInput);
    listen('change', onChange);
    listen('keydown', onKeyDown);
    listen('mouseover', onMouseOver);

    let pendingCounter = 0;
    let lastSelectRequest = { element: null, time: 0 };
    window.__btPending = window.__btPending || {};

    const openSelect = (event) => {
        if (!config.viewer || mode !== 'record') {
            return;
        }
        const element = eventElement(event);
        if (!(element instanceof HTMLSelectElement) || element.disabled) {
            return;
        }
        event.preventDefault();
        if (lastSelectRequest.element === element && Date.now() - lastSelectRequest.time < 400) {
            return;
        }
        lastSelectRequest = { element, time: Date.now() };
        pendingCounter += 1;
        const id = `${pageToken}-select-${pendingCounter}`;
        window.__btPending[id] = element;
        const box = element.getBoundingClientRect();
        if (typeof window.__btSelect === 'function') {
            window.__btSelect({
                id,
                multiple: element.multiple,
                x: box.left,
                y: box.bottom,
                options: Array.from(element.options).map((option) => ({
                    value: option.value,
                    label: normalize(option.label || option.textContent),
                    selected: option.selected,
                    disabled: option.disabled,
                })),
            });
        }
    };
    listen('mousedown', openSelect);
    listen('touchend', openSelect);

    let lastCursor = '';
    const cursorOf = (element) => {
        if (!(element instanceof Element)) {
            return 'default';
        }
        const cursor = getComputedStyle(element).cursor;
        if (cursor === 'auto') {
            return isTextInput(element) ? 'text' : 'default';
        }
        return cursor;
    };
    window.addEventListener('mousemove', (event) => {
        if (!config.viewer || typeof window.__btCursor !== 'function') {
            return;
        }
        const cursor = cursorOf(eventElement(event));
        if (cursor !== lastCursor) {
            lastCursor = cursor;
            window.__btCursor(cursor);
        }
    }, { capture: true, passive: true });
    for (const type of ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'auxclick']) {
        listen(type, blockInPickMode);
    }

    let resizeTimer = null;
    const reportViewport = () => {
        if (isTopFrame) {
            emit({ type: 'viewport' });
        }
    };
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(reportViewport, 250);
    });

    const start = () => {
        installToolbar();
        reportViewport();
        if (typeof window.__btState === 'function') {
            Promise.resolve(window.__btState()).then((state) => {
                if (state && state.mode) {
                    mode = state.mode;
                    renderToolbar();
                }
            }).catch(() => {});
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
        start();
    }
})();
