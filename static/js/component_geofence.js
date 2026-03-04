/*
 * Geofence custom component for plugin configuration.
 * Provides a Leaflet map with shift+drag rectangle drawing and coordinate inputs.
 * Depends on component_common.js for registries and componentState.
 * Depends on Leaflet.js being loaded by the template.
 */

// Render geofence component
componentRenderers['geofence'] = function(pluginType, component) {
    const {field_name, title, icon, help_text, config} = component;
    const sectionId = `${pluginType}-${field_name}-section`;
    const mapId = `${pluginType}-${field_name}-map`;
    const configDivId = `${pluginType}-${field_name}-config`;
    const cardStyle = window.componentCardStyle ? ` style="${window.componentCardStyle}"` : '';

    return `
        <div id="${sectionId}" class="card mb-3"${cardStyle}>
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="fas ${icon}"></i>
                    ${title}
                </h5>
            </div>
            <div class="card-body">
                <div class="alert alert-info mb-3">
                    <i class="fas fa-info-circle"></i>
                    ${help_text}
                </div>
                <div class="form-check mb-3">
                    <input class="form-check-input" type="checkbox"
                           id="plugin_${field_name}_enabled"
                           name="plugin_${field_name}_enabled"
                           onchange="toggleGeofence('${pluginType}', '${field_name}', this.checked)">
                    <label class="form-check-label">
                        ${config.enable_checkbox_label}
                    </label>
                </div>
                <div id="${configDivId}" style="display: none;">
                    <div class="mb-3">
                        <div id="${mapId}" style="height: 400px; border: 1px solid #dee2e6; border-radius: 0.375rem;"></div>
                        <small class="form-text text-muted">
                            <i class="fas fa-info-circle"></i>
                            Draw a rectangle on the map or enter coordinates manually
                        </small>
                    </div>
                    <div class="row g-2">
                        <div class="col-md-3">
                            <label class="form-label">North</label>
                            <input type="number" step="any" class="form-control"
                                   id="plugin_${field_name}_north"
                                   name="plugin_${field_name}_north"
                                   placeholder="90.0"
                                   onchange="updateGeofenceOnMap('${pluginType}', '${field_name}')">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">South</label>
                            <input type="number" step="any" class="form-control"
                                   id="plugin_${field_name}_south"
                                   name="plugin_${field_name}_south"
                                   placeholder="-90.0"
                                   onchange="updateGeofenceOnMap('${pluginType}', '${field_name}')">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">East</label>
                            <input type="number" step="any" class="form-control"
                                   id="plugin_${field_name}_east"
                                   name="plugin_${field_name}_east"
                                   placeholder="180.0"
                                   onchange="updateGeofenceOnMap('${pluginType}', '${field_name}')">
                        </div>
                        <div class="col-md-3">
                            <label class="form-label">West</label>
                            <input type="number" step="any" class="form-control"
                                   id="plugin_${field_name}_west"
                                   name="plugin_${field_name}_west"
                                   placeholder="-180.0"
                                   onchange="updateGeofenceOnMap('${pluginType}', '${field_name}')">
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
};

// Toggle geofence visibility
function toggleGeofence(pluginType, fieldName, enabled) {
    const component = findComponent(pluginType, fieldName);
    if (!component) return;

    const configDivId = `${pluginType}-${fieldName}-config`;
    const configDiv = document.getElementById(configDivId);

    if (!configDiv) return;

    if (enabled) {
        configDiv.style.display = 'block';
        // Initialize map if not already done
        initGeofenceMap(pluginType, fieldName, component.config);
    } else {
        configDiv.style.display = 'none';
    }
}

// Initialize Leaflet map for geofence
function initGeofenceMap(pluginType, fieldName, config) {
    const mapId = `${pluginType}-${fieldName}-map`;
    const mapKey = `${pluginType}_${fieldName}_map`;

    // Check if map already exists
    if (componentState[mapKey]) {
        return;
    }

    // Create map with world bounds restriction
    const map = L.map(mapId, {
        maxBounds: [[-90, -180], [90, 180]],
        maxBoundsViscosity: 1.0
    }).setView(config.default_center, config.default_zoom);

    // Add tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        noWrap: true
    }).addTo(map);

    // Store map reference
    componentState[mapKey] = {
        map: map,
        rectangle: null
    };

    // Enable shift+drag rectangle drawing
    let isDrawing = false;
    let startLatLng = null;

    map.on('mousedown', function(e) {
        if (e.originalEvent.shiftKey) {
            isDrawing = true;
            startLatLng = e.latlng;

            // Remove existing rectangle if any
            if (componentState[mapKey].rectangle) {
                map.removeLayer(componentState[mapKey].rectangle);
                componentState[mapKey].rectangle = null;
            }
        }
    });

    map.on('mousemove', function(e) {
        if (isDrawing && startLatLng) {
            // Remove temporary rectangle
            if (componentState[mapKey].rectangle) {
                map.removeLayer(componentState[mapKey].rectangle);
            }

            // Draw new temporary rectangle
            const bounds = L.latLngBounds(startLatLng, e.latlng);
            componentState[mapKey].rectangle = L.rectangle(bounds, {
                color: '#3388ff',
                weight: 2,
                fillOpacity: 0.2
            }).addTo(map);
        }
    });

    map.on('mouseup', function(e) {
        if (isDrawing && startLatLng) {
            isDrawing = false;

            // Finalize rectangle
            const bounds = L.latLngBounds(startLatLng, e.latlng);

            // Update input fields with final bounds
            updateGeofenceFromMap(pluginType, fieldName, bounds);

            startLatLng = null;
        }
    });

    // Invalidate size after a short delay to ensure proper rendering
    setTimeout(() => {
        map.invalidateSize();
    }, 100);
}

// Update input fields from map rectangle
function updateGeofenceFromMap(pluginType, fieldName, bounds) {
    // Normalize coordinates
    let north = bounds.getNorth();
    let south = bounds.getSouth();
    let east = bounds.getEast();
    let west = bounds.getWest();

    // Clamp latitude to valid range (-90 to 90)
    north = Math.max(-90, Math.min(90, north));
    south = Math.max(-90, Math.min(90, south));

    // Wrap longitude to valid range (-180 to 180)
    const wrapLongitude = (lon) => {
        while (lon > 180) lon -= 360;
        while (lon < -180) lon += 360;
        return lon;
    };

    east = wrapLongitude(east);
    west = wrapLongitude(west);

    document.getElementById(`plugin_${fieldName}_north`).value = north.toFixed(6);
    document.getElementById(`plugin_${fieldName}_south`).value = south.toFixed(6);
    document.getElementById(`plugin_${fieldName}_east`).value = east.toFixed(6);
    document.getElementById(`plugin_${fieldName}_west`).value = west.toFixed(6);
}

// Update map rectangle from input fields
function updateGeofenceOnMap(pluginType, fieldName) {
    const mapKey = `${pluginType}_${fieldName}_map`;
    const mapState = componentState[mapKey];

    if (!mapState || !mapState.map) return;

    const north = parseFloat(document.getElementById(`plugin_${fieldName}_north`).value);
    const south = parseFloat(document.getElementById(`plugin_${fieldName}_south`).value);
    const east = parseFloat(document.getElementById(`plugin_${fieldName}_east`).value);
    const west = parseFloat(document.getElementById(`plugin_${fieldName}_west`).value);

    if (isNaN(north) || isNaN(south) || isNaN(east) || isNaN(west)) {
        return;
    }

    // Remove existing rectangle
    if (mapState.rectangle) {
        mapState.map.removeLayer(mapState.rectangle);
    }

    // Create new rectangle
    const bounds = [[south, west], [north, east]];
    mapState.rectangle = L.rectangle(bounds, {
        color: '#3388ff',
        weight: 2,
        fillOpacity: 0.2
    }).addTo(mapState.map);

    // Fit map to bounds
    mapState.map.fitBounds(bounds);
}

// Validate geofence component
componentValidators['geofence'] = function(pluginType, component) {
    const enabled = document.getElementById(`plugin_${component.field_name}_enabled`);

    if (!enabled || !enabled.checked) {
        return true;  // Not enabled, no validation needed
    }

    const north = parseFloat(document.getElementById(`plugin_${component.field_name}_north`).value);
    const south = parseFloat(document.getElementById(`plugin_${component.field_name}_south`).value);
    const east = parseFloat(document.getElementById(`plugin_${component.field_name}_east`).value);
    const west = parseFloat(document.getElementById(`plugin_${component.field_name}_west`).value);

    if (isNaN(north) || isNaN(south) || isNaN(east) || isNaN(west)) {
        alert(`${component.title}: All coordinate fields are required when geofence is enabled.`);
        return false;
    }

    if (north < -90 || north > 90 || south < -90 || south > 90) {
        alert(`${component.title}: Latitude values must be between -90 and 90.`);
        return false;
    }

    if (east < -180 || east > 180 || west < -180 || west > 180) {
        alert(`${component.title}: Longitude values must be between -180 and 180.`);
        return false;
    }

    if (north <= south) {
        alert(`${component.title}: North latitude must be greater than South latitude.`);
        return false;
    }

    return true;
};
