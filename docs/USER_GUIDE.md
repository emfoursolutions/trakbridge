# TrakBridge User Guide

## Overview

This guide covers day-to-day operations for TrakBridge end users, including creating and managing streams, monitoring data flow, and understanding the plugin categorization system. This guide assumes TrakBridge has been installed and configured by your system administrator.

## Getting Started

### Logging In

1. **Navigate to TrakBridge** in your web browser
2. **Enter credentials** provided by your administrator
3. **Change password** if prompted (first-time login)
4. **Verify access level** - your available features depend on your assigned role

### User Roles and Permissions

#### Viewer Role
- View existing streams and their status
- Monitor TAK server connections
- Access read-only dashboards and reports
- Cannot create, edit, or delete resources

#### User Role
- All Viewer permissions
- Create and manage their own streams
- Edit personal profile and change password
- Cannot manage other users or system settings

#### Operator Role
- All User permissions  
- Manage all streams (create, edit, delete)
- Manage TAK server configurations
- Cannot manage users or access admin settings

#### Admin Role
- Full system access
- User management and role assignment
- System configuration and settings
- Complete administrative control

## Understanding Plugin Categories

TrakBridge organizes data sources into categories to simplify selection and management:

### OSINT (Open Source Intelligence)
**Purpose**: Intelligence platforms and open-source data feeds
**Examples**: 
- **Deepstate**: Battlefield intelligence and situational awareness data

**Use Cases**:
- Situational awareness from public sources
- Intelligence gathering and analysis
- Real-time battlefield or crisis monitoring

### Tracker (GPS and Satellite Devices)
**Purpose**: GPS tracking devices and location services
**Examples**:
- **Garmin InReach**: Satellite communicators and GPS devices
- **SPOT Tracker**: GPS tracking devices and emergency communicators
- **Traccar**: Open-source GPS tracking server platform

**Use Cases**:
- Personnel and asset tracking
- Fleet management and monitoring
- Emergency response and rescue operations

### EMS (Emergency Management Systems)  
**Purpose**: Emergency management and response systems
**Status**: Available for future expansion
**Planned Examples**: Emergency dispatch systems, first responder networks

**Use Cases**:
- Emergency response coordination
- First responder tracking and management
- Crisis communication and coordination

## Creating Data Streams

### Stream Creation Workflow

#### Step 1: Navigate to Stream Creation
1. **Click "Create Stream"** from the main dashboard
2. **Select data source category** from the dropdown (OSINT, Tracker, EMS)
3. **Choose specific provider** from the filtered list

#### Step 2: Configure Basic Settings
1. **Stream Name**: Enter descriptive name (e.g., "Team Alpha GPS", "Battlefield Intel Feed")
2. **Description**: Optional detailed description for documentation
3. **TAK Server**: Select destination TAK server from configured options
4. **Active Status**: Enable stream to start data flow immediately

#### Step 3: Provider-Specific Configuration

##### Garmin InReach Configuration
```
Username: Your Garmin InReach username
Password: Your Garmin InReach password  
Share Page URL: Your public share page URL (optional)
Refresh Interval: Data polling frequency (default: 300 seconds)
```

**Setup Requirements**:
- Active Garmin InReach subscription with sharing enabled
- Share page must be set to public if using URL method
- Valid credentials for API access

##### SPOT Tracker Configuration
```
Feed ID: Your SPOT shared page feed ID
Refresh Interval: Data polling frequency (default: 300 seconds)
```

**Setup Requirements**:
- SPOT device with active subscription
- Shared page enabled in SPOT account
- Feed ID from shared page URL

##### Deepstate OSINT Configuration
```
API URL: Deepstate API endpoint (default provided)
Refresh Interval: Data polling frequency (default: 600 seconds)
COT Type Mode: How to handle different data types
```

**Setup Requirements**:
- No authentication required (public API)
- Internet connectivity to Deepstate servers
- Understanding of OSINT data types and sources

##### Traccar Configuration
```
Server URL: Your Traccar server URL
Username: Traccar account username
Password: Traccar account password
Device IDs: Specific devices to track (optional)
Refresh Interval: Data polling frequency (default: 300 seconds)
```

**Setup Requirements**:
- Access to Traccar server installation
- Valid user account with device access
- Server configured for API access

#### Step 4: Configure Custom Callsigns (Tracker Plugins Only)
*Available for: Garmin InReach, SPOT Tracker, Traccar*

1. **Enable Callsign Mapping** (optional): Check "Enable custom callsign mapping" to assign meaningful names to individual trackers
2. **Select Identifier Field**: Choose which field to use for tracker identification (IMEI, device name, etc.)
3. **Discover Trackers**: System automatically discovers available trackers and displays them in a table
4. **Assign Callsigns**: Edit the "Assigned Callsign" field for each tracker with meaningful names (e.g., "Alpha-1", "Bravo-Team-Lead")
5. **Set Per-Tracker COT Types** (optional): Override the stream COT type for specific trackers if needed
6. **Configure Error Handling**: Choose fallback behavior for unmapped trackers

**Callsign Mapping Benefits**:
- **Meaningful Identifiers**: Use "Alpha-1" instead of "IMEI:123456789"
- **Flexible COT Types**: Different tracker types can have different COT classifications
- **Auto-Discovery**: New trackers automatically detected and can be assigned callsigns
- ⚡ **Zero Performance Impact**: When disabled, works exactly like before

#### Step 5: Test and Validate
1. **Click "Test Connection"** to verify configuration
2. **Review test results** for any error messages
3. **Test callsign discovery** if callsign mapping is enabled
4. **Correct any configuration issues** before saving
5. **Save stream** once test passes successfully

### Stream Configuration Best Practices

#### Naming Conventions
- Use descriptive names that indicate purpose and source
- Include team, unit, or operational context
- Examples: "Alpha_Team_InReach", "Command_Post_SPOT", "Intel_Feed_Ukraine"

#### Refresh Intervals
- **GPS Trackers**: 300-600 seconds (5-10 minutes) for normal operations
- **OSINT Sources**: 600-1800 seconds (10-30 minutes) for intelligence feeds
- **Emergency Operations**: 60-300 seconds (1-5 minutes) for critical situations
- **Consider server load**: More frequent updates require more system resources

#### Security Considerations
- Use strong, unique passwords for device accounts
- Regularly rotate credentials according to security policy
- Enable two-factor authentication where supported
- Avoid sharing credentials between multiple streams

## Managing Existing Streams

### Stream Status Monitoring

#### Dashboard Overview
The main dashboard shows all streams with key status indicators:

- **Green Circle**: Stream running normally, data flowing
- **Yellow Warning**: Stream active but with warnings or errors
- **Red Error**: Stream failed or stopped, requires attention
- **Gray Inactive**: Stream disabled or not started

#### Detailed Stream Information
Click any stream to view detailed information:

- **Last Update**: When data was last received from source
- **Events Sent**: Count of messages sent to TAK server
- **Current Status**: Detailed status message and any errors
- **Configuration Summary**: Quick overview of stream settings

### Stream Operations

#### Starting and Stopping Streams
- **Start Stream**: Click the play button to begin data flow
- **Stop Stream**: Click the pause button to temporarily halt stream  
- **Restart Stream**: Stop and start to reset connection and clear errors
- **Bulk Operations**: Select multiple streams for simultaneous control

#### Editing Stream Configuration
1. **Click "Edit"** on the stream you want to modify
2. **Update configuration** fields as needed
3. **Test connection** if credentials or endpoints changed  
4. **Save changes** - stream will restart automatically if active

#### Managing Callsign Mappings (Tracker Streams)
*Available for GPS tracker streams with callsign mapping enabled*

**Viewing Current Callsigns**:
- Stream detail page shows current callsign assignments
- Table displays: Identifier → Assigned Callsign → COT Type (if overridden)
- Status indicators show which trackers are currently active

**Adding New Trackers**:
1. **Click "Refresh Trackers"** to discover new devices
2. **Review new tracker list** - existing assignments are preserved
3. **Assign callsigns** to new trackers using meaningful names
4. **Set COT types** if different from stream default
5. **Save changes** to update mappings

**Modifying Existing Callsigns**:
1. **Navigate to stream edit page**
2. **Scroll to callsign mapping section**
3. **Edit callsign fields** directly in the table
4. **Update COT types** as needed for operational changes
5. **Save stream** to apply changes

**Removing Tracker Mappings**:
- **Clear callsign field** to remove custom assignment (uses default name)
- **Delete mapping** if tracker is no longer in use
- **Bulk operations** available for managing multiple trackers

**Troubleshooting Callsign Issues**:
- **Missing trackers**: Use "Refresh Trackers" to rediscover devices
- **Incorrect names**: Verify identifier field selection matches your devices
- **Mapping failures**: Check error handling setting (fallback vs skip mode)
- **COT type conflicts**: Ensure per-tracker COT types are valid TAK identifiers

#### Stream Troubleshooting
Common issues and solutions:

**Connection Errors**:
- Verify credentials haven't expired or changed
- Check network connectivity to data source
- Confirm data source service is operational

**Authentication Failures**:
- Re-enter username and password
- Check for account lockouts or suspensions
- Verify two-factor authentication isn't required

**No Data Received**:
- Check if source device is powered on and transmitting
- Verify share settings are enabled on source account
- Confirm refresh interval isn't too aggressive

**TAK Server Errors**:
- Verify TAK server is operational and accepting connections
- Check network connectivity between TrakBridge and TAK server
- Confirm TAK server certificates are valid and trusted

**Callsign Mapping Issues**:
- **Callsigns not applying**: Verify callsign mapping is enabled and saved
- **Wrong identifier field**: Check selected field matches your tracker setup
- **Missing new trackers**: Use "Refresh Trackers" to rediscover devices
- **COT type errors**: Ensure per-tracker COT types use valid military identifiers
- **Duplicate callsigns**: Each callsign should be unique within the stream
- **Performance impact**: Disable callsign mapping if experiencing slowdowns

## Monitoring and Maintenance

### Regular Monitoring Tasks

#### Daily Checks
- Review stream status on dashboard
- Verify active streams are receiving data
- Check for any error messages or warnings
- Monitor data flow to TAK servers

#### Weekly Reviews
- Review stream performance and data quality
- Check for any configuration changes needed
- Verify credentials are still valid and functional
- Review any system notifications or alerts

### Data Quality Management

#### Understanding Data Types
Different plugins provide different types of location data:

**GPS Trackers**:
- Precise coordinate data with timestamps
- Battery and signal strength information
- Movement and speed calculations
- Emergency activation status

**OSINT Sources**:
- Situational reports and incident data
- Geographic features and landmarks
- Analyzed intelligence products
- Public domain information

#### Data Validation
- **Coordinate Accuracy**: GPS data should show reasonable precision
- **Timestamp Currency**: Data should be recent and properly timestamped
- **Source Attribution**: Data should clearly indicate origin and reliability
- **Format Consistency**: Data should maintain consistent formatting

### Performance Optimization

#### Refresh Interval Tuning
- **High-Priority Operations**: Shorter intervals (1-5 minutes) for critical data
- **Normal Operations**: Standard intervals (5-10 minutes) for routine monitoring
- **Background Monitoring**: Longer intervals (15-30 minutes) for non-urgent data

#### Resource Management
- Monitor system performance during peak operations
- Adjust refresh intervals during high-load periods
- Balance data currency needs with system capacity
- Coordinate with administrators for system optimization

## User Profile Management

### Password Management
1. **Navigate to Profile** (top-right menu)
2. **Click "Change Password"**
3. **Enter current password** for verification
4. **Set new password** meeting security requirements
5. **Confirm new password** and save changes

### Profile Information
- **Update contact information** for notifications and communication
- **Set timezone preferences** for accurate data display
- **Configure notification settings** for alerts and updates
- **Review assigned permissions** and access levels

## Troubleshooting Common Issues

### Login Problems
**Can't remember password**:
- Contact your system administrator for password reset
- Use "Forgot Password" link if enabled
- Verify account hasn't been locked or disabled

**Account locked**:
- Wait for automatic unlock period (typically 15-30 minutes)
- Contact administrator if immediate access required
- Review failed login attempts with security team

### Stream Creation Issues
**Plugin not available**:
- Verify your role has permission to create streams
- Check if specific plugins are restricted by policy
- Contact administrator about plugin availability

**Connection test fails**:
- Double-check all configuration fields for accuracy
- Verify network connectivity from TrakBridge server
- Test credentials directly with data source
- Review firewall and proxy settings

### Data Flow Problems
**Stream shows active but no data**:
- Verify data source is transmitting (check device status)
- Confirm source account sharing settings are enabled
- Check for data source service outages or maintenance
- Review stream logs for detailed error messages

**Data appears delayed**:
- Check refresh interval settings (may be too long)
- Verify network connectivity and latency
- Monitor system performance during peak hours
- Consider adjusting polling frequency

### TAK Server Integration
**Data not appearing in TAK**:
- Verify TAK server is operational and accessible
- Check TrakBridge to TAK server connectivity
- Confirm TAK server is configured to accept external data
- Review TAK server logs for connection errors

**Coordinate system mismatches**:
- Verify coordinate system settings match TAK requirements
- Check datum and projection configurations
- Confirm data source provides coordinates in expected format
- Contact TAK server administrator for coordinate system requirements

## Best Practices for Operations

### Stream Management
- **Descriptive Naming**: Use clear, consistent naming conventions
- **Regular Testing**: Periodically test stream connections
- **Documentation**: Maintain records of stream purposes and configurations
- **Change Management**: Coordinate configuration changes with team

### Callsign Management (GPS Tracker Streams)
- **Consistent Naming**: Use standardized callsign patterns (e.g., "Alpha-1", "Bravo-2", "Charlie-Lead")
- **Meaningful Identifiers**: Choose callsigns that reflect operational roles or positions
- **Regular Updates**: Keep callsign mappings current as team composition changes
- **Backup Documentation**: Maintain separate record of callsign assignments for reference
- **COT Type Planning**: Use appropriate COT types that reflect actual unit/equipment types
- **Performance Monitoring**: Monitor system performance when using many callsign mappings

### Security Practices
- **Credential Security**: Protect login credentials and device passwords
- **Regular Updates**: Keep passwords current according to policy
- **Access Monitoring**: Report unusual access patterns or unauthorized changes
- **Incident Reporting**: Report security concerns to administrators immediately

### Operational Efficiency
- **Category Organization**: Use plugin categories to organize and find data sources
- **Bulk Operations**: Use multi-select for managing multiple streams simultaneously
- **Status Monitoring**: Develop routine monitoring procedures for critical streams
- **Team Coordination**: Communicate stream changes and issues with team members

### Data Management
- **Quality Control**: Regular review data quality and accuracy
- **Source Verification**: Verify data source authenticity and reliability  
- **Archive Planning**: Coordinate with administrators for data retention policies
- **Backup Procedures**: Understand backup and recovery procedures for critical configurations

## Getting Help

### Self-Service Resources
- **System Status**: Check `/api/health` endpoint for system health
- **Documentation**: Review relevant sections of this user guide
- **Error Messages**: Note exact error messages for troubleshooting
- **Stream Logs**: Check detailed stream logs for diagnostic information

### Administrator Support
Contact your system administrator for:
- **Account Issues**: Password resets, role changes, access problems
- **System Problems**: Server outages, performance issues, configuration errors
- **New Requirements**: Additional plugins, TAK server configurations, policy changes
- **Security Concerns**: Suspected security issues, unauthorized access, policy violations

### Technical Support Resources
- **GitHub Issues**: Report software bugs and feature requests
- **Community Support**: Participate in discussions and community forums
- **Documentation**: Access comprehensive technical documentation
- **Training Materials**: Review available training resources and tutorials

---

**User Guide Version**: 1.3.0  
**Last Updated**: 2025-09-05  
**Applies To**: TrakBridge v1.0.0-rc.4 and later  
**New Features**: Callsign mapping for GPS tracker streams