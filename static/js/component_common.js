/*
 * Shared component infrastructure for plugin custom UI components.
 * Provides registries, rendering dispatch, and validation dispatch.
 * Templates set window.componentCardStyle before loading this file.
 */

// Component registry for custom UI components
const componentRenderers = {};
const componentValidators = {};
const componentState = {};

// Default card style — templates override before this file loads
if (typeof window.componentCardStyle === 'undefined') {
    window.componentCardStyle = '';
}

// Main function to render custom components for a plugin
function renderCustomComponents(pluginType, components) {
    const container = document.getElementById('plugin-custom-components');
    if (!container) return;

    container.innerHTML = '';

    if (!components || components.length === 0) {
        return;
    }

    // Initialize component state for this plugin if not exists
    if (!componentState[pluginType]) {
        componentState[pluginType] = {};
    }

    components.forEach(component => {
        const renderer = componentRenderers[component.type];
        if (renderer) {
            const componentHTML = renderer(pluginType, component);
            container.insertAdjacentHTML('beforeend', componentHTML);

            // Initialize component state if needed
            if (!componentState[pluginType][component.field_name]) {
                componentState[pluginType][component.field_name] = [];
            }
        } else {
            console.warn(`No renderer found for component type: ${component.type}`);
        }
    });
}

// Validate all custom components for a plugin
function validateCustomComponents(pluginType) {
    const metadata = pluginMetadata[pluginType];
    if (!metadata || !metadata.custom_components) {
        return true;
    }

    for (const component of metadata.custom_components) {
        const validator = componentValidators[component.type];
        if (validator && !validator(pluginType, component)) {
            return false;
        }
    }
    return true;
}
