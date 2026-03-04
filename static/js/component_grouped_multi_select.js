/*
 * Grouped multi-select custom component for plugin configuration.
 * Renders a searchable, grouped checkbox grid with select-all controls.
 * Depends on component_common.js for registries and componentState.
 *
 * Config shape expected from plugin metadata:
 *   config.items  — Object mapping display name to value (e.g., {"Ukraine": 0, "Syria": 3})
 *   config.groups — Object mapping group name to array of item names
 */

// Render grouped multi-select component
componentRenderers['grouped_multi_select'] = function(pluginType, component) {
    const {field_name, title, icon, help_text, config} = component;
    const sectionId = `${pluginType}-${field_name}-section`;
    const hiddenInputId = `${pluginType}_plugin_${field_name}`;
    const items = config.items || {};
    const groups = config.groups || {};
    const cardStyle = window.componentCardStyle ? ` style="${window.componentCardStyle}"` : '';

    // Build grouped checkbox HTML
    let groupsHTML = '';
    Object.entries(groups).forEach(([groupName, itemNames]) => {
        const groupId = `${pluginType}-${field_name}-group-${groupName.replace(/[^a-zA-Z0-9]/g, '_')}`;
        let checkboxesHTML = '';
        itemNames.forEach(name => {
            const itemValue = items[name];
            if (itemValue !== undefined) {
                const checkboxId = `${pluginType}-${field_name}-item-${itemValue}`;
                checkboxesHTML += `
                    <div class="col-lg-3 col-md-4 col-sm-6">
                        <div class="form-check">
                            <input class="form-check-input multi-select-checkbox" type="checkbox"
                                   id="${checkboxId}" value="${itemValue}"
                                   data-item-name="${name}" data-group="${groupId}"
                                   onchange="serializeMultiSelect('${pluginType}', '${field_name}')">
                            <label class="form-check-label" for="${checkboxId}">${name}</label>
                        </div>
                    </div>
                `;
            }
        });
        groupsHTML += `
            <div class="mb-3" id="${groupId}">
                <div class="d-flex justify-content-between align-items-center mb-2 border-bottom pb-1">
                    <h6 class="mb-0"><i class="fas fa-folder-open me-1"></i>${groupName}</h6>
                    <div>
                        <button type="button" class="btn btn-sm btn-outline-primary me-1"
                                onclick="selectGroupMultiSelect('${pluginType}', '${field_name}', '${groupId}', true)">
                            Select All
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary"
                                onclick="selectGroupMultiSelect('${pluginType}', '${field_name}', '${groupId}', false)">
                            Clear
                        </button>
                    </div>
                </div>
                <div class="row g-1">${checkboxesHTML}</div>
            </div>
        `;
    });

    return `
        <div id="${sectionId}" class="card mb-3"${cardStyle}>
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">
                    <i class="fas ${icon}"></i>
                    ${title}
                    <span id="${pluginType}-${field_name}-count" class="badge bg-primary ms-2">0 selected</span>
                </h5>
                <div>
                    <button type="button" class="btn btn-sm btn-outline-primary me-1"
                            onclick="selectAllMultiSelect('${pluginType}', '${field_name}', true)">
                        <i class="fas fa-check-double"></i> Select All
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary"
                            onclick="selectAllMultiSelect('${pluginType}', '${field_name}', false)">
                        <i class="fas fa-times"></i> Clear All
                    </button>
                </div>
            </div>
            <div class="card-body">
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    ${help_text}
                </div>
                <div class="mb-3">
                    <input type="text" class="form-control" placeholder="Search..."
                           id="${pluginType}-${field_name}-search"
                           oninput="filterMultiSelect('${pluginType}', '${field_name}', this.value)">
                </div>
                ${groupsHTML}
                <input type="hidden" id="${hiddenInputId}" name="plugin_${field_name}" value="[]">
            </div>
        </div>
    `;
};

// Serialize selected checkboxes to hidden input
function serializeMultiSelect(pluginType, fieldName) {
    const hiddenInputId = `${pluginType}_plugin_${fieldName}`;
    const hiddenInput = document.getElementById(hiddenInputId);
    if (!hiddenInput) return;

    const checkboxes = document.querySelectorAll(`#${pluginType}-${fieldName}-section .multi-select-checkbox:checked`);
    const selectedValues = Array.from(checkboxes).map(cb => parseInt(cb.value));
    hiddenInput.value = JSON.stringify(selectedValues);

    // Update count badge
    const countBadge = document.getElementById(`${pluginType}-${fieldName}-count`);
    if (countBadge) {
        countBadge.textContent = `${selectedValues.length} selected`;
    }
}

// Select/deselect all items globally
function selectAllMultiSelect(pluginType, fieldName, checked) {
    const section = document.getElementById(`${pluginType}-${fieldName}-section`);
    if (!section) return;
    // Only toggle visible (non-filtered) checkboxes
    section.querySelectorAll('.multi-select-checkbox').forEach(cb => {
        if (cb.closest('.col-lg-3').style.display !== 'none') {
            cb.checked = checked;
        }
    });
    serializeMultiSelect(pluginType, fieldName);
}

// Select/deselect all items within a group
function selectGroupMultiSelect(pluginType, fieldName, groupId, checked) {
    const group = document.getElementById(groupId);
    if (!group) return;
    group.querySelectorAll('.multi-select-checkbox').forEach(cb => {
        if (cb.closest('.col-lg-3').style.display !== 'none') {
            cb.checked = checked;
        }
    });
    serializeMultiSelect(pluginType, fieldName);
}

// Filter items by search text
function filterMultiSelect(pluginType, fieldName, searchText) {
    const section = document.getElementById(`${pluginType}-${fieldName}-section`);
    if (!section) return;
    const term = searchText.toLowerCase();
    section.querySelectorAll('.multi-select-checkbox').forEach(cb => {
        const name = cb.getAttribute('data-item-name').toLowerCase();
        const col = cb.closest('.col-lg-3');
        if (col) {
            col.style.display = name.includes(term) ? '' : 'none';
        }
    });
}

// Validate grouped multi-select — at least one item must be selected
componentValidators['grouped_multi_select'] = function(pluginType, component) {
    const hiddenInputId = `${pluginType}_plugin_${component.field_name}`;
    const hiddenInput = document.getElementById(hiddenInputId);
    if (!hiddenInput) return true;

    try {
        const selected = JSON.parse(hiddenInput.value);
        if (!Array.isArray(selected) || selected.length === 0) {
            alert(`${component.title}: At least one item must be selected.`);
            return false;
        }
    } catch (e) {
        alert(`${component.title}: At least one item must be selected.`);
        return false;
    }
    return true;
};
