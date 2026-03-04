/*
 * Message rules custom component for plugin configuration.
 * Provides a rule builder UI with dynamic add/remove/edit of message rules.
 * Depends on component_common.js for registries and componentState.
 */

// Render message rules component
componentRenderers['message_rules'] = function(pluginType, component) {
    const {field_name, title, icon, help_text, config} = component;
    const containerId = `${pluginType}-${field_name}-container`;
    const sectionId = `${pluginType}-${field_name}-section`;
    const noRulesId = `${pluginType}-${field_name}-no-rules`;
    const hiddenInputId = `${pluginType}_plugin_${field_name}`;
    const cardStyle = window.componentCardStyle ? ` style="${window.componentCardStyle}"` : '';

    return `
        <div id="${sectionId}" class="card mb-3"${cardStyle}>
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">
                    <i class="fas ${icon}"></i>
                    ${title}
                </h5>
                <button type="button" class="btn btn-sm btn-primary"
                        onclick="addComponentRule('${pluginType}', '${field_name}')">
                    <i class="fas fa-plus"></i> Add Rule
                </button>
            </div>
            <div class="card-body">
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    ${help_text}
                </div>
                <div id="${containerId}"></div>
                <div id="${noRulesId}" class="text-center text-muted py-4">
                    <i class="fas fa-inbox fa-3x mb-3 opacity-25"></i>
                    <p>No rules defined. Click "Add Rule" to create your first rule.</p>
                </div>
                <input type="hidden" id="${hiddenInputId}" name="plugin_${field_name}" value="[]">
            </div>
        </div>
    `;
};

// Add a new message rule
function addComponentRule(pluginType, fieldName) {
    const component = findComponent(pluginType, fieldName);
    if (!component) return;

    const rule = {
        id: `rule_${Date.now()}`,
        enabled: true
    };

    // Initialize fields from schema
    component.config.rule_fields.forEach(field => {
        rule[field.name] = field.default || '';
    });

    if (!componentState[pluginType][fieldName]) {
        componentState[pluginType][fieldName] = [];
    }
    componentState[pluginType][fieldName].push(rule);
    renderComponentRules(pluginType, fieldName);
}

// Remove a message rule
function removeComponentRule(pluginType, fieldName, ruleId) {
    if (!componentState[pluginType] || !componentState[pluginType][fieldName]) return;

    componentState[pluginType][fieldName] = componentState[pluginType][fieldName].filter(
        rule => rule.id !== ruleId
    );
    renderComponentRules(pluginType, fieldName);
}

// Update a rule field
function updateComponentRule(pluginType, fieldName, ruleId, field, value) {
    if (!componentState[pluginType] || !componentState[pluginType][fieldName]) return;

    const rule = componentState[pluginType][fieldName].find(r => r.id === ruleId);
    if (rule) {
        rule[field] = value;
        serializeComponentRules(pluginType, fieldName);
    }
}

// Render all rules for a component
function renderComponentRules(pluginType, fieldName) {
    const component = findComponent(pluginType, fieldName);
    if (!component) return;

    const containerId = `${pluginType}-${fieldName}-container`;
    const noRulesId = `${pluginType}-${fieldName}-no-rules`;
    const container = document.getElementById(containerId);
    const noRulesMsg = document.getElementById(noRulesId);

    if (!container) return;

    const rules = componentState[pluginType][fieldName] || [];

    if (rules.length === 0) {
        container.innerHTML = '';
        if (noRulesMsg) noRulesMsg.style.display = 'block';
        serializeComponentRules(pluginType, fieldName);
        return;
    }

    if (noRulesMsg) noRulesMsg.style.display = 'none';

    container.innerHTML = rules.map((rule, index) => `
        <div class="card mb-3" id="${pluginType}-${fieldName}-rule-${rule.id}">
            <div class="card-header d-flex justify-content-between align-items-center">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox"
                           id="${pluginType}-${fieldName}-enabled-${rule.id}"
                           ${rule.enabled ? 'checked' : ''}
                           onchange="updateComponentRule('${pluginType}', '${fieldName}', '${rule.id}', 'enabled', this.checked)">
                    <label class="form-check-label fw-bold">
                        Rule ${index + 1}
                    </label>
                </div>
                <button type="button" class="btn btn-sm btn-outline-danger"
                        onclick="removeComponentRule('${pluginType}', '${fieldName}', '${rule.id}')">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
            <div class="card-body">
                ${component.config.rule_fields.map(field => `
                    <div class="mb-3">
                        <label class="form-label">
                            ${field.label}
                            ${field.required ? '<span class="text-danger">*</span>' : ''}
                        </label>
                        ${field.type === 'textarea' ? `
                            <textarea class="form-control"
                                      placeholder="${field.placeholder || ''}"
                                      onchange="updateComponentRule('${pluginType}', '${fieldName}', '${rule.id}', '${field.name}', this.value)"
                                      rows="3">${rule[field.name] || ''}</textarea>
                        ` : `
                            <input type="text" class="form-control"
                                   placeholder="${field.placeholder || ''}"
                                   value="${rule[field.name] || ''}"
                                   onchange="updateComponentRule('${pluginType}', '${fieldName}', '${rule.id}', '${field.name}', this.value)">
                        `}
                        ${field.help ? `<small class="form-text text-muted">${field.help}</small>` : ''}
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');

    serializeComponentRules(pluginType, fieldName);
}

// Serialize rules to hidden input
function serializeComponentRules(pluginType, fieldName) {
    const hiddenInputId = `${pluginType}_plugin_${fieldName}`;
    const hiddenInput = document.getElementById(hiddenInputId);
    if (!hiddenInput) return;

    const rules = componentState[pluginType][fieldName] || [];
    hiddenInput.value = JSON.stringify(rules);
}

// Find a component in plugin metadata
function findComponent(pluginType, fieldName) {
    const metadata = pluginMetadata[pluginType];
    if (!metadata || !metadata.custom_components) return null;

    return metadata.custom_components.find(c => c.field_name === fieldName);
}

// Validate message rules component
componentValidators['message_rules'] = function(pluginType, component) {
    const rules = componentState[pluginType][component.field_name] || [];

    if (rules.length === 0) {
        alert(`${component.title}: At least one rule is required.`);
        return false;
    }

    for (let i = 0; i < rules.length; i++) {
        const rule = rules[i];

        // Check required fields
        for (const field of component.config.rule_fields) {
            if (field.required && (!rule[field.name] || rule[field.name].trim() === '')) {
                alert(`${component.title} - Rule ${i + 1}: ${field.label} is required.`);
                return false;
            }
        }

        // Validate regex patterns (uid_filter field)
        if (rule.uid_filter && rule.uid_filter.trim() !== '') {
            try {
                new RegExp(rule.uid_filter);
            } catch (e) {
                alert(`${component.title} - Rule ${i + 1}: Invalid regex pattern in UID Filter: ${e.message}`);
                return false;
            }
        }
    }

    return true;
};
